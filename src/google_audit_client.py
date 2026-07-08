from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import GoogleConfig

# Reports API activities.list で利用可能な applicationName
ALL_APPLICATION_NAMES = [
    "access_transparency",
    "admin",
    "calendar",
    "chat",
    "chrome",
    "cloud_search",
    "drive",
    "gcp",
    "gmail",
    "groups",
    "groups_enterprise",
    "jamboard",
    "keep",
    "login",
    "meet",
    "mobile",
    "rules",
    "saml",
    "token",
    "user_accounts",
]

SCOPES = ["https://www.googleapis.com/auth/admin.reports.audit.readonly"]


@dataclass
class AuditEvent:
    email: str
    timestamp: datetime
    application_name: str
    event_name: str
    ip_address: str | None
    detail: str


class GoogleAuditClient:
    def __init__(self, config: GoogleConfig):
        if not config.credentials_path:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS が未設定です")
        if not config.admin_email:
            raise ValueError("GOOGLE_ADMIN_EMAIL が未設定です")

        credentials = service_account.Credentials.from_service_account_file(
            config.credentials_path,
            scopes=SCOPES,
        ).with_subject(config.admin_email)
        self._service = build("admin", "reports_v1", credentials=credentials, cache_discovery=False)
        self._application_names = self._resolve_application_names(config.application_names)

    def _resolve_application_names(self, configured: list[str] | str) -> list[str]:
        if configured == "all":
            return ALL_APPLICATION_NAMES.copy()
        return list(configured)

    def fetch_events(
        self,
        start_date: date,
        end_date: date,
        emails: list[str] | None = None,
        max_pages: int | None = None,
    ) -> list[AuditEvent]:
        start_time = _date_to_rfc3339(start_date, end_of_day=False)
        end_time = _date_to_rfc3339(end_date, end_of_day=True)
        events: list[AuditEvent] = []
        user_keys = emails if emails else ["all"]

        for application_name in self._application_names:
            for user_key in user_keys:
                events.extend(
                    self._fetch_application_events(
                        application_name=application_name,
                        start_time=start_time,
                        end_time=end_time,
                        user_key=user_key,
                        max_pages=max_pages,
                    )
                )
        return events

    def _fetch_application_events(
        self,
        application_name: str,
        start_time: str,
        end_time: str,
        user_key: str = "all",
        max_pages: int | None = None,
    ) -> list[AuditEvent]:
        page_token: str | None = None
        collected: list[AuditEvent] = []
        pages_fetched = 0

        while True:
            try:
                request = (
                    self._service.activities()
                    .list(
                        userKey=user_key,
                        applicationName=application_name,
                        startTime=start_time,
                        endTime=end_time,
                        maxResults=1000,
                        pageToken=page_token,
                    )
                )
                response = _execute_with_retry(request)
            except HttpError as error:
                if error.resp.status in {400, 404}:
                    return collected
                raise

            for activity in response.get("items", []):
                parsed = _parse_activity(activity, application_name)
                if parsed:
                    collected.extend(parsed)

            pages_fetched += 1
            page_token = response.get("nextPageToken")
            if not page_token:
                break
            if max_pages is not None and pages_fetched >= max_pages:
                break

        return collected


def _execute_with_retry(request: Any, max_attempts: int = 5) -> dict[str, Any]:
    delay_seconds = 1.0
    for attempt in range(max_attempts):
        try:
            return request.execute()
        except HttpError as error:
            if error.resp.status in {429, 500, 503} and attempt < max_attempts - 1:
                time.sleep(delay_seconds)
                delay_seconds *= 2
                continue
            raise
    raise RuntimeError("Google API request failed after retries")


def _parse_activity(activity: dict[str, Any], application_name: str) -> list[AuditEvent]:
    actor = activity.get("actor", {})
    email = actor.get("email")
    if not email:
        return []

    id_info = activity.get("id", {})
    time_raw = id_info.get("time")
    if not time_raw:
        return []

    timestamp = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
    ip_address = actor.get("ipAddress")
    parsed_events: list[AuditEvent] = []

    for event in activity.get("events", []):
        event_name = event.get("name", "unknown")
        detail = _format_event_detail(event)
        parsed_events.append(
            AuditEvent(
                email=str(email).lower(),
                timestamp=timestamp,
                application_name=application_name,
                event_name=event_name,
                ip_address=ip_address,
                detail=detail,
            )
        )

    return parsed_events


def _format_event_detail(event: dict[str, Any]) -> str:
    parts: list[str] = []
    for parameter in event.get("parameters", []):
        name = parameter.get("name")
        value = (
            parameter.get("value")
            or parameter.get("intValue")
            or parameter.get("boolValue")
            or parameter.get("multiValue")
        )
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _date_to_rfc3339(target_date: date, end_of_day: bool) -> str:
    if end_of_day:
        dt = datetime.combine(target_date, datetime.max.time()).replace(microsecond=0)
    else:
        dt = datetime.combine(target_date, datetime.min.time())
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
