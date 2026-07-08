from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser

from src.google_audit_client import AuditEvent
from src.models import AttendanceRecord, OvertimeRecord
from src.config import MatchingConfig


@dataclass
class TimeWindow:
    start: datetime
    end: datetime


@dataclass
class OutsideHoursEvent:
    email: str
    work_date: date
    timestamp: datetime
    application_name: str
    event_name: str
    ip_address: str | None
    detail: str


@dataclass
class DailySummary:
    email: str
    work_date: date
    attendance_start: str | None
    attendance_end: str | None
    approved_overtime_count: int
    outside_event_count: int
    estimated_outside_minutes: int
    first_outside_at: datetime | None
    last_outside_at: datetime | None
    suspicion_level: str


@dataclass
class MatchResult:
    outside_events: list[OutsideHoursEvent]
    daily_summaries: list[DailySummary]


class AttendanceMatcher:
    def __init__(self, config: MatchingConfig):
        self.config = config
        self.tz = ZoneInfo(config.timezone)

    def match(
        self,
        attendance_records: Iterable[AttendanceRecord],
        overtime_records: Iterable[OvertimeRecord],
        audit_events: Iterable[AuditEvent],
    ) -> MatchResult:
        attendance_by_key = _index_attendance(attendance_records)
        overtime_by_key = _index_overtime(overtime_records)
        events_by_key = _index_events(audit_events, self.tz)

        keys = set(events_by_key.keys()) | set(attendance_by_key.keys())
        outside_events: list[OutsideHoursEvent] = []
        daily_summaries: list[DailySummary] = []

        for email, work_date in sorted(keys):
            attendance = attendance_by_key.get((email, work_date))
            if attendance is None and self.config.missing_attendance_policy == "skip":
                continue

            overtime_list = overtime_by_key.get((email, work_date), [])
            allowed_windows = self._build_allowed_windows(attendance, overtime_list, work_date)
            day_events = events_by_key.get((email, work_date), [])

            day_outside: list[OutsideHoursEvent] = []
            for event in day_events:
                local_ts = event.timestamp.astimezone(self.tz)
                if not _is_within_any_window(local_ts, allowed_windows):
                    outside = OutsideHoursEvent(
                        email=email,
                        work_date=work_date,
                        timestamp=local_ts,
                        application_name=event.application_name,
                        event_name=event.event_name,
                        ip_address=event.ip_address,
                        detail=event.detail,
                    )
                    day_outside.append(outside)
                    outside_events.append(outside)

            estimated_minutes = _estimate_session_minutes(
                [item.timestamp for item in day_outside],
                self.config.session_gap_minutes,
            )
            suspicion_level = _classify_suspicion(len(day_outside), estimated_minutes)

            daily_summaries.append(
                DailySummary(
                    email=email,
                    work_date=work_date,
                    attendance_start=attendance.start_time if attendance else None,
                    attendance_end=attendance.end_time if attendance else None,
                    approved_overtime_count=len(overtime_list),
                    outside_event_count=len(day_outside),
                    estimated_outside_minutes=estimated_minutes,
                    first_outside_at=day_outside[0].timestamp if day_outside else None,
                    last_outside_at=day_outside[-1].timestamp if day_outside else None,
                    suspicion_level=suspicion_level,
                )
            )

        outside_events.sort(key=lambda item: (item.email, item.timestamp))
        daily_summaries.sort(key=lambda item: (item.email, item.work_date))
        return MatchResult(outside_events=outside_events, daily_summaries=daily_summaries)

    def _build_allowed_windows(
        self,
        attendance: AttendanceRecord | None,
        overtime_records: list[OvertimeRecord],
        work_date: date,
    ) -> list[TimeWindow]:
        windows: list[TimeWindow] = []

        if attendance and attendance.start_time and attendance.end_time:
            start = _parse_datetime(work_date, attendance.start_time, self.tz)
            end = _parse_datetime(work_date, attendance.end_time, self.tz)
            if start and end:
                windows.append(
                    TimeWindow(
                        start=start - timedelta(minutes=self.config.grace_minutes_before),
                        end=end + timedelta(minutes=self.config.grace_minutes_after),
                    )
                )

        for overtime in overtime_records:
            start = _parse_datetime(work_date, overtime.start_time, self.tz)
            end = _parse_datetime(work_date, overtime.end_time, self.tz)
            if start and end:
                windows.append(TimeWindow(start=start, end=end))

        return _merge_windows(windows)


def _index_attendance(records: Iterable[AttendanceRecord]) -> dict[tuple[str, date], AttendanceRecord]:
    indexed: dict[tuple[str, date], AttendanceRecord] = {}
    for record in records:
        indexed[(record.email, record.work_date)] = record
    return indexed


def _index_overtime(records: Iterable[OvertimeRecord]) -> dict[tuple[str, date], list[OvertimeRecord]]:
    indexed: dict[tuple[str, date], list[OvertimeRecord]] = {}
    for record in records:
        indexed.setdefault((record.email, record.work_date), []).append(record)
    return indexed


def _index_events(
    events: Iterable[AuditEvent],
    tz: ZoneInfo,
) -> dict[tuple[str, date], list[AuditEvent]]:
    indexed: dict[tuple[str, date], list[AuditEvent]] = {}
    for event in events:
        local_date = event.timestamp.astimezone(tz).date()
        indexed.setdefault((event.email, local_date), []).append(event)
    for key in indexed:
        indexed[key].sort(key=lambda item: item.timestamp)
    return indexed


def _parse_datetime(work_date: date, raw_value: str | None, tz: ZoneInfo) -> datetime | None:
    if raw_value is None:
        return None

    text = str(raw_value).strip()
    if not text:
        return None

    if _looks_like_minutes(text):
        return _datetime_from_teamspirit_minutes(work_date, float(text), tz)

    if "T" in text or " " in text:
        parsed = date_parser.isoparse(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)

    time_part = text[:8]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(time_part, fmt).time()
            return datetime.combine(work_date, parsed_time, tzinfo=tz)
        except ValueError:
            continue
    return None


def _looks_like_minutes(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _datetime_from_teamspirit_minutes(work_date: date, minutes_value: float, tz: ZoneInfo) -> datetime:
    total_minutes = int(minutes_value)
    extra_days, minutes_in_day = divmod(total_minutes, 24 * 60)
    hour, minute = divmod(minutes_in_day, 60)
    target_date = work_date + timedelta(days=extra_days)
    return datetime.combine(target_date, time(hour, minute), tzinfo=tz)


def _is_within_any_window(timestamp: datetime, windows: list[TimeWindow]) -> bool:
    if not windows:
        return False
    return any(window.start <= timestamp <= window.end for window in windows)


def _merge_windows(windows: list[TimeWindow]) -> list[TimeWindow]:
    if not windows:
        return []

    sorted_windows = sorted(windows, key=lambda item: item.start)
    merged: list[TimeWindow] = [sorted_windows[0]]

    for window in sorted_windows[1:]:
        last = merged[-1]
        if window.start <= last.end:
            merged[-1] = TimeWindow(start=last.start, end=max(last.end, window.end))
        else:
            merged.append(window)
    return merged


def _estimate_session_minutes(timestamps: list[datetime], gap_minutes: int) -> int:
    if not timestamps:
        return 0

    sorted_ts = sorted(timestamps)
    gap = timedelta(minutes=gap_minutes)
    session_start = sorted_ts[0]
    session_end = sorted_ts[0]
    total_minutes = 0

    for current in sorted_ts[1:]:
        if current - session_end <= gap:
            session_end = current
            continue
        total_minutes += max(1, int((session_end - session_start).total_seconds() // 60) + 1)
        session_start = current
        session_end = current

    total_minutes += max(1, int((session_end - session_start).total_seconds() // 60) + 1)
    return total_minutes


def _classify_suspicion(event_count: int, estimated_minutes: int) -> str:
    if event_count == 0:
        return "問題なし"
    if estimated_minutes >= 60 or event_count >= 20:
        return "要確認（高）"
    if estimated_minutes >= 30 or event_count >= 5:
        return "要確認（中）"
    return "要確認（低）"
