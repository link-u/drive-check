#!/usr/bin/env python3
"""Salesforce OAuth2 接続を確認する."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from src.salesforce_client import _build_salesforce_client  # noqa: E402


def main() -> None:
    try:
        client = _build_salesforce_client()
    except ValueError as error:
        print(f"接続設定エラー: {error}")
        sys.exit(1)

    identity = client.query(
        "SELECT Id, Username, Email FROM User WHERE Username = '{}'".format(
            os.environ.get("SF_USERNAME", "")
        )
    )
    if identity["totalSize"] == 0:
        sample_user = client.query("SELECT Id, Username, Email FROM User LIMIT 1")
        user = sample_user["records"][0]
    else:
        user = identity["records"][0]
    print("OAuth2 接続成功")
    print(f"  User Id : {user['Id']}")
    print(f"  Username: {user['Username']}")
    print(f"  Email   : {user.get('Email', '')}")

    sample = client.query(
        "SELECT COUNT() FROM teamspirit__AtkEmpDay__c WHERE teamspirit__Date__c = LAST_N_DAYS:7"
    )
    print(f"  直近7日の勤怠日次レコード数: {sample['totalSize']}")


if __name__ == "__main__":
    main()
