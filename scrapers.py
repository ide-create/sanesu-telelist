#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
求人サイト スクレイパー群

対象サイト:
  - Indeed
  - バイトル
  - 求人ボックス
  - はたらこねっと
  - タウンワーク
  - スタンバイ
  - エンゲージ
  - Workin

各スクレイパーは dict のリストを返す。
dict のキー: title, posted_company, description, location, station, work_hours, source_site, source_url, prefecture
"""

import time
import random
import logging
import re
from typing import List, Dict, Any
from urllib.parse import quote_plus, urlencode

from playwright.sync_api import Page, BrowserContext, TimeoutError as PWTimeoutError

logger = logging.getLogger(__name__)

# ─── 定数 ────────────────────────────────────────────────────────────

TARGET_PREFECTURES = ["愛知県", "三重県", "静岡県", "岐阜県"]

# 業種・職種キーワード（各サイトの検索窓に入力）
SEARCH_QUERIES = [
    "製造 工場",
    "自動車部品 製造",
    "食品製造 工場",
    "物流 倉庫",
    "ピッキング 倉庫",
    "製造スタッフ",
]

# バイトル エリアID
BAITORU_AREAS = {
    "愛知県": "aichi",
    "三重県": "mie",
    "静岡県": "shizuoka",
    "岐阜県": "gifu",
}

# はたらこねっと エリアコード
HATARAKKO_AREAS = {
    "愛知県": "23",
    "三重県": "24",
    "静岡県": "22",
    "岐阜県": "21",
}

# Workin 都道府県コード
WORKIN_PREFS = {
    "愛知県": "23",
    "三重県": "24",
    "静岡県": "22",
    "岐阜県": "21",
}

# エンゲージ エリアコード
ENGAGE_AREAS = {
    "愛知県": "23",
    "三重県": "24",
    "静岡県": "22",
    "岐阜県": "21",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ─── ユーティリティ ───────────────────────────────────────────────────

def _sleep(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def _safe_text(page: Page, selector: str, default: str = "") -> str:
    try:
        elem = page.query_selector(selector)
        return elem.inner_text().strip() if elem else default
    except Exception:
        return default


def _safe_attr(page: Page, selector: str, attr: str, default: str = "") -> str:
    try:
        elem = page.query_selector(selector)
        return elem.get_attribute(attr) or default if elem else default
    except Exception:
        return default


def _make_job(
    title: str,
    posted_company: str,
    description: str,
    location: str,
    station: str,
    work_hours: str,
    source_site: str,
    source_url: str,
    prefecture: str,
) -> Dict[str, str]:
    return {
        "title": title.strip(),
        "posted_company": posted_company.strip(),
        "description": description.strip(),
        "location": location.strip(),
        "station": station.strip(),
        "work_hours": work_hours.strip(),
        "source_site": source_site,
        "source_url": source_url,
        "prefecture": prefecture,
    }


# ─── Indeed Japan ─────────────────────────────────────────────────────

def scrape_indeed(ctx: BrowserContext, max_per_pref: int = 60) -> List[Dict]:
    """
    jp.indeed.com から製造・物流系求人を収集する。
    ページネーションで最大 max_per_pref 件/県取得。
    """
    results: List[Dict] = []
    site = "Indeed"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            for query in SEARCH_QUERIES[:3]:  # 代表クエリ3種で検索
                start = 0
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({
                        "q": query,
                        "l": pref,
                        "radius": "50",
                        "start": start,
                        "sort": "date",
                    })
                    url = f"https://jp.indeed.com/jobs?{params}"
                    logger.info(f"[Indeed] {pref} / {query} / page start={start}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[Indeed] タイムアウト: {url}")
                        break

                    # 求人カードを取得
                    cards = page.query_selector_all('[data-jk], .job_seen_beacon, .tapItem')
                    if not cards:
                        logger.info(f"[Indeed] {pref}/{query} 結果なし")
                        break

                    for card in cards:
                        try:
                            title = ""
                            for sel in ["h2.jobTitle span", ".jobTitle a span", "h2 a span"]:
                                t = card.query_selector(sel)
                                if t:
                                    title = t.inner_text().strip()
                                    break

                            company = ""
                            for sel in ['[data-testid="company-name"]', ".companyName", ".company"]:
                                c = card.query_selector(sel)
                                if c:
                                    company = c.inner_text().strip()
                                    break

                            location = ""
                            for sel in ['[data-testid="text-location"]', ".companyLocation", ".location"]:
                                l = card.query_selector(sel)
                                if l:
                                    location = l.inner_text().strip()
                                    break

                            # 求人詳細URLを取得
                            link_el = card.query_selector("h2 a, .jobTitle a, a.tapItem")
                            href = link_el.get_attribute("href") if link_el else ""
                            job_url = f"https://jp.indeed.com{href}" if href and href.startswith("/") else href or url

                            # 簡易 description: スニペットから取得
                            desc = ""
                            for sel in [".job-snippet", ".summary", '[data-testid="job-snippet"]']:
                                d = card.query_selector(sel)
                                if d:
                                    desc = d.inner_text().strip()
                                    break

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=desc,
                                    location=location,
                                    station="",
                                    work_hours="",
                                    source_site=site,
                                    source_url=job_url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[Indeed] カードパースエラー: {e}")

                    # 次ページへ
                    next_btn = page.query_selector('[aria-label="次へ"], [data-testid="pagination-page-next"]')
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    start += 10
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[Indeed] 取得件数: {len(results)}")
    return results


# ─── バイトル ─────────────────────────────────────────────────────────

def scrape_baitoru(ctx: BrowserContext, max_per_pref: int = 50) -> List[Dict]:
    """baitoru.com から求人を収集する"""
    results: List[Dict] = []
    site = "バイトル"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            area_id = BAITORU_AREAS.get(pref, "")
            if not area_id:
                continue

            for query in SEARCH_QUERIES[:3]:
                page_num = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    url = (
                        f"https://www.baitoru.com/{area_id}/list/"
                        f"?free={quote_plus(query)}&page={page_num}"
                    )
                    logger.info(f"[バイトル] {pref} / {query} / p{page_num}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[バイトル] タイムアウト: {url}")
                        break

                    cards = page.query_selector_all(".joblist-unit, .resultItem, .job-item, article.job")
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = ""
                            for sel in [".joblist-unit-ttl", ".job-title", "h2", "h3"]:
                                t = card.query_selector(sel)
                                if t:
                                    title = t.inner_text().strip()
                                    break

                            company = ""
                            for sel in [".joblist-unit-company", ".company-name", ".corp-name"]:
                                c = card.query_selector(sel)
                                if c:
                                    company = c.inner_text().strip()
                                    break

                            location = ""
                            for sel in [".joblist-unit-access", ".work-place", ".location"]:
                                l = card.query_selector(sel)
                                if l:
                                    location = l.inner_text().strip()
                                    break

                            salary = ""
                            for sel in [".joblist-unit-salary", ".salary", ".pay"]:
                                s = card.query_selector(sel)
                                if s:
                                    salary = s.inner_text().strip()
                                    break

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            job_url = f"https://www.baitoru.com{href}" if href and href.startswith("/") else href or url

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=salary,
                                    location=location,
                                    station="",
                                    work_hours=salary,
                                    source_site=site,
                                    source_url=job_url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[バイトル] カードエラー: {e}")

                    # 次ページ確認
                    next_btn = page.query_selector(".pager-next a, .next-page a, [rel='next']")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    page_num += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[バイトル] 取得件数: {len(results)}")
    return results


# ─── 求人ボックス ─────────────────────────────────────────────────────

def scrape_kyujinbox(ctx: BrowserContext, max_per_pref: int = 50) -> List[Dict]:
    """求人ボックス から求人を収集する"""
    results: List[Dict] = []
    site = "求人ボックス"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            for query in SEARCH_QUERIES[:3]:
                p = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({"q": query, "l": pref, "p": p})
                    # 求人ボックスはIDN対応URLで動作
                    url = f"https://求人ボックス.com/jobs?{params}"
                    logger.info(f"[求人ボックス] {pref} / {query} / p{p}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[求人ボックス] タイムアウト: {url}")
                        break

                    cards = page.query_selector_all(
                        ".job-card, .result-item, article.job, .k-card, [class*='job-item']"
                    )
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = ""
                            for sel in [".job-card__title", ".title", "h2", "h3"]:
                                t = card.query_selector(sel)
                                if t:
                                    title = t.inner_text().strip()
                                    break

                            company = ""
                            for sel in [".job-card__company", ".company", ".corp"]:
                                c = card.query_selector(sel)
                                if c:
                                    company = c.inner_text().strip()
                                    break

                            location = ""
                            for sel in [".job-card__location", ".location", ".address", ".place"]:
                                l = card.query_selector(sel)
                                if l:
                                    location = l.inner_text().strip()
                                    break

                            desc = ""
                            for sel in [".job-card__description", ".description", ".summary"]:
                                d = card.query_selector(sel)
                                if d:
                                    desc = d.inner_text().strip()
                                    break

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            if href and not href.startswith("http"):
                                href = "https://求人ボックス.com" + href

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=desc,
                                    location=location,
                                    station="",
                                    work_hours="",
                                    source_site=site,
                                    source_url=href or url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[求人ボックス] カードエラー: {e}")

                    next_btn = page.query_selector(".pagination__next, [rel='next'], .next a")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    p += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[求人ボックス] 取得件数: {len(results)}")
    return results


# ─── はたらこねっと ────────────────────────────────────────────────────

def scrape_hatarakko(ctx: BrowserContext, max_per_pref: int = 40) -> List[Dict]:
    """はたらこねっと から求人を収集する"""
    results: List[Dict] = []
    site = "はたらこねっと"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            area_code = HATARAKKO_AREAS.get(pref, "")
            for query in SEARCH_QUERIES[:2]:
                p = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({
                        "keyword": query,
                        "pref": area_code,
                        "page": p,
                    })
                    url = f"https://www.hatarakko.net/jqms/search/?{params}"
                    logger.info(f"[はたらこねっと] {pref} / {query} / p{p}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[はたらこねっと] タイムアウト")
                        break

                    cards = page.query_selector_all(".job-unit, .result-box, .jqms-result-item, article")
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = _safe_text_from_elem(card, [".job-name", ".title", "h2", "h3"])
                            company = _safe_text_from_elem(card, [".company", ".corp", ".client"])
                            location = _safe_text_from_elem(card, [".location", ".address", ".place", ".access"])
                            station = _safe_text_from_elem(card, [".station", ".nearest-station"])
                            work_hours = _safe_text_from_elem(card, [".work-time", ".hours", ".time"])
                            desc = _safe_text_from_elem(card, [".description", ".detail", ".summary"])

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            if href and not href.startswith("http"):
                                href = "https://www.hatarakko.net" + href

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=desc,
                                    location=location,
                                    station=station,
                                    work_hours=work_hours,
                                    source_site=site,
                                    source_url=href or url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[はたらこねっと] カードエラー: {e}")

                    next_btn = page.query_selector(".next, [rel='next'], .pagination-next")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    p += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[はたらこねっと] 取得件数: {len(results)}")
    return results


# ─── タウンワーク ─────────────────────────────────────────────────────

def scrape_townwork(ctx: BrowserContext, max_per_pref: int = 50) -> List[Dict]:
    """タウンワーク から求人を収集する"""
    results: List[Dict] = []
    site = "タウンワーク"
    page = ctx.new_page()

    # タウンワーク エリアコード（例）
    area_codes = {
        "愛知県": "130000",  # 東海エリア愛知
        "三重県": "140000",
        "静岡県": "120000",
        "岐阜県": "130100",
    }

    try:
        for pref in TARGET_PREFECTURES:
            area_code = area_codes.get(pref, "")
            for query in SEARCH_QUERIES[:2]:
                p = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({
                        "searchWord": query,
                        "areaCode": area_code,
                        "page": p,
                    })
                    url = f"https://townwork.net/search/?{params}"
                    logger.info(f"[タウンワーク] {pref} / {query} / p{p}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[タウンワーク] タイムアウト")
                        break

                    cards = page.query_selector_all(".job-unit, .tw-job-card, article.job, .search-item")
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = _safe_text_from_elem(card, [".job-title", ".title", "h2", "h3"])
                            company = _safe_text_from_elem(card, [".company", ".corp-name", ".employer"])
                            location = _safe_text_from_elem(card, [".location", ".place", ".address", ".access"])
                            station = _safe_text_from_elem(card, [".station", ".nearest"])
                            work_hours = _safe_text_from_elem(card, [".work-time", ".hour", ".shift"])
                            desc = _safe_text_from_elem(card, [".description", ".detail", ".feature"])

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            if href and not href.startswith("http"):
                                href = "https://townwork.net" + href

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=desc,
                                    location=location,
                                    station=station,
                                    work_hours=work_hours,
                                    source_site=site,
                                    source_url=href or url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[タウンワーク] カードエラー: {e}")

                    next_btn = page.query_selector(".next-page, [rel='next'], .pagination .next")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    p += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[タウンワーク] 取得件数: {len(results)}")
    return results


# ─── スタンバイ ───────────────────────────────────────────────────────

def scrape_stanby(ctx: BrowserContext, max_per_pref: int = 50) -> List[Dict]:
    """スタンバイ (jp.stanby.com) から求人を収集する"""
    results: List[Dict] = []
    site = "スタンバイ"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            for query in SEARCH_QUERIES[:3]:
                p = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({
                        "q": query,
                        "location": pref,
                        "p": p,
                    })
                    url = f"https://jp.stanby.com/search/?{params}"
                    logger.info(f"[スタンバイ] {pref} / {query} / p{p}")

                    try:
                        page.goto(url, wait_until="networkidle", timeout=35000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[スタンバイ] タイムアウト")
                        break

                    cards = page.query_selector_all(
                        "[data-testid='job-card'], .jobCard, .job-item, article.result"
                    )
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = _safe_text_from_elem(card, [
                                "[data-testid='job-title']", ".jobTitle", ".title", "h2", "h3"
                            ])
                            company = _safe_text_from_elem(card, [
                                "[data-testid='company-name']", ".companyName", ".company"
                            ])
                            location = _safe_text_from_elem(card, [
                                "[data-testid='job-location']", ".location", ".place"
                            ])
                            salary = _safe_text_from_elem(card, [
                                "[data-testid='salary']", ".salary", ".pay"
                            ])
                            desc = _safe_text_from_elem(card, [
                                "[data-testid='job-description']", ".description", ".summary"
                            ])

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            if href and not href.startswith("http"):
                                href = "https://jp.stanby.com" + href

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=f"{desc} {salary}".strip(),
                                    location=location,
                                    station="",
                                    work_hours=salary,
                                    source_site=site,
                                    source_url=href or url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[スタンバイ] カードエラー: {e}")

                    next_btn = page.query_selector("[aria-label='次のページ'], .next, [rel='next']")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    p += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[スタンバイ] 取得件数: {len(results)}")
    return results


# ─── エンゲージ ───────────────────────────────────────────────────────

def scrape_engage(ctx: BrowserContext, max_per_pref: int = 40) -> List[Dict]:
    """エンゲージ (en-gage.net) から求人を収集する"""
    results: List[Dict] = []
    site = "エンゲージ"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            area_code = ENGAGE_AREAS.get(pref, "")
            for query in SEARCH_QUERIES[:2]:
                p = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({
                        "searchKeyword": query,
                        "areaCode": area_code,
                        "page": p,
                    })
                    url = f"https://en-gage.net/work/search/?{params}"
                    logger.info(f"[エンゲージ] {pref} / {query} / p{p}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[エンゲージ] タイムアウト")
                        break

                    cards = page.query_selector_all(
                        ".job-card, .jobListItem, article.job, .work-item, [class*='jobcard']"
                    )
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = _safe_text_from_elem(card, [".job-title", ".title", "h2", "h3"])
                            company = _safe_text_from_elem(card, [".company", ".corp", ".employer"])
                            location = _safe_text_from_elem(card, [".location", ".address", ".place"])
                            desc = _safe_text_from_elem(card, [".description", ".detail", ".feature", ".appeal"])

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            if href and not href.startswith("http"):
                                href = "https://en-gage.net" + href

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=desc,
                                    location=location,
                                    station="",
                                    work_hours="",
                                    source_site=site,
                                    source_url=href or url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[エンゲージ] カードエラー: {e}")

                    next_btn = page.query_selector(".pagination__next, .next, [rel='next']")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    p += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[エンゲージ] 取得件数: {len(results)}")
    return results


# ─── Workin ───────────────────────────────────────────────────────────

def scrape_workin(ctx: BrowserContext, max_per_pref: int = 40) -> List[Dict]:
    """Workin (workin.jp) から求人を収集する"""
    results: List[Dict] = []
    site = "Workin"
    page = ctx.new_page()

    try:
        for pref in TARGET_PREFECTURES:
            pref_code = WORKIN_PREFS.get(pref, "")
            for query in SEARCH_QUERIES[:2]:
                p = 1
                pref_count = 0

                while pref_count < max_per_pref:
                    params = urlencode({
                        "q": query,
                        "pref": pref_code,
                        "page": p,
                    })
                    url = f"https://www.workin.jp/search/list/?{params}"
                    logger.info(f"[Workin] {pref} / {query} / p{p}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        _sleep(2, 4)
                    except PWTimeoutError:
                        logger.warning(f"[Workin] タイムアウト")
                        break

                    cards = page.query_selector_all(
                        ".job-list-item, .result-item, article.job, .jobItem, [class*='job-card']"
                    )
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title = _safe_text_from_elem(card, [".job-title", ".title", "h2", "h3"])
                            company = _safe_text_from_elem(card, [".company", ".corp", ".employer"])
                            location = _safe_text_from_elem(card, [".location", ".address", ".place"])
                            station = _safe_text_from_elem(card, [".station", ".access"])
                            work_hours = _safe_text_from_elem(card, [".work-time", ".hours"])
                            desc = _safe_text_from_elem(card, [".description", ".detail", ".summary"])

                            link_el = card.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else ""
                            if href and not href.startswith("http"):
                                href = "https://www.workin.jp" + href

                            if title:
                                results.append(_make_job(
                                    title=title,
                                    posted_company=company,
                                    description=desc,
                                    location=location,
                                    station=station,
                                    work_hours=work_hours,
                                    source_site=site,
                                    source_url=href or url,
                                    prefecture=pref,
                                ))
                                pref_count += 1

                        except Exception as e:
                            logger.debug(f"[Workin] カードエラー: {e}")

                    next_btn = page.query_selector(".next, [rel='next'], .pagination-next a")
                    if not next_btn or pref_count >= max_per_pref:
                        break
                    p += 1
                    _sleep(2, 4)

    finally:
        page.close()

    logger.info(f"[Workin] 取得件数: {len(results)}")
    return results


# ─── 共通ヘルパー ─────────────────────────────────────────────────────

def _safe_text_from_elem(elem: Any, selectors: List[str], default: str = "") -> str:
    """要素の中から複数セレクタを試して最初にヒットしたテキストを返す"""
    for sel in selectors:
        try:
            child = elem.query_selector(sel)
            if child:
                text = child.inner_text().strip()
                if text:
                    return text
        except Exception:
            continue
    return default


# ─── 全サイト実行 ─────────────────────────────────────────────────────

def run_all_scrapers(ctx: BrowserContext) -> List[Dict]:
    """
    全8サイトのスクレイパーを順番に実行して結果を統合する。
    エラーが発生したサイトはスキップして継続する。
    """
    all_jobs: List[Dict] = []

    scrapers = [
        ("Indeed", scrape_indeed),
        ("バイトル", scrape_baitoru),
        ("求人ボックス", scrape_kyujinbox),
        ("はたらこねっと", scrape_hatarakko),
        ("タウンワーク", scrape_townwork),
        ("スタンバイ", scrape_stanby),
        ("エンゲージ", scrape_engage),
        ("Workin", scrape_workin),
    ]

    for name, func in scrapers:
        try:
            logger.info(f"=== {name} スクレイピング開始 ===")
            jobs = func(ctx)
            all_jobs.extend(jobs)
            logger.info(f"=== {name} 完了: {len(jobs)} 件 ===")
            _sleep(3, 6)  # サイト間のインターバル
        except Exception as e:
            logger.error(f"[{name}] スクレイパーエラー: {e}", exc_info=True)

    logger.info(f"全サイト合計: {len(all_jobs)} 件")
    return all_jobs
