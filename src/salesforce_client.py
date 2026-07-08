from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from simple_salesforce import Salesforce

from src.models import AttendanceRecord, OvertimeRecord


def _get_nested_value(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _build_salesforce_client() -> Salesforce:
    client_id = os.environ.get("SF_CLIENT_ID")
    client_secret = os.environ.get("SF_CLIENT_SECRET")
    refresh_token = os.environ.get("SF_REFRESH_TOKEN")
    instance_url = os.environ.get("SF_INSTANCE_URL")
    domain = os.environ.get("SF_DOMAIN", "login")

    if client_id and client_secret:
        if not refresh_token or not instance_url:
            raise ValueError(
                "OAuth2 接続には SF_REFRESH_TOKEN と SF_INSTANCE_URL が必要です。\n"
                "初回のみ: python scripts/get_salesforce_token.py を実行してください。"
            )
        return Salesforce(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            instance_url=instance_url,
        )

    username = os.environ.get("SF_USERNAME")
    password = os.environ.get("SF_PASSWORD")
    if username and password:
        return Salesforce(
            username=username,
            password=password,
            security_token=os.environ.get("SF_SECURITY_TOKEN", ""),
            domain=domain,
        )

    raise ValueError(
        "Salesforce 認証情報が未設定です。\n"
        "OAuth2: SF_CLIENT_ID, SF_CLIENT_SECRET, SF_REFRESH_TOKEN, SF_INSTANCE_URL\n"
        "または ID/Pass: SF_USERNAME, SF_PASSWORD"
    )


def _format_soql(template: str, start_date: date, end_date: date) -> str:
    return (
        template.replace(":start_date", start_date.isoformat())
        .replace(":end_date", end_date.isoformat())
    )


def _parse_salesforce_date(value: Any) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value)[:10])


class SalesforceClient:
    def __init__(self, attendance_soql: str, overtime_soql: str, field_mapping: dict[str, Any]):
        self.attendance_soql = attendance_soql
        self.overtime_soql = overtime_soql
        self.field_mapping = field_mapping
        self._client: Salesforce | None = None

    @property
    def client(self) -> Salesforce:
        if self._client is None:
            self._client = _build_salesforce_client()
        return self._client

    def fetch_attendance(self, start_date: date, end_date: date) -> list[AttendanceRecord]:
        mapping = self.field_mapping["attendance"]
        soql = _format_soql(self.attendance_soql, start_date, end_date)
        result = self.client.query_all(soql)
        records: list[AttendanceRecord] = []

        for row in result["records"]:
            email = _get_nested_value(row, mapping["email"])
            work_date_raw = _get_nested_value(row, mapping["date"])
            if not email or not work_date_raw:
                continue

            start_time = _first_present(
                _get_nested_value(row, mapping["start_time"]),
                _get_nested_value(row, mapping["shift_start_time"])
                if mapping.get("shift_start_time")
                else None,
            )
            end_time = _first_present(
                _get_nested_value(row, mapping["end_time"]),
                _get_nested_value(row, mapping["shift_end_time"])
                if mapping.get("shift_end_time")
                else None,
            )

            records.append(
                AttendanceRecord(
                    email=str(email).lower(),
                    work_date=date.fromisoformat(str(work_date_raw)[:10]),
                    start_time=_normalize_optional_time(start_time),
                    end_time=_normalize_optional_time(end_time),
                )
            )
        return records

    def fetch_overtime(self, start_date: date, end_date: date) -> list[OvertimeRecord]:
        mapping = self.field_mapping["overtime"]
        approved_statuses = {str(value) for value in mapping.get("approved_statuses", [])}
        overtime_apply_types = {str(value) for value in mapping.get("overtime_apply_types", [])}
        soql = _format_soql(self.overtime_soql, start_date, end_date)
        result = self.client.query_all(soql)
        records: list[OvertimeRecord] = []

        for row in result["records"]:
            email = _get_nested_value(row, mapping["email"])
            apply_start = _parse_salesforce_date(_get_nested_value(row, mapping["start_date"]))
            apply_end = _parse_salesforce_date(_get_nested_value(row, mapping["end_date"]))
            status = _get_nested_value(row, mapping["status"])
            apply_type = _get_nested_value(row, mapping["apply_type"])

            if not email or not apply_start:
                continue
            if approved_statuses and str(status) not in approved_statuses:
                continue
            if overtime_apply_types and str(apply_type) not in overtime_apply_types:
                continue

            apply_end = apply_end or apply_start
            range_start = max(apply_start, start_date)
            range_end = min(apply_end, end_date)
            start_time = _normalize_optional_time(_get_nested_value(row, mapping["start_time"]))
            end_time = _normalize_optional_time(_get_nested_value(row, mapping["end_time"]))

            current = range_start
            while current <= range_end:
                records.append(
                    OvertimeRecord(
                        email=str(email).lower(),
                        work_date=current,
                        start_time=start_time,
                        end_time=end_time,
                        status=str(status) if status is not None else None,
                        apply_type=str(apply_type) if apply_type is not None else None,
                    )
                )
                current += timedelta(days=1)

        return records


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip() != "":
            return value
    return None


def _normalize_optional_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
