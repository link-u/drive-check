from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.google_audit_client import AuditEvent


def save_audit_events(path: str | Path, events: list[AuditEvent]) -> Path:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with cache_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(
                json.dumps(
                    {
                        "email": event.email,
                        "timestamp": event.timestamp.isoformat(),
                        "application_name": event.application_name,
                        "event_name": event.event_name,
                        "ip_address": event.ip_address,
                        "detail": event.detail,
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")

    return cache_path


def load_audit_events(path: str | Path) -> list[AuditEvent]:
    cache_path = Path(path)
    if not cache_path.exists():
        raise FileNotFoundError(f"監査ログキャッシュが見つかりません: {cache_path}")

    events: list[AuditEvent] = []
    with cache_path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue

            raw = json.loads(text)
            timestamp = raw["timestamp"]
            if timestamp.endswith("Z"):
                timestamp = timestamp.replace("Z", "+00:00")

            events.append(
                AuditEvent(
                    email=str(raw["email"]).lower(),
                    timestamp=datetime.fromisoformat(timestamp),
                    application_name=raw["application_name"],
                    event_name=raw["event_name"],
                    ip_address=raw.get("ip_address"),
                    detail=raw.get("detail", ""),
                )
            )

    return events
