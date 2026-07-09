# drive-check

TeamSpirit（勤怠）の CSV と Google Workspace 監査ログを照合し、**勤務時間外の Google 操作**を検出するツールです。

人事・労務向けの「要確認リスト」作成を目的としています。法的な未払残業の認定を自動で行うものではありません。

---

## できること

- TeamSpirit からエクスポートした勤怠 CSV を読み込む
- Google Workspace Admin Reports API から監査ログを取得する
- 出退勤時間（±猶予）と承認済み残業申請の範囲外にある操作を **時間外イベント** として抽出する
- 社員 × 日次のサマリー CSV を出力する

---

## 処理の流れ

```
TeamSpirit 勤怠 CSV ──┐
TeamSpirit 社員 CSV ──┼──► 許容時間帯の計算 ──► 時間外判定 ──► output/*.csv
残業申請 CSV（任意） ──┘         ▲
                                 │
Google 監査ログ ──► 除外フィルタ ──┘
                    (GAS・受動ログ等)
```

---

## 必要なもの

| 項目 | 内容 |
|------|------|
| Python | 3.11 以上推奨 |
| Google Workspace | 管理者権限（監査ログ閲覧） |
| TeamSpirit | 勤怠・社員マスタの CSV エクスポート |
| GCP | サービスアカウント + Admin SDK API 有効化 |

---

## セットアップ

### 1. 依存関係のインストール

```bash
cd drive-check
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 設定ファイル

```bash
cp config.example.yaml config.yaml
```

`config.yaml` で CSV ファイル名・列マッピング・照合パラメータを編集します。

### 3. 環境変数（Google 認証）

```bash
cp .env.example .env
```

`.env` に以下を設定します。

```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials/service-account.json
GOOGLE_ADMIN_EMAIL=admin@your-domain.com
```

#### Google 側の準備（初回のみ）

1. **Google Cloud Console** でプロジェクトを作成
2. **Admin SDK API** を有効化
3. **サービスアカウント** を作成し、JSON キーを `credentials/` に保存
4. **Google 管理コンソール** → セキュリティ → API コントロール → ドメイン全体の委任

| 項目 | 値 |
|------|-----|
| クライアント ID | サービスアカウントの Client ID |
| OAuth スコープ | `https://www.googleapis.com/auth/admin.reports.audit.readonly` |

接続確認:

```bash
python scripts/test_google_connection.py
```

---

## 入力ファイル（`input/`）

TeamSpirit（Salesforce）のレポートから CSV をエクスポートし、`input/` に配置します。

### Salesforce レポート（ダウンロード元）

| 用途 | レポート | 配置先（例） |
|------|----------|--------------|
| 社員マスタ（ユーザー一覧） | [ユーザー一覧](https://teamspirit-7025.lightning.force.com/lightning/r/Report/00OIU00000AwfQw2AJ/view?queryScope=userFolders) | `input/report1783402017703.csv` |
| 打刻情報（勤怠日次） | [打刻情報](https://teamspirit-7025.lightning.force.com/lightning/r/Report/00OfQ00000ADcpiUAD/view?queryScope=userFolders) | `input/report1783401008096.csv` |

**エクスポート手順（Salesforce）**

1. 上記リンクからレポートを開く
2. 右上 **▼** → **エクスポート**
3. **詳細表示形式: 結合** / **形式: CSV** を選択してダウンロード
4. `input/` に配置し、`config.yaml` のファイル名と一致させる

| ファイル | 必須 | 内容 |
|----------|------|------|
| 勤怠 CSV（打刻情報） | ✅ | 日次の出社・退社 |
| 社員マスタ CSV（ユーザー一覧） | ✅ | 社員コード → メールの紐付け |
| 残業申請 CSV（`overtime.csv`） | 任意 | 承認済み残業の時間帯（フレックス制など残業申請がない場合は不要） |

`config.yaml` の `input.attendance_file` / `employee_mapping_file` でファイル名を指定します。

### 勤怠 CSV の主な列

- `社員コード` / `社員名`
- `日付`
- `出社時刻(HH:MM)` / `退社時刻(HH:MM)`

### 社員マスタ CSV の主な列

- `社員コード` / `社員名`
- `ユーザ: メール`

**注意:** Google 監査ログのメールアドレスと一致する必要があります。別ドメイン（例: `@studiomoon6.com`）の社員は突合できません。

---

## 使い方

### 基本（先月分・全員）

```bash
source .venv/bin/activate
python main.py
```

### 期間を指定

```bash
python main.py --start-date 2026-06-01 --end-date 2026-06-30
```

### 特定の社員だけ（推奨: 試行時）

```bash
python main.py --start-date 2026-06-01 --end-date 2026-06-30 \
  --email user@link-u.co.jp
```

### CLI オプション

| オプション | 説明 |
|-----------|------|
| `--config` | 設定ファイル（default: `config.yaml`） |
| `--start-date` | 照合開始日 `YYYY-MM-DD` |
| `--end-date` | 照合終了日 `YYYY-MM-DD` |
| `--email` | 対象メール（複数指定可）。未指定時は全員 |
| `--audit-cache` | 保存済み監査ログ（JSONL）を読み込み、API 取得をスキップ |
| `--save-audit-cache` | API 取得結果を JSONL に保存（デバッグ用） |

### 監査ログのキャッシュ（デバッグ向け）

**現状:** 通常実行では毎回 Google API から監査ログを取得します（ここが最も時間がかかります）。

除外ルール・自動更新検出・勤怠 CSV を変えただけなら、**監査ログの再取得は不要**です。一度取得した生ログをファイルに保存して使い回せます。

```bash
# 1. 初回のみ API 取得 + キャッシュ保存
python main.py --start-date 2026-06-01 --end-date 2026-06-30 \
  --email ryuunoshin.tsunematsu@link-u.group \
  --save-audit-cache cache/audit_2026-06_tsunematsu.jsonl

# 2. 以降はキャッシュから照合（数秒〜数十秒）
python main.py --start-date 2026-06-01 --end-date 2026-06-30 \
  --email ryuunoshin.tsunematsu@link-u.group \
  --audit-cache cache/audit_2026-06_tsunematsu.jsonl
```

| 変更内容 | キャッシュ使い回し |
|----------|-------------------|
| `config.yaml` の除外ルール・検出パラメータ | ✅ 可 |
| 勤怠 CSV | ✅ 可（同じ期間なら） |
| 照合期間・対象メール | ❌ 別キャッシュが必要 |
| Google 側の新しい操作を反映 | ❌ API 再取得が必要 |

キャッシュは API 取得直後の **生ログ** です。`*_events.csv`（時間外イベントのみ）とは別物なので、デバッグには `--save-audit-cache` の JSONL を使ってください。

---

## 出力（`output/`）

実行ごとにタイムスタンプ付き CSV が生成されます。

| ファイル | 内容 |
|----------|------|
| `*_events.csv` | 時間外 Google 操作の一覧（1操作 = 1行） |
| `*_summary.csv` | 社員 × 日次のサマリー |

### events.csv の列

| 列 | 意味 |
|----|------|
| `email` | 操作者メール（監査ログの actor） |
| `work_date` | 照合対象日（イベント時刻の JST 日付） |
| `timestamp` | 操作日時（JST、`+09:00`） |
| `application_name` | Google アプリ名（例: `drive`, `gmail`, `login`） |
| `event_name` | イベント種別（例: `edit`, `send`, `delivery`） |
| `ip_address` | IP アドレス（ログに含まれる場合） |
| `detail` | イベントパラメータ（`doc_title`, `script_id` 等を `;` 連結） |

### summary.csv の主な列

| 列 | 意味 |
|----|------|
| `employee_name` | 社員名（社員マスタ CSV から取得） |
| `email` | メールアドレス |
| `attendance_start` / `attendance_end` | 出社・退社時刻 |
| `outside_event_count` | 時間外イベント件数 |
| `estimated_outside_minutes` | 推定の時間外操作時間（分） |
| `suspicion_level` | `問題なし` / `要確認（低・中・高）` |

---

## 照合ロジック

### 許容時間帯（その日の「OK ゾーン」）

1. **勤怠の出退勤 ± 猶予**（default: 前後 15 分）
2. **承認済み残業申請**（`overtime.csv` がある場合。フレックス制で残業申請がない場合は打刻のみで判定）

上記をマージした時間帯内の Google 操作は **問題なし**、範囲外は **時間外イベント** です。

### 除外イベント（照合対象外）

次のログは **本人の能動操作とは限らない** ため、default では照合から除外します。

| 除外条件 | 理由 |
|----------|------|
| `detail` に `script_id=` を含む | GAS（Google Apps Script）の自動実行 |
| `detail` に `api_method=` を含む | Sheets / Drive API 経由の操作 |
| `detail` に `originating_app_id=` を含む | アドオン・連携アプリ経由の操作 |
| `drive` / `access_url` | 外部 URL へのアクセス（GAS の UrlFetch 等） |
| `drive` / `sync_item_content` | Drive のオフライン同期（本人の能動操作ではない） |
| `gmail` / `delivery` | 受信メールの自動配信ログ |
| `token` / `authorize` | アプリ認証（ESET 等） |
| `mobile` / `DEVICE_SYNC_EVENT` 等 | 端末の自動同期 |
| **自動更新シート検出** | GAS 定期更新など（操作パターンから自動判定） |
| `doc_title_substrings`（任意） | 自動検出で拾えない特定シート名 |

`config.yaml` の `matching.exclude_events` で変更できます。

---

## 監査ログの取得・照合仕様

### 照合に使う TeamSpirit 側のデータ

| データ | 使い方 |
|--------|--------|
| 打刻 CSV の出社・退社時刻 | 許容時間帯の中心（±猶予 15 分） |
| 社員マスタ CSV | 社員コード → Google メールの解決、`summary.csv` の社員名 |
| 残業申請 CSV（任意） | 許容時間帯の追加（フレックス制など申請運用がない場合は未使用で可） |

出退勤のない日（休日・有休など）は `missing_attendance_policy: skip` により照合しません。

### Google 監査ログの取得範囲

Admin SDK Reports API（`activities.list`）から、指定期間・指定ユーザーのログを取得します。

- **アプリ（`application_name`）**: default は `all`（下表の全アプリ）
- **イベント種別（`event_name`）**: **取得時点ではフィルタしない**（API が返すものをすべて取得）
- **ユーザ**: `--email` 未指定時は全員、`--email` 指定時はそのメールのみ

`application_names: all` で取得するアプリ一覧:

| application_name | 主な内容（例） |
|------------------|----------------|
| `drive` | ファイル閲覧・編集・アップロード、GAS 実行（`script_id` 付き） |
| `gmail` | メール送信（`send`）、受信（`delivery`）等 |
| `login` | ログイン成功・検証 |
| `calendar` | 予定の作成・変更 |
| `meet` | Meet 関連 |
| `chat` | Chat の閲覧・投稿 |
| `token` | 外部アプリへの OAuth 認可・失効 |
| `admin` | 管理操作 |
| `mobile` | モバイル端末同期 |
| `chrome` | Chrome 関連 |
| その他 | `access_transparency`, `cloud_search`, `gcp`, `groups`, `keep`, `rules`, `saml`, `user_accounts` 等 |

`google.application_names` を `[drive, gmail, login]` のようにリスト指定すると、取得するアプリだけを絞れます（実行時間短縮向け）。イベント種別のフィルタはここでは行いません。

1 件の監査ログから、出力用に次の項目を保持します。

| 内部項目 | 説明 |
|----------|------|
| `email` | 操作者 |
| `timestamp` | 操作日時（UTC で取得 → 照合時に JST 変換） |
| `application_name` | アプリ名 |
| `event_name` | イベント種別 |
| `ip_address` | IP（あれば） |
| `detail` | パラメータ文字列（`doc_title=...`, `script_id=...` 等） |

### 照合の流れ（3段階）

```
① API 取得     … 指定期間の全イベント（イベント種別は絞らない）
      ↓
② 除外フィルタ … 固定ルール除外 + 自動更新シート検出（下表）
      ↓
③ 時間外判定   … 残ったイベントの時刻が、出退勤 ± 猶予の外なら時間外
```

**重要:** 「取得するログ」と「時間外としてカウントするログ」は同じではありません。② の除外を通過したものだけが ③ の比較対象になります。

### 除外されるイベント（default）

| 条件 | 例 | 理由 |
|------|-----|------|
| `detail` に `script_id=` | `drive/access_url`（GAS トリガー） | GAS 自動実行 |
| `detail` に `api_method=` | `drive/access_item_content` + Sheets API | API 経由の読み取り |
| `detail` に `originating_app_id=` | スプレッドシートアドオン経由 | 連携アプリ経由 |
| `drive` + `access_url` | 外部 URL アクセス | UrlFetch 等 |
| `drive` + `sync_item_content` | Drive オフライン同期 | 自動同期 |
| `gmail` + `delivery` | 受信メール | 受動的ログ |
| `token` + `authorize` | ESET 等の認可 | アプリ認証 |
| `mobile` + `DEVICE_SYNC_EVENT` 等 | 端末同期 | 本人操作ではない |
| **自動更新シート検出** | 同一ファイルへの定期操作 | GAS 時間主導トリガー等（後述） |

#### 自動更新シート検出（人ごとの設定不要）

GAS や連携処理は **`script_id` や `api_method` なし** で記録されることがあります。シート名を config に書く代わりに、**同一ファイル（`doc_id`）への操作パターン** から自動検出します（`drive` イベント全般。`edit` だけでなく `download` も含む）。

| パターン | 例 | 検出条件（概要） |
|----------|-----|------------------|
| 高頻度連続 | 株価シート（3分おき） | 1日20回以上・8時間以上に分散・間隔中央値≤15分 |
| 定期バースト | 工数未入力アラート（0/4/8/20時） | 1日平均3回以上・同じ時間帯が複数日・バースト内間隔≤60分 |
| ペア重複 | ESET シート DL（2件同時ログ） | 5日以上・1日平均2回以上・間隔中央値≤1分 |
| 固定時刻 | News用（毎朝8時） | 10日以上・同じ時刻帯が70%以上の日 |
| 低頻度・散発 | LUG-お問い合わせ（n8n 外部 cron） | 10日以上・1〜4回/日・4時間以上に分散・特定時刻に偏らない |

```yaml
matching:
  detect_automated_edits:
    enabled: true
    min_edits_per_day: 20          # 高頻度連続
    min_distinct_hours: 8
    max_median_gap_minutes: 15
    min_automated_days: 3
    min_avg_events_per_day: 3      # 定期バースト
    min_recurring_hours: 3
    recurring_hour_day_ratio: 0.5
    max_burst_median_gap_minutes: 60
    min_paired_days: 5             # ペア重複
    min_paired_avg_per_day: 2
    max_paired_median_gap_minutes: 1.0
    min_fixed_schedule_days: 10    # 固定時刻
    min_fixed_schedule_avg_per_day: 1.0
    fixed_hour_day_ratio: 0.7
    min_sparse_active_days: 10      # 低頻度・散発（n8n / 外部 cron）
    min_sparse_avg_per_day: 1.0
    max_sparse_avg_per_day: 4.0
    min_sparse_distinct_hours: 4
    sparse_max_dominant_hour_day_ratio: 0.6
```

#### 手動でのシート名除外（任意）

自動検出で拾えないケース向けに、`doc_title_substrings` も引き続き使えます。

```yaml
exclude_events:
  doc_title_substrings:
    - 特定のシート名
```

### 照合対象となるイベント（除外されないもの）

除外ルールに該当しないイベントは、**勤務時間外であればすべて時間外としてカウント**します。例:

| application_name | event_name | 意味（例） | 照合 |
|------------------|------------|------------|------|
| `drive` | `edit`, `view`, `access_item_content`, `upload` 等 | ファイル操作 | ✅ 対象 |
| `gmail` | `send` | **メール送信** | ✅ 対象 |
| `gmail` | `delivery` | 受信 | ❌ default で除外 |
| `login` | `login_success` 等 | ログイン | ✅ 対象 |
| `calendar` | `change_event` 等 | 予定変更 | ✅ 対象 |
| `chat` | `message_posted` 等 | Chat 操作 | ✅ 対象 |
| `token` | `authorize` | アプリ認可 | ❌ default で除外 |
| `token` | `revoke` | 認可失効 | ✅ 対象（除外リストに無いため） |

#### gmail / メール送信について

Google 監査ログのイベント名は **`mail_send` ではなく `send`** です（`application_name=gmail`, `event_name=send`）。

- **取得**: `application_names: all` なら `send` も API から取得します
- **照合**: `send` は default の除外対象ではないため、**勤務時間外の送信は時間外イベントとしてカウント**されます
- **除外**: 受信の `delivery` のみ default で除外（`send` は除外しない）

※ 時間外イベント CSV に `gmail/send` が無い日は、その時間帯に送信操作が無かった（または許容時間内だった）ことを意味します。恒松さんの 6 月分では時間外 CSV に出ていた gmail は `delivery` のみでした。

### 判定式（イメージ）

```
時間外イベント =
  Google操作時刻（JST）
  ∉ (出退勤 ± 猶予 ∪ 承認済み残業)
```

### 疑いレベル

| 条件 | レベル |
|------|--------|
| 時間外 0 件 | 問題なし |
| 推定 30 分以上 または 5 件以上 | 要確認（中） |
| 推定 60 分以上 または 20 件以上 | 要確認（高） |
| それ以外 | 要確認（低） |

### config.yaml で変更可能なパラメータ

```yaml
matching:
  timezone: Asia/Tokyo
  grace_minutes_before: 15   # 出社前猶予（分）
  grace_minutes_after: 15    # 退社後猶予（分）
  session_gap_minutes: 30      # セッション区切り（分）
  missing_attendance_policy: skip  # 勤怠なし日は照合しない
  exclude_events:
    detail_substrings:
      - script_id=           # GAS 自動実行
      - api_method=          # Sheets / Drive API
      - originating_app_id=  # アドオン・連携アプリ
    application_events:
      - application_name: gmail
        event_name: delivery
      - application_name: token
        event_name: authorize
      - application_name: drive
        event_name: access_url
      - application_name: drive
        event_name: sync_item_content
      - application_name: mobile
        event_name: DEVICE_SYNC_EVENT
    doc_title_substrings: []  # 任意: 自動検出で拾えないシート名
  detect_automated_edits:
    enabled: true
    min_edits_per_day: 20
    min_distinct_hours: 8
    max_median_gap_minutes: 15
    min_automated_days: 3
    min_avg_events_per_day: 3
    min_recurring_hours: 3
    recurring_hour_day_ratio: 0.5
    max_burst_median_gap_minutes: 60
    min_paired_days: 5
    min_paired_avg_per_day: 2
    max_paired_median_gap_minutes: 1.0
    min_fixed_schedule_days: 10
    min_fixed_schedule_avg_per_day: 1.0
    fixed_hour_day_ratio: 0.7
    min_sparse_active_days: 10      # 低頻度・散発（n8n / 外部 cron）
    min_sparse_avg_per_day: 1.0
    max_sparse_avg_per_day: 4.0
    min_sparse_distinct_hours: 4
    sparse_max_dominant_hour_day_ratio: 0.6
```

除外ルールの追加・無効化もこの `exclude_events` で行います（空にすれば除外なし）。

---

## 実行時間の目安

| パターン | 目安 |
|----------|------|
| 1 人・1 ヶ月 | 1〜3 分 |
| 全員・1 ヶ月・全アプリ | 30 分〜数時間 |

ボトルネックは Google 監査ログの API 取得です。初回や全社実行時は `--email` で 1 人ずつ試すか、`application_names` を絞ることを推奨します。

---

## プロジェクト構成

```
drive-check/
├── main.py                 # メイン実行
├── config.yaml             # 設定（gitignore）
├── config.example.yaml     # 設定テンプレート
├── .env                    # 認証情報（gitignore）
├── requirements.txt
├── input/                  # TeamSpirit CSV（gitignore: *.csv）
├── output/                 # 結果 CSV
├── cache/                  # 監査ログキャッシュ（gitignore、デバッグ用）
├── credentials/            # サービスアカウント JSON（gitignore）
├── scripts/
│   ├── test_google_connection.py
│   ├── get_salesforce_token.py   # Salesforce OAuth（現行フローでは未使用）
│   └── test_salesforce_connection.py
└── src/
    ├── csv_loader.py       # TeamSpirit CSV 読込
    ├── event_filter.py     # 監査ログ除外フィルタ
    ├── audit_cache.py      # 監査ログキャッシュ読込/保存
    ├── automated_detector.py  # 自動更新シート検出
    ├── google_audit_client.py
    ├── matcher.py          # 照合ロジック
    └── report.py           # CSV 出力
```

---

## 注意事項

- **未払残業の自動判定ではない** … あくまで Google 操作と勤怠の突合結果です
- **残業申請 CSV がない場合** … フレックス制などでは打刻 ± 猶予のみで判定（休日出勤は打刻に反映される想定）
- **監査ログの保持** … Admin コンソールは通常約 6 ヶ月。それ以前は Vault / BigQuery 等が必要
- **就業規則・プライバシー** … ログ利用範囲は社内規程に従ってください
- **秘密情報** … `.env` / `credentials/` / `input/*.csv` は Git にコミットしないでください

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `GOOGLE_APPLICATION_CREDENTIALS が未設定` | `.env` のパスを確認 |
| `403 Not Authorized` | ドメイン全体の委任・スコープを確認 |
| 勤怠 0 件 | CSV ファイル名・期間・列名（`config.yaml`）を確認 |
| メール未解決の警告 | 社員マスタ CSV に該当社員がいるか確認 |
| 実行が終わらない | `--email` で絞る、`application_names` を絞る、期間を短くする |

---

## ライセンス

社内利用を想定。必要に応じて追記してください。
