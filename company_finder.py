#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企業名特定・電話番号取得モジュール

求人票に記載されている会社名は派遣会社であることが多いため、
勤務地・業務内容・最寄り駅・勤務時間などから実際の企業を推測する。
"""

import re
import time
import logging
import random
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─── 定数定義 ────────────────────────────────────────────────────────

# 会社名を示す正規表現パターン（優先度順）
COMPANY_PATTERNS = [
    # 前置きパターン（株式会社○○）
    r'株式会社[\s　]*([^\s\n　、。（「』\d【】]{2,20})',
    r'有限会社[\s　]*([^\s\n　、。（「』\d【】]{2,20})',
    r'合同会社[\s　]*([^\s\n　、。（「』\d【】]{2,20})',
    # 後置きパターン（○○株式会社）
    r'([^\s\n　、。（「』\d【】]{2,20})[\s　]*(株式会社|有限会社|合同会社)',
    # 業種サフィックス
    r'([^\s\n　、。（「』\d【】]{2,15})(製作所|工業所|工業|精工|精機|精密|技研|テクノ|産業)',
    r'([^\s\n　、。（「』\d【】]{2,15})(フーズ|フード|食品|乳業|製菓)',
    r'([^\s\n　、。（「』\d【】]{2,15})(物流|ロジスティクス|倉庫)',
]

# 派遣・請負会社を示すキーワード
STAFFING_KEYWORDS = [
    "派遣", "人材派遣", "アウトソーシング", "請負", "業務委託",
    "スタッフィング", "テンプスタッフ", "スタッフサービス",
    "パソナ", "アデコ", "マンパワー", "ランスタッド",
    "リクルートスタッフィング", "リクルートR&Dスタッフィング",
    "日総工産", "日研トータルソーシング", "日研", "ウィルオブ",
    "UTグループ", "UT", "メイテック", "フルキャスト",
    "エン・ジャパン", "エンジャパン", "夢真", "綜合キャリアオプション",
    "コウジョブ", "ヒューマンリソシア", "キャリアリンク",
    "アビリティーセンター", "クリエイトスタッフ", "東和エンジニアリング",
    "セントスタッフ", "アルプス技研", "ネオキャリア",
    "ヒューマンアイズ", "クイック", "トランスコスモス",
    "グロップ", "タスクフォース", "テクノプロ", "ミライスタイル",
    "ジェイック", "キャリアデザインセンター", "ディップ",
    "リビングキャリア", "ライクスタッフィング",
]

# 除外する大手企業
EXCLUDED_LARGE_COMPANIES = [
    "トヨタ", "Toyota", "TOYOTA", "デンソー", "DENSO",
    "アイシン", "ブリヂストン", "花王",
    "本田技研工業", "ホンダ", "スズキ", "ヤマハ発動機", "ヤマハ",
    "三菱電機", "三菱重工", "住友電気工業", "住友理工",
    "川崎重工業", "パナソニック", "ソニー", "日立製作所",
    "東芝", "富士通", "NEC", "シャープ", "京セラ",
    "コカ・コーラ", "コカコーラ", "サントリー", "キリン", "アサヒ",
    "味の素", "キッコーマン", "明治", "森永", "グリコ", "カゴメ",
    "ヤマト運輸", "佐川急便", "日本郵便", "Amazon", "アマゾン",
    "日産自動車", "マツダ", "ダイハツ", "いすゞ",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# iタウンページ 都道府県コード
PREF_CODES = {
    "愛知県": "23",
    "三重県": "24",
    "静岡県": "22",
    "岐阜県": "21",
}

# ─── ユーティリティ関数 ──────────────────────────────────────────────

def _is_staffing(name: str) -> bool:
    """派遣・請負会社かどうか判定"""
    return any(kw in name for kw in STAFFING_KEYWORDS)


def _is_excluded(name: str) -> bool:
    """除外対象の大手企業かどうか判定"""
    return any(ex in name for ex in EXCLUDED_LARGE_COMPANIES)


def _clean_company_name(raw: str) -> str:
    """抽出した会社名の前後の不要文字を除去"""
    name = raw.strip()
    # 末尾に残る助詞・記号を除去
    name = re.sub(r'[のでにをはがも、。\s　]+$', '', name)
    # 先頭に残る記号を除去
    name = re.sub(r'^[・\-\s　]+', '', name)
    return name


def _extract_company_names(text: str) -> List[str]:
    """テキストから会社名候補を抽出"""
    found = []
    seen = set()

    for pattern in COMPANY_PATTERNS:
        for m in re.finditer(pattern, text):
            # グループがある場合は結合してフルの会社名を作る
            full = m.group(0)
            name = _clean_company_name(full)
            if (
                name
                and len(name) >= 3
                and name not in seen
                and not _is_staffing(name)
                and not _is_excluded(name)
            ):
                seen.add(name)
                found.append(name)

    return found


# ─── オンライン検索（DuckDuckGo HTML版） ────────────────────────────

def _search_company_online(location: str, station: str, description_snippet: str) -> List[str]:
    """
    勤務地・最寄り駅などをもとにDuckDuckGoで企業候補を検索する。
    API不要・無料で利用可能。
    """
    try:
        query_parts = [p for p in [location, station, "工場 製造 企業"] if p]
        query = " ".join(query_parts)
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}&kl=jp-jp"

        time.sleep(random.uniform(2.0, 4.0))
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        candidates = []
        seen = set()

        for result in soup.select(".result__body")[:8]:
            text = result.get_text(" ", strip=True)
            for name in _extract_company_names(text):
                if name not in seen:
                    seen.add(name)
                    candidates.append(name)

        return candidates[:5]

    except Exception as e:
        logger.debug(f"オンライン検索エラー: {e}")
        return []


# ─── 電話番号取得（iタウンページ） ──────────────────────────────────

def lookup_phone(company_name: str, prefecture: str) -> str:
    """
    iタウンページで企業の電話番号を検索する。
    見つからない場合は空文字を返す。
    """
    try:
        pref_code = PREF_CODES.get(prefecture, "")
        # 法人格を除いた短縮名で検索
        short_name = re.sub(
            r'(株式会社|有限会社|合同会社|合資会社|合名会社)', '', company_name
        ).strip()
        short_name = re.sub(r'[\s　]+', ' ', short_name)

        if not short_name:
            return ""

        url = (
            "https://itp.ne.jp/service/tel/search/"
            f"?searchKey={requests.utils.quote(short_name)}"
            f"&prefCode={pref_code}"
        )

        time.sleep(random.uniform(1.0, 2.5))
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        # iタウンページの電話番号要素
        for selector in [".telNum", ".tel", "[itemprop='telephone']", ".number"]:
            elem = soup.select_one(selector)
            if elem:
                phone = re.search(r'0\d{1,4}[-\u2212\s]\d{1,4}[-\u2212\s]\d{3,4}', elem.get_text())
                if phone:
                    return phone.group(0).replace('\u2212', '-').replace(' ', '-')

        # フォールバック: ページ全体から電話番号パターンを抽出
        all_text = soup.get_text()
        phones = re.findall(r'0\d{1,4}[-\s]\d{1,4}[-\s]\d{3,4}', all_text)
        if phones:
            return phones[0].replace(' ', '-')

        return ""

    except Exception as e:
        logger.debug(f"電話番号取得エラー ({company_name}): {e}")
        return ""


# ─── メイン: 企業特定 ────────────────────────────────────────────────

def identify_company(
    posted_company: str,
    description: str,
    location: str,
    station: str,
    work_hours: str,
    prefecture: str,
) -> Tuple[str, str]:
    """
    求人情報から実際の企業名と電話番号を推定する。

    ロジック:
      1. 求人票の会社名が派遣会社でなければそのまま採用
      2. 説明文から会社名パターンを抽出
         - 1件 → 確定
         - 複数 → 候補として列挙
      3. オンライン検索で候補を補完
      4. 特定不能 → 「不明（地名付近の工場）」

    Returns:
        (企業名または候補文字列, 電話番号または空文字)
    """
    combined_text = f"{posted_company}\n{description}\n{location}\n{station}\n{work_hours}"

    # ─ Step 1: 求人票の会社名が有効な場合
    if posted_company and not _is_staffing(posted_company) and not _is_excluded(posted_company):
        # 会社名らしい文字列かチェック（法人格 or 業種サフィックスを含む）
        has_legal = any(s in posted_company for s in [
            "株式会社", "有限会社", "合同会社",
            "製作所", "工業", "精工", "テクノ", "産業", "食品",
        ])
        if has_legal and len(posted_company) >= 4:
            phone = lookup_phone(posted_company, prefecture)
            logger.debug(f"  → 求人票会社名採用: {posted_company}")
            return posted_company, phone

    # ─ Step 2: 説明文から会社名を抽出
    candidates = _extract_company_names(combined_text)

    if len(candidates) == 1:
        phone = lookup_phone(candidates[0], prefecture)
        logger.debug(f"  → 説明文から特定: {candidates[0]}")
        return candidates[0], phone

    if len(candidates) >= 2:
        # 最大4候補まで
        shown = candidates[:4]
        candidates_str = "／".join(shown) + "の可能性"
        phone = lookup_phone(shown[0], prefecture)
        logger.debug(f"  → 複数候補: {candidates_str}")
        return candidates_str, phone

    # ─ Step 3: オンライン検索
    online = _search_company_online(location, station, description[:100])

    if len(online) == 1:
        phone = lookup_phone(online[0], prefecture)
        logger.debug(f"  → オンライン検索で特定: {online[0]}")
        return online[0], phone

    if len(online) >= 2:
        shown = online[:4]
        candidates_str = "／".join(shown) + "の可能性"
        phone = lookup_phone(shown[0], prefecture)
        logger.debug(f"  → オンライン複数候補: {candidates_str}")
        return candidates_str, phone

    # ─ Step 4: 特定不能
    loc_hint = re.sub(r'[都道府県市区町村].*', '', location)[:8] if location else "不明地域"
    fallback = f"不明（{loc_hint}付近の工場）"
    logger.debug(f"  → 特定不能: {fallback}")
    return fallback, ""
