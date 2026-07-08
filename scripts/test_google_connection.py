#!/usr/bin/env python3
"""Google Workspace 監査ログ API 接続を確認する."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from src.config import load_config  # noqa: E402
from src.google_audit_client import GoogleAuditClient  # noqa: E402


def main() -> None:
    config_path = ROOT / "config.yaml"
    if not config_path.exists():
        config_path = ROOT / "config.example.yaml"

    try:
        config = load_config(config_path)
        client = GoogleAuditClient(config.google)
    except ValueError as error:
        print(f"接続設定エラー: {error}")
        sys.exit(1)

    end_date = date.today()
    start_date = end_date - timedelta(days=1)

    print("Google 監査ログ API 接続テスト")
    print(f"  管理者メール: {config.google.admin_email}")
    print(f"  認証情報    : {config.google.credentials_path}")
    print(f"  取得期間    : {start_date} 〜 {end_date}（drive のみ）")

    original_apps = client._application_names
    client._application_names = ["drive"]
    try:
        events = client.fetch_events(start_date, end_date, max_pages=1)
    finally:
        client._application_names = original_apps

    print(f"接続成功: drive イベント {len(events)} 件")
    if events:
        sample = events[0]
        print(f"  サンプル: {sample.email} / {sample.timestamp} / {sample.event_name}")


if __name__ == "__main__":
    main()
