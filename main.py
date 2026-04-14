#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
製造工場・物流倉庫 求人収集スクリプト
========================================
対象エリア  : 愛知県・三重県・静岡県・岐阜県
対象業種    : 製造工場（自動車部品・食品等）・物流倉庫
スプレッドシート: 14eskhSvD7hh_x-jRmfH_c97B5QrU0JJ0Dz_B1TXbw_c
シート名    : テレアポリスト

実行方法:
  python main.py

  初回は playwright install chromium を先に実行してください。
"""

import logging
import os
import sys
import json
from datetime import date
from typing import List, Dict, Set

from playwright.sync_api import sync_playwright

from scrapers import run_all_scrapers
from company_finder import identify_company
from sheets_writer import get_existing_companies, append_records

# ─── 設定 ────────────────────────────────────────────────────────────

SPREADSHEET_ID = "14eskhSvD7hh_x-jRmfH_c97B5QrU0JJ0Dz_B1TXbw_c"
SHEET_NAME = "テレアポリスト"
CREDENTIALS_FILE = os.environ.get("CREDENTIALS_FILE", "credentials.json")

# 初回実行の最低収集件数（スプレッドシートに既存データがない場合）
MIN_RECORDS = 300

TODAY = date.today().isoformat()

# ─── ロギング設定 ────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─── 除外大手企業 ────────────────────────────────────────────────────

EXCLUDED_LARGE_COMPANIES = {
    "トヨタ", "Toyota", "TOYOTA", "デンソー", "DENSO",
    "アイシン", "ブリヂストン", "花王",
    "本田技研工業", "ホンダ", "スズキ", "ヤマハ発動機",
    "三菱電機", "三菱重工", "住友電気工業",
    "川崎重工業", "パナソニック", "ソニー", "日立製作所",
    "東芝", "富士通", "NEC", "シャープ", "京セラ",
    "コカ・コーラ", "サントリー", "キリン", "アサヒ",
    "味の素", "キッコーマン", "明治", "森永", "グリコ", "カゴメ",
    "ヤマト運輸", "佐川急便", "日本郵便", "Amazon", "アマゾン",
    "日産自動車", "マツダ", "ダイハツ", "いすゞ",
}


def _is_excluded_large(company_name: str) -> bool:
    return any(ex in company_name for ex in EXCLUDED_LARGE_COMPANIES)


# ─── 求人データから企業レコードへ変換 ────────────────────────────────

def process_job(job: Dict) -> Dict:
    """
    1件の求人データを処理して企業レコードに変換する。

    - 実際の企業名を推定 (company_finder.identify_company)
    - 電話番号を取得
    - 大手企業は除外

    Returns:
        {"企業名", "所在地", "電話番号", "求人サイト", "取得日"} または None（除外対象）
    """
    company_name, phone = identify_company(
        posted_company=job.get("posted_company", ""),
        description=job.get("description", ""),
        location=job.get("location", ""),
        station=job.get("station", ""),
        work_hours=job.get("work_hours", ""),
        prefecture=job.get("prefecture", ""),
    )

    # 除外チェック
    if _is_excluded_large(company_name):
        logger.info(f"  除外（大手）: {company_name}")
        return None

    return {
        "企業名": company_name,
        "所在地": job.get("location", ""),
        "電話番号": phone,
        "求人サイト": job.get("source_site", ""),
        "取得日": TODAY,
    }


# ─── 重複除去 ─────────────────────────────────────────────────────────

def deduplicate(records: List[Dict], existing: Set[str]) -> List[Dict]:
    """
    企業名ベースで重複を除去する。
    既存データとの照合 + 今回バッチ内の重複も排除。
    """
    seen: Set[str] = set(existing)
    unique: List[Dict] = []

    for rec in records:
        name = rec.get("企業名", "").strip()
        if not name or name in seen:
            continue
        # 「不明」で始まる場合は場所情報で重複チェック
        if name.startswith("不明"):
            key = f"{name}_{rec.get('所在地', '')}"
        else:
            key = name

        if key not in seen:
            seen.add(key)
            unique.append(rec)

    return unique


# ─── メイン処理 ───────────────────────────────────────────────────────

def main() -> None:
    # 認証ファイルの確認
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error(
            f"認証ファイルが見つかりません: {CREDENTIALS_FILE}\n"
            "Google Cloud Console でサービスアカウントを作成し、"
            "JSONキーを credentials.json として保存してください。"
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("求人収集スクリプト 開始")
    logger.info(f"対象日付: {TODAY}")
    logger.info("=" * 60)

    # ─ Step 1: スプレッドシートの既存企業名を取得
    logger.info("[Step 1] 既存データ確認...")
    existing_companies = get_existing_companies(SPREADSHEET_ID, SHEET_NAME, CREDENTIALS_FILE)
    logger.info(f"既存企業数: {len(existing_companies)} 件")

    # ─ Step 2: 全サイトをスクレイピング
    logger.info("[Step 2] 求人サイトのスクレイピング開始...")
    all_jobs: List[Dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--lang=ja",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "ja,en-US;q=0.9,en;q=0.8"},
        )
        # ボット検知回避: navigator.webdriver を隠す
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        all_jobs = run_all_scrapers(ctx)

        ctx.close()
        browser.close()

    logger.info(f"[Step 2] スクレイピング完了: 計 {len(all_jobs)} 件の求人を取得")

    if not all_jobs:
        logger.warning("求人が1件も取得できませんでした。終了します。")
        return

    # ─ Step 3: 企業名特定・電話番号取得
    logger.info("[Step 3] 企業特定・電話番号取得中...")
    records: List[Dict] = []

    for i, job in enumerate(all_jobs, 1):
        logger.info(
            f"  処理中 ({i}/{len(all_jobs)}): "
            f"[{job.get('source_site')}] {job.get('title', '')[:30]}"
        )
        rec = process_job(job)
        if rec:
            records.append(rec)

    logger.info(f"[Step 3] 有効レコード: {len(records)} 件")

    # ─ Step 4: 重複除去
    logger.info("[Step 4] 重複チェック...")
    unique_records = deduplicate(records, existing_companies)
    logger.info(f"[Step 4] 新規レコード: {len(unique_records)} 件")

    # 初回実行で300件未達の場合は警告
    if len(existing_companies) == 0 and len(unique_records) < MIN_RECORDS:
        logger.warning(
            f"初回収集件数が目標 {MIN_RECORDS} 件に未達です "
            f"(実際: {len(unique_records)} 件)。"
            "サイト側のページ数上限や構造変化の可能性があります。"
        )

    # ─ Step 5: スプレッドシートへ書き込み
    logger.info("[Step 5] スプレッドシートへ書き込み中...")
    added = append_records(
        unique_records,
        SPREADSHEET_ID,
        SHEET_NAME,
        CREDENTIALS_FILE,
        existing_companies,
    )

    # ─ 完了サマリ
    logger.info("=" * 60)
    logger.info("処理完了")
    logger.info(f"  取得求人総数   : {len(all_jobs)} 件")
    logger.info(f"  有効企業レコード: {len(records)} 件")
    logger.info(f"  重複除去後      : {len(unique_records)} 件")
    logger.info(f"  スプレッドシート追記: {added} 件")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
