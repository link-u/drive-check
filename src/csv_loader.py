from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser

from src.config import InputConfig
from src.models import AttendanceRecord, OvertimeRecord


class TeamSpiritCsvLoader:
    def __init__(self, config: InputConfig):
        self.config = config
        self.input_dir = Path(config.directory)
        self._email_by_code, self._email_by_name, self._email_to_name = _load_employee_mapping(
            self.input_dir / config.employee_mapping_file,
            config.encoding,
        )

    @property
    def email_to_name(self) -> dict[str, str]:
        return self._email_to_name

    def load_attendance(
        self,
        start_date: date,
        end_date: date,
        emails: set[str] | None = None,
    ) -> list[AttendanceRecord]:
        path = self.input_dir / self.config.attendance_file
        if not path.exists():
            raise FileNotFoundError(
                f"勤怠 CSV が見つかりません: {path}\n"
                f"TeamSpirit からエクスポートした CSV を input/ に配置してください。"
            )

        mapping = self.config.column_mapping["attendance"]
        records: list[AttendanceRecord] = []
        skipped_no_email = 0
        skipped_no_punch = 0

        for row in _read_csv_rows(path, self.config.encoding):
            work_date = _parse_date(_get_cell(row, mapping["date"]))
            if not work_date or work_date < start_date or work_date > end_date:
                continue

            email = _resolve_email(row, mapping, self._email_by_code, self._email_by_name)
            if not email:
                skipped_no_email += 1
                continue
            if emails and email not in emails:
                continue

            start_time = _first_present(
                _get_cell(row, mapping["start_time"]),
                _get_cell(row, mapping.get("shift_start_time", [])),
            )
            end_time = _first_present(
                _get_cell(row, mapping["end_time"]),
                _get_cell(row, mapping.get("shift_end_time", [])),
            )
            if not start_time or not end_time:
                skipped_no_punch += 1
                continue

            records.append(
                AttendanceRecord(
                    email=email,
                    work_date=work_date,
                    start_time=_normalize_time(start_time),
                    end_time=_normalize_time(end_time),
                )
            )

        if skipped_no_email:
            print(
                f"  警告: メール未解決の行を {skipped_no_email} 件スキップしました。"
                f" {self.config.employee_mapping_file} を確認してください。"
            )
        if skipped_no_punch:
            print(f"  情報: 出退勤なし（休日等）の行を {skipped_no_punch} 件スキップしました。")

        return records

    def load_overtime(
        self,
        start_date: date,
        end_date: date,
        emails: set[str] | None = None,
    ) -> list[OvertimeRecord]:
        if not self.config.overtime_file:
            return []

        path = self.input_dir / self.config.overtime_file
        if not path.exists():
            return []

        mapping = self.config.column_mapping["overtime"]
        filters = self.config.overtime_filters
        approved_statuses = {str(value) for value in filters.get("approved_statuses", [])}
        apply_types = {str(value) for value in filters.get("apply_types", [])}
        records: list[OvertimeRecord] = []

        for row in _read_csv_rows(path, self.config.encoding):
            apply_start = _parse_date(_get_cell(row, mapping["start_date"]))
            apply_end = _parse_date(_get_cell(row, mapping.get("end_date", mapping["start_date"])))
            status = _get_cell(row, mapping.get("status", []))
            apply_type = _get_cell(row, mapping.get("apply_type", []))

            email = _resolve_email(row, mapping, self._email_by_code, self._email_by_name)
            if not email or not apply_start:
                continue
            if emails and email not in emails:
                continue
            if approved_statuses and str(status) not in approved_statuses:
                continue
            if apply_types and str(apply_type) not in apply_types:
                continue

            apply_end = apply_end or apply_start
            range_start = max(apply_start, start_date)
            range_end = min(apply_end, end_date)
            start_time = _normalize_time(_get_cell(row, mapping["start_time"]))
            end_time = _normalize_time(_get_cell(row, mapping["end_time"]))

            current = range_start
            while current <= range_end:
                records.append(
                    OvertimeRecord(
                        email=email,
                        work_date=current,
                        start_time=start_time,
                        end_time=end_time,
                        status=str(status) if status is not None else None,
                        apply_type=str(apply_type) if apply_type is not None else None,
                    )
                )
                current += timedelta(days=1)

        return records


def _load_employee_mapping(
    path: Path,
    encoding: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    by_code: dict[str, str] = {}
    by_name: dict[str, str] = {}
    by_email_to_name: dict[str, str] = {}
    if not path.exists():
        return by_code, by_name, by_email_to_name

    for row in _read_csv_rows(path, encoding):
        email = _get_cell(row, ["メール", "Email", "email", "メールアドレス", "ユーザ: メール"])
        if not email:
            continue
        email = email.lower()
        code = _get_cell(row, ["社員コード", "employee_code", "EmpCode"])
        name = _get_cell(row, ["社員名", "employee_name", "Name"])
        if code:
            by_code[code] = email
        if name:
            by_name[name] = email
            by_email_to_name[email] = name
    return by_code, by_name, by_email_to_name


def _resolve_email(
    row: dict[str, str],
    mapping: dict[str, Any],
    by_code: dict[str, str],
    by_name: dict[str, str],
) -> str | None:
    direct = _get_cell(row, mapping.get("email", []))
    if direct:
        return direct.lower()

    code = _get_cell(row, mapping.get("employee_code", []))
    if code and code in by_code:
        return by_code[code]

    name = _get_cell(row, mapping.get("employee_name", []))
    if name and name in by_name:
        return by_name[name]

    return None


def _read_csv_rows(path: Path, encoding: str) -> list[dict[str, str]]:
    with path.open(encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV にヘッダー行がありません: {path}")
        return [dict(row) for row in reader]


def _get_cell(row: dict[str, str], candidates: list[str] | str) -> str | None:
    if isinstance(candidates, str):
        candidates = [candidates]
    for candidate in candidates:
        if candidate in row:
            value = row[candidate]
            if value is not None and str(value).strip() != "":
                return str(value).strip()
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] in "-/":
        return date.fromisoformat(text[:10].replace("/", "-"))
    parsed = date_parser.parse(text)
    return parsed.date()


def _normalize_time(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _first_present(*values: str | None) -> str | None:
    for value in values:
        if value is not None and str(value).strip() != "":
            return value
    return None
