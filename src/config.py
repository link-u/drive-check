from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class InputConfig:
    directory: str
    attendance_file: str
    overtime_file: str
    employee_mapping_file: str
    encoding: str
    column_mapping: dict[str, Any]
    overtime_filters: dict[str, Any]


@dataclass
class GoogleConfig:
    application_names: list[str] | str
    admin_email: str
    credentials_path: str


@dataclass
class EventExcludeConfig:
    detail_substrings: list[str]
    application_events: list[tuple[str, str]]
    doc_title_substrings: list[str]


@dataclass
class AutomatedEditDetectionConfig:
    enabled: bool
    min_edits_per_day: int
    min_distinct_hours: int
    max_median_gap_minutes: int
    min_automated_days: int
    min_avg_events_per_day: int
    min_recurring_hours: int
    recurring_hour_day_ratio: float
    max_burst_median_gap_minutes: int
    min_paired_days: int
    min_paired_avg_per_day: int
    max_paired_median_gap_minutes: float
    min_fixed_schedule_days: int
    min_fixed_schedule_avg_per_day: float
    fixed_hour_day_ratio: float
    min_sparse_active_days: int
    min_sparse_avg_per_day: float
    max_sparse_avg_per_day: float
    min_sparse_distinct_hours: int
    sparse_max_dominant_hour_day_ratio: float


@dataclass
class MatchingConfig:
    timezone: str
    grace_minutes_before: int
    grace_minutes_after: int
    session_gap_minutes: int
    missing_attendance_policy: str
    exclude_events: EventExcludeConfig
    detect_automated_edits: AutomatedEditDetectionConfig


@dataclass
class OutputConfig:
    directory: str
    csv_prefix: str


@dataclass
class AppConfig:
    input: InputConfig
    google: GoogleConfig
    matching: MatchingConfig
    output: OutputConfig


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    google_raw = raw["google"]
    input_raw = raw["input"]

    return AppConfig(
        input=InputConfig(
            directory=input_raw.get("directory", "input"),
            attendance_file=input_raw["attendance_file"],
            overtime_file=input_raw.get("overtime_file", ""),
            employee_mapping_file=input_raw.get("employee_mapping_file", "employees.csv"),
            encoding=input_raw.get("encoding", "utf-8-sig"),
            column_mapping=input_raw["column_mapping"],
            overtime_filters=input_raw.get("overtime_filters", {}),
        ),
        google=GoogleConfig(
            application_names=google_raw.get("application_names", "all"),
            admin_email=os.environ.get("GOOGLE_ADMIN_EMAIL", google_raw.get("admin_email", "")),
            credentials_path=os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS",
                google_raw.get("credentials_path", ""),
            ),
        ),
        matching=MatchingConfig(
            timezone=raw["matching"]["timezone"],
            grace_minutes_before=raw["matching"]["grace_minutes_before"],
            grace_minutes_after=raw["matching"]["grace_minutes_after"],
            session_gap_minutes=raw["matching"]["session_gap_minutes"],
            missing_attendance_policy=raw["matching"]["missing_attendance_policy"],
            exclude_events=_load_exclude_config(raw["matching"].get("exclude_events")),
            detect_automated_edits=_load_automated_edit_detection_config(
                raw["matching"].get("detect_automated_edits")
            ),
        ),
        output=OutputConfig(**raw["output"]),
    )


def _load_exclude_config(raw: dict[str, Any] | None) -> EventExcludeConfig:
    if not raw:
        return EventExcludeConfig(
            detail_substrings=[],
            application_events=[],
            doc_title_substrings=[],
        )

    application_events: list[tuple[str, str]] = []
    for item in raw.get("application_events", []):
        application_events.append((item["application_name"], item["event_name"]))

    return EventExcludeConfig(
        detail_substrings=list(raw.get("detail_substrings", [])),
        application_events=application_events,
        doc_title_substrings=list(raw.get("doc_title_substrings", [])),
    )


def _load_automated_edit_detection_config(
    raw: dict[str, Any] | None,
) -> AutomatedEditDetectionConfig:
    if not raw:
        return AutomatedEditDetectionConfig(
            enabled=False,
            min_edits_per_day=20,
            min_distinct_hours=8,
            max_median_gap_minutes=15,
            min_automated_days=3,
            min_avg_events_per_day=3,
            min_recurring_hours=3,
            recurring_hour_day_ratio=0.5,
            max_burst_median_gap_minutes=60,
            min_paired_days=5,
            min_paired_avg_per_day=2,
            max_paired_median_gap_minutes=1.0,
            min_fixed_schedule_days=10,
            min_fixed_schedule_avg_per_day=1.0,
            fixed_hour_day_ratio=0.7,
            min_sparse_active_days=10,
            min_sparse_avg_per_day=1.0,
            max_sparse_avg_per_day=4.0,
            min_sparse_distinct_hours=4,
            sparse_max_dominant_hour_day_ratio=0.6,
        )

    return AutomatedEditDetectionConfig(
        enabled=bool(raw.get("enabled", True)),
        min_edits_per_day=int(raw.get("min_edits_per_day", 20)),
        min_distinct_hours=int(raw.get("min_distinct_hours", 8)),
        max_median_gap_minutes=int(raw.get("max_median_gap_minutes", 15)),
        min_automated_days=int(raw.get("min_automated_days", 3)),
        min_avg_events_per_day=int(raw.get("min_avg_events_per_day", 3)),
        min_recurring_hours=int(raw.get("min_recurring_hours", 3)),
        recurring_hour_day_ratio=float(raw.get("recurring_hour_day_ratio", 0.5)),
        max_burst_median_gap_minutes=int(raw.get("max_burst_median_gap_minutes", 60)),
        min_paired_days=int(raw.get("min_paired_days", 5)),
        min_paired_avg_per_day=int(raw.get("min_paired_avg_per_day", 2)),
        max_paired_median_gap_minutes=float(raw.get("max_paired_median_gap_minutes", 1.0)),
        min_fixed_schedule_days=int(raw.get("min_fixed_schedule_days", 10)),
        min_fixed_schedule_avg_per_day=float(raw.get("min_fixed_schedule_avg_per_day", 1.0)),
        fixed_hour_day_ratio=float(raw.get("fixed_hour_day_ratio", 0.7)),
        min_sparse_active_days=int(raw.get("min_sparse_active_days", 10)),
        min_sparse_avg_per_day=float(raw.get("min_sparse_avg_per_day", 1.0)),
        max_sparse_avg_per_day=float(raw.get("max_sparse_avg_per_day", 4.0)),
        min_sparse_distinct_hours=int(raw.get("min_sparse_distinct_hours", 4)),
        sparse_max_dominant_hour_day_ratio=float(
            raw.get("sparse_max_dominant_hour_day_ratio", 0.6)
        ),
    )
