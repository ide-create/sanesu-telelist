#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Sheets 書き込みモジュール
"""

import logging
import time
from typing import List, Set, Dict

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# スプレッドシートの列定義
COLUMNS = ["企業名", "所在地", "電話番号", "求人サイト", "取得日"]


def _connect(spreadsheet_id: str, sheet_name: str, credentials_file: str) -> gspread.Worksheet:
    """スプレッドシートワークシートへ接続"""
    creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(spreadsheet_id).worksheet(sheet_name)


def get_existing_companies(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
) -> Set[str]:
    """
    既存の企業名セットを取得する。
    シートが空の場合はヘッダーを書き込む。
    """
    try:
        sheet = _connect(spreadsheet_id, sheet_name, credentials_file)
        all_values = sheet.get_all_values()

        if not all_values:
            logger.info("シートが空です。ヘッダーを書き込みます。")
            sheet.append_row(COLUMNS, value_input_option="USER_ENTERED")
            return set()

        # 1行目がヘッダーかどうか確認
        header = all_values[0]
        if header == COLUMNS:
            data_rows = all_values[1:]
        else:
            # ヘッダーなしのケース（0列目を企業名として扱う）
            data_rows = all_values

        companies = {row[0].strip() for row in data_rows if row and row[0].strip()}
        logger.info(f"既存企業数: {len(companies)} 件")
        return companies

    except Exception as e:
        logger.error(f"既存データ取得エラー: {e}")
        return set()


def append_records(
    records: List[Dict],
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
    existing_companies: Set[str],
) -> int:
    """
    新規レコードをスプレッドシートに追記する。
    企業名で重複チェックを行い、新規のみ追加。

    Returns:
        追記した件数
    """
    try:
        sheet = _connect(spreadsheet_id, sheet_name, credentials_file)
        added = 0

        for record in records:
            company = record.get("企業名", "").strip()
            if not company or company in existing_companies:
                continue

            row = [
                record.get("企業名", ""),
                record.get("所在地", ""),
                record.get("電話番号", ""),
                record.get("求人サイト", ""),
                record.get("取得日", ""),
            ]

            try:
                sheet.append_row(row, value_input_option="USER_ENTERED")
                existing_companies.add(company)
                added += 1
                logger.info(f"  追記: {company}")

                # Sheets API レート制限対策 (100req/100sec)
                if added % 20 == 0:
                    time.sleep(2)
                else:
                    time.sleep(0.3)

            except gspread.exceptions.APIError as api_err:
                logger.warning(f"API エラー ({company}): {api_err} — スキップ")
                time.sleep(5)

        logger.info(f"追記完了: {added} 件")
        return added

    except Exception as e:
        logger.error(f"スプレッドシート書き込みエラー: {e}")
        return 0
