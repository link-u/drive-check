from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from src.config import OutputConfig
from src.matcher import DailySummary, MatchResult, OutsideHoursEvent


class ReportWriter:
    def __init__(self, config: OutputConfig):
        self.config = config

    def write(
        self,
        result: MatchResult,
        start_label: str,
        end_label: str,
        email_to_name: dict[str, str] | None = None,
    ) -> dict[str, Path]:
        output_dir = Path(self.config.directory)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{self.config.csv_prefix}_{start_label}_{end_label}_{timestamp}"

        events_path = output_dir / f"{prefix}_events.csv"
        summary_path = output_dir / f"{prefix}_summary.csv"

        _write_events_csv(events_path, result.outside_events)
        _write_summary_csv(summary_path, result.daily_summaries, email_to_name or {})

        return {
            "events": events_path,
            "summary": summary_path,
        }


def _write_events_csv(path: Path, events: list[OutsideHoursEvent]) -> None:
    headers = [
        "email",
        "work_date",
        "timestamp",
        "application_name",
        "event_name",
        "ip_address",
        "detail",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "email": event.email,
                    "work_date": event.work_date.isoformat(),
                    "timestamp": event.timestamp.isoformat(),
                    "application_name": event.application_name,
                    "event_name": event.event_name,
                    "ip_address": event.ip_address or "",
                    "detail": event.detail,
                }
            )


def _write_summary_csv(
    path: Path,
    summaries: list[DailySummary],
    email_to_name: dict[str, str],
) -> None:
    headers = [
        "employee_name",
        "email",
        "work_date",
        "attendance_start",
        "attendance_end",
        "approved_overtime_count",
        "outside_event_count",
        "estimated_outside_minutes",
        "first_outside_at",
        "last_outside_at",
        "suspicion_level",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(
                {
                    "employee_name": email_to_name.get(summary.email, ""),
                    "email": summary.email,
                    "work_date": summary.work_date.isoformat(),
                    "attendance_start": summary.attendance_start or "",
                    "attendance_end": summary.attendance_end or "",
                    "approved_overtime_count": summary.approved_overtime_count,
                    "outside_event_count": summary.outside_event_count,
                    "estimated_outside_minutes": summary.estimated_outside_minutes,
                    "first_outside_at": summary.first_outside_at.isoformat() if summary.first_outside_at else "",
                    "last_outside_at": summary.last_outside_at.isoformat() if summary.last_outside_at else "",
                    "suspicion_level": summary.suspicion_level,
                }
            )
