from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from statistics import median
from typing import Iterable
from zoneinfo import ZoneInfo

from src.config import AutomatedEditDetectionConfig
from src.google_audit_client import AuditEvent


def detect_automated_document_keys(
    events: Iterable[AuditEvent],
    config: AutomatedEditDetectionConfig,
    timezone: str,
) -> set[tuple[str, str]]:
    if not config.enabled:
        return set()

    tz = ZoneInfo(timezone)
    activity_by_doc = _group_drive_activity_by_doc(events, tz)

    automated: set[tuple[str, str]] = set()
    for doc_key, days in activity_by_doc.items():
        if _matches_any_automation_pattern(days, config):
            automated.add(doc_key)

    return automated


def extract_doc_id(detail: str) -> str | None:
    marker = "doc_id="
    index = detail.find(marker)
    if index == -1:
        return None

    start = index + len(marker)
    end = detail.find(";", start)
    if end == -1:
        return detail[start:]

    return detail[start:end]


def _group_drive_activity_by_doc(
    events: Iterable[AuditEvent],
    tz: ZoneInfo,
) -> dict[tuple[str, str], dict[date, list[datetime]]]:
    activity_by_doc: dict[tuple[str, str], dict[date, list[datetime]]] = defaultdict(dict)

    for event in events:
        if event.application_name != "drive":
            continue

        doc_id = extract_doc_id(event.detail)
        if not doc_id:
            continue

        work_date = event.timestamp.astimezone(tz).date()
        doc_key = (event.email, doc_id)
        local_timestamp = event.timestamp.astimezone(tz)
        activity_by_doc[doc_key].setdefault(work_date, []).append(local_timestamp)

    return activity_by_doc


def _matches_any_automation_pattern(
    days: dict[date, list[datetime]],
    config: AutomatedEditDetectionConfig,
) -> bool:
    if _high_frequency_qualifying_days(days, config) >= config.min_automated_days:
        return True

    if len(days) < config.min_automated_days:
        return False

    return (
        _is_scheduled_burst_automation(days, config)
        or _is_paired_activity_automation(days, config)
        or _is_fixed_schedule_automation(days, config)
        or _is_sparse_recurring_automation(days, config)
    )


def _high_frequency_qualifying_days(
    days: dict[date, list[datetime]],
    config: AutomatedEditDetectionConfig,
) -> int:
    qualifying_days = 0
    for timestamps in days.values():
        if _looks_like_high_frequency_day(timestamps, config):
            qualifying_days += 1
    return qualifying_days


def _looks_like_high_frequency_day(
    timestamps: list[datetime],
    config: AutomatedEditDetectionConfig,
) -> bool:
    if len(timestamps) < config.min_edits_per_day:
        return False

    distinct_hours = {timestamp.hour for timestamp in timestamps}
    if len(distinct_hours) < config.min_distinct_hours:
        return False

    sorted_timestamps = sorted(timestamps)
    gaps_minutes = [
        (sorted_timestamps[index + 1] - sorted_timestamps[index]).total_seconds() / 60
        for index in range(len(sorted_timestamps) - 1)
    ]
    if not gaps_minutes:
        return False

    return median(gaps_minutes) <= config.max_median_gap_minutes


def _is_scheduled_burst_automation(
    days: dict[date, list[datetime]],
    config: AutomatedEditDetectionConfig,
) -> bool:
    num_days = len(days)
    average_events = _average_events_per_day(days)
    if average_events < config.min_avg_events_per_day:
        return False

    recurring_hours = _count_recurring_hours(days, config.recurring_hour_day_ratio)
    if recurring_hours < config.min_recurring_hours:
        return False

    daily_medians = _daily_gap_medians(days)
    if daily_medians and median(daily_medians) > config.max_burst_median_gap_minutes:
        return False

    return True


def _is_paired_activity_automation(
    days: dict[date, list[datetime]],
    config: AutomatedEditDetectionConfig,
) -> bool:
    num_days = len(days)
    if num_days < config.min_paired_days:
        return False

    average_events = _average_events_per_day(days)
    if average_events < config.min_paired_avg_per_day:
        return False

    daily_medians = _daily_gap_medians(days)
    if not daily_medians:
        return False

    return median(daily_medians) <= config.max_paired_median_gap_minutes


def _is_fixed_schedule_automation(
    days: dict[date, list[datetime]],
    config: AutomatedEditDetectionConfig,
) -> bool:
    num_days = len(days)
    if num_days < config.min_fixed_schedule_days:
        return False

    average_events = _average_events_per_day(days)
    if average_events < config.min_fixed_schedule_avg_per_day:
        return False

    hour_day_counts = Counter()
    for timestamps in days.values():
        for hour in {timestamp.hour for timestamp in timestamps}:
            hour_day_counts[hour] += 1

    threshold = num_days * config.fixed_hour_day_ratio
    return any(count >= threshold for count in hour_day_counts.values())


def _is_sparse_recurring_automation(
    days: dict[date, list[datetime]],
    config: AutomatedEditDetectionConfig,
) -> bool:
    """Detect n8n / external cron: low volume, many days, scattered hours."""
    num_days = len(days)
    if num_days < config.min_sparse_active_days:
        return False

    average_events = _average_events_per_day(days)
    if average_events < config.min_sparse_avg_per_day:
        return False
    if average_events > config.max_sparse_avg_per_day:
        return False

    hour_day_counts = Counter()
    distinct_hours: set[int] = set()
    for timestamps in days.values():
        day_hours = {timestamp.hour for timestamp in timestamps}
        distinct_hours.update(day_hours)
        for hour in day_hours:
            hour_day_counts[hour] += 1

    if len(distinct_hours) < config.min_sparse_distinct_hours:
        return False

    dominant_ratio = max(hour_day_counts.values()) / num_days
    if dominant_ratio >= config.sparse_max_dominant_hour_day_ratio:
        return False

    return True


def _average_events_per_day(days: dict[date, list[datetime]]) -> float:
    return sum(len(timestamps) for timestamps in days.values()) / len(days)


def _count_recurring_hours(days: dict[date, list[datetime]], day_ratio: float) -> int:
    num_days = len(days)
    hour_day_counts = Counter()
    for timestamps in days.values():
        for hour in {timestamp.hour for timestamp in timestamps}:
            hour_day_counts[hour] += 1

    threshold = max(3, int(num_days * day_ratio))
    return sum(1 for count in hour_day_counts.values() if count >= threshold)


def _daily_gap_medians(days: dict[date, list[datetime]]) -> list[float]:
    daily_medians: list[float] = []
    for timestamps in days.values():
        sorted_timestamps = sorted(timestamps)
        gaps_minutes = [
            (sorted_timestamps[index + 1] - sorted_timestamps[index]).total_seconds() / 60
            for index in range(len(sorted_timestamps) - 1)
        ]
        if gaps_minutes:
            daily_medians.append(median(gaps_minutes))
    return daily_medians
