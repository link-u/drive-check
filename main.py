#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, timedelta

from dotenv import load_dotenv

from src.config import load_config
from src.csv_loader import TeamSpiritCsvLoader
from src.audit_cache import load_audit_events, save_audit_events
from src.automated_detector import detect_automated_document_keys
from src.event_filter import filter_audit_events
from src.google_audit_client import GoogleAuditClient
from src.matcher import AttendanceMatcher
from src.report import ReportWriter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TeamSpirit 勤怠 CSV と Google Workspace 監査ログを照合し、勤務時間外操作を検出します。",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="設定ファイルパス (default: config.yaml)",
    )
    parser.add_argument(
        "--start-date",
        help="照合開始日 (YYYY-MM-DD)。未指定時は先月1日",
    )
    parser.add_argument(
        "--end-date",
        help="照合終了日 (YYYY-MM-DD)。未指定時は先月末日",
    )
    parser.add_argument(
        "--email",
        action="append",
        help="照合対象メール（複数可）。未指定時は全員",
    )
    parser.add_argument(
        "--audit-cache",
        help="保存済み監査ログ（JSONL）を読み込み、API 取得をスキップする",
    )
    parser.add_argument(
        "--save-audit-cache",
        help="API 取得した監査ログを JSONL として保存する（デバッグ用）",
    )
    return parser.parse_args()


def _default_period() -> tuple[date, date]:
    today = date.today()
    first_day_this_month = today.replace(day=1)
    last_day_prev_month = first_day_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    return first_day_prev_month, last_day_prev_month


def main() -> None:
    load_dotenv()
    args = parse_args()
    config = load_config(args.config)

    if args.start_date and args.end_date:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    else:
        start_date, end_date = _default_period()

    print(f"照合期間: {start_date} 〜 {end_date}")

    target_emails: set[str] | None = None
    if args.email:
        target_emails = {email.strip().lower() for email in args.email}
        print(f"照合対象: {', '.join(sorted(target_emails))}")
    else:
        print("照合対象: 全員（employees.csv でメール解決できる社員）")

    csv_loader = TeamSpiritCsvLoader(config.input)
    google_client = None if args.audit_cache else GoogleAuditClient(config.google)
    matcher = AttendanceMatcher(config.matching)
    report_writer = ReportWriter(config.output)

    print("TeamSpirit 勤怠 CSV を読み込み中...")
    attendance_records = csv_loader.load_attendance(start_date, end_date, target_emails)
    print(f"  勤怠レコード: {len(attendance_records)} 件")

    print("TeamSpirit 残業申請 CSV を読み込み中...")
    overtime_records = csv_loader.load_overtime(start_date, end_date, target_emails)
    print(f"  残業申請レコード: {len(overtime_records)} 件")

    print("Google 監査ログを取得中...")
    if args.audit_cache:
        audit_events = load_audit_events(args.audit_cache)
        print(f"  キャッシュ読込: {args.audit_cache}")
        print(f"  監査イベント: {len(audit_events)} 件")
    else:
        audit_events = google_client.fetch_events(
            start_date,
            end_date,
            emails=sorted(target_emails) if target_emails else None,
        )
        print(f"  監査イベント: {len(audit_events)} 件")
        if args.save_audit_cache:
            cache_path = save_audit_events(args.save_audit_cache, audit_events)
            print(f"  キャッシュ保存: {cache_path}")

    automated_doc_keys = detect_automated_document_keys(
        audit_events,
        config.matching.detect_automated_edits,
        config.matching.timezone,
    )
    if automated_doc_keys:
        print(f"  自動更新シート検出: {len(automated_doc_keys)} 件（ユーザー × ファイル）")

    audit_events, excluded_count = filter_audit_events(
        audit_events,
        config.matching.exclude_events,
        automated_doc_keys,
    )
    if excluded_count:
        print(f"  除外イベント: {excluded_count} 件（GAS・API・自動更新シート等）")
    print(f"  照合対象イベント: {len(audit_events)} 件")

    print("照合処理を実行中...")
    result = matcher.match(attendance_records, overtime_records, audit_events)

    suspicious_days = [
        summary for summary in result.daily_summaries if summary.outside_event_count > 0
    ]
    print(f"  時間外イベント: {len(result.outside_events)} 件")
    print(f"  要確認日数: {len(suspicious_days)} 日")

    paths = report_writer.write(
        result,
        start_date.isoformat(),
        end_date.isoformat(),
        email_to_name=csv_loader.email_to_name,
    )
    print("レポート出力完了:")
    print(f"  イベント詳細: {paths['events']}")
    print(f"  日次サマリー: {paths['summary']}")


if __name__ == "__main__":
    main()
