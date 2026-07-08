#!/usr/bin/env python3
"""Salesforce OAuth (PKCE 対応) で Refresh Token を取得する補助スクリプト."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PKCE_PATH = ROOT / ".salesforce_pkce"
SCOPES = "api refresh_token offline_access"


def _oauth_base_url(domain: str) -> str:
    if domain == "test":
        return "https://test.salesforce.com"
    return "https://login.salesforce.com"


def _resolve_redirect_uri(domain: str) -> str:
    configured = os.environ.get("SF_REDIRECT_URI", "").strip()
    if configured:
        return configured
    if domain == "test":
        return "https://test.salesforce.com/services/oauth2/success"
    return "https://login.salesforce.com/services/oauth2/success"


def _generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def _save_pkce_state(code_verifier: str, redirect_uri: str, base_url: str) -> None:
    PKCE_PATH.write_text(
        json.dumps(
            {
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "base_url": base_url,
            }
        ),
        encoding="utf-8",
    )


def _load_pkce_state() -> dict[str, str] | None:
    if not PKCE_PATH.exists():
        return None
    return json.loads(PKCE_PATH.read_text(encoding="utf-8"))


def _extract_auth_code(raw_input: str) -> str:
    text = raw_input.strip()
    if not text:
        return ""

    if "code=" in text:
        parsed = urllib.parse.urlparse(text)
        query = urllib.parse.parse_qs(parsed.query)
        code_values = query.get("code", [])
        if code_values:
            return code_values[0]

    return text


def _update_env(refresh_token: str, instance_url: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""

    def upsert(content: str, key: str, value: str) -> str:
        pattern = rf"^{re.escape(key)}=.*$"
        line = f"{key}={value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            return re.sub(pattern, line, content, flags=re.MULTILINE)
        return content.rstrip() + "\n" + line + "\n"

    text = upsert(text, "SF_REFRESH_TOKEN", refresh_token)
    text = upsert(text, "SF_INSTANCE_URL", instance_url)
    ENV_PATH.write_text(text, encoding="utf-8")


def _exchange_code(
    auth_code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    base_url: str,
    code_verifier: str,
) -> dict:
    token_response = requests.post(
        f"{base_url}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    if not token_response.ok:
        print(f"トークン取得失敗: {token_response.status_code}")
        print(token_response.text)
        print()
        print(f"使用した redirect_uri: {redirect_uri}")
        print("Connected App の Callback URL と .env の SF_REDIRECT_URI が完全一致しているか確認してください。")
        sys.exit(1)
    return token_response.json()


def main() -> None:
    load_dotenv(ENV_PATH)

    client_id = os.environ.get("SF_CLIENT_ID")
    client_secret = os.environ.get("SF_CLIENT_SECRET")
    domain = os.environ.get("SF_DOMAIN", "login")

    if not client_id or not client_secret:
        print("SF_CLIENT_ID と SF_CLIENT_SECRET を .env に設定してください。")
        sys.exit(1)

    base_url = _oauth_base_url(domain)
    redirect_uri = _resolve_redirect_uri(domain)

    code_verifier, code_challenge = _generate_pkce_pair()
    _save_pkce_state(code_verifier, redirect_uri, base_url)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{base_url}/services/oauth2/authorize?{urllib.parse.urlencode(params)}"

    print("OAuth2 初回認可（PKCE 対応・1回だけ）")
    print(f"redirect_uri: {redirect_uri}")
    print("1. ブラウザで Salesforce にログインし、Connected App を許可")
    print("2. リダイレクト先 URL 全体、または code= の値をコピー")
    print()
    print(auth_url)
    print()

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    auth_code = _extract_auth_code(input("Authorization Code or Callback URL: "))
    if not auth_code:
        print("Authorization Code が空です。")
        sys.exit(1)

    payload = _exchange_code(
        auth_code=auth_code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        base_url=base_url,
        code_verifier=code_verifier,
    )

    refresh_token = payload.get("refresh_token")
    instance_url = payload.get("instance_url")

    if not refresh_token or not instance_url:
        print("refresh_token または instance_url が返ってきませんでした。")
        print(payload)
        sys.exit(1)

    _update_env(refresh_token, instance_url)
    if PKCE_PATH.exists():
        PKCE_PATH.unlink()

    print()
    print("OAuth2 設定を .env に保存しました。")
    print("接続確認: python scripts/test_salesforce_connection.py")


if __name__ == "__main__":
    main()
