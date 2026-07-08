from __future__ import annotations

from src.automated_detector import extract_doc_id
from src.config import EventExcludeConfig
from src.google_audit_client import AuditEvent


def is_excluded(
    event: AuditEvent,
    config: EventExcludeConfig,
    automated_doc_keys: set[tuple[str, str]] | None = None,
) -> bool:
    for substring in config.detail_substrings:
        if substring in event.detail:
            return True

    for doc_title in config.doc_title_substrings:
        if _detail_has_doc_title(event.detail, doc_title):
            return True

    if automated_doc_keys:
        doc_id = extract_doc_id(event.detail)
        if doc_id and (event.email, doc_id) in automated_doc_keys:
            return True

    for application_name, event_name in config.application_events:
        if event.application_name == application_name and event.event_name == event_name:
            return True

    return False


def filter_audit_events(
    events: list[AuditEvent],
    config: EventExcludeConfig,
    automated_doc_keys: set[tuple[str, str]] | None = None,
) -> tuple[list[AuditEvent], int]:
    kept: list[AuditEvent] = []
    excluded_count = 0

    for event in events:
        if is_excluded(event, config, automated_doc_keys):
            excluded_count += 1
            continue
        kept.append(event)

    return kept, excluded_count


def _detail_has_doc_title(detail: str, doc_title: str) -> bool:
    marker = f"doc_title={doc_title}"
    index = detail.find(marker)
    if index == -1:
        return False

    next_index = index + len(marker)
    if next_index == len(detail):
        return True

    return detail[next_index] == ";"
