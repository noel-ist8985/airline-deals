#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航空セール情報の自動取得スクリプト(標準ライブラリのみ・pip不要)

やること:
  1. scripts/sources.json に書かれた各航空会社の RSS(主に PR TIMES 企業別RSS)を取得
  2. 「セール/キャンペーン/運賃/割引…」等のキーワードで関連リリースを抽出
  3. 既存の data/sales.json 形式に変換
  4. 手動データ(data/manual.json)と統合して data/sales.json を書き出し

情報源について:
  航空会社セールを統一的に配信する公式APIは無いため、機械可読な
  PR TIMES の「企業別RSS」( https://prtimes.jp/companyrdf.php?company_id=ID )を主に使う。
  プレスリリース由来なので価格・締切などの細かい欄は空になることが多い。

使い方:
  python3 scripts/fetch_deals.py
"""

import html
import json
import os
import re
import ssl
import subprocess
import sys
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError
import xml.etree.ElementTree as ET

# ---- 設定 ----
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "scripts", "sources.json")
MANUAL_PATH = os.path.join(ROOT, "data", "manual.json")
OUTPUT_PATH = os.path.join(ROOT, "data", "sales.json")

JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (AirlineDeals fetcher; +https://example.com)"
TIMEOUT = 25
MAX_AGE_DAYS = 180      # これより古いリリースは取り込まない
MAX_PER_SOURCE = 8      # 1社あたりの最大取り込み件数

# 関連リリースと判定するキーワード(いずれか含めば対象)
INCLUDE_KEYWORDS = [
    "セール", "キャンペーン", "運賃", "割引", "特別", "タイムセール", "クーポン",
    "お得", "プレゼント", "特典", "マイル", "ポイント", "OFF", "オフ", "値下げ",
    "弾丸", "就航", "開設", "増便", "記念", "無料", "抽選", "フェア",
]
# 明らかに関係ない企業ニュースを除外(いずれか含めば除外)
EXCLUDE_KEYWORDS = [
    "決算", "配当", "役員人事", "組織変更", "有価証券", "IR説明会",
    "燃油", "付加運賃", "運賃改定", "運賃の改定",  # 値上げ系はセールではない
]

# 種別の推定(上から順に判定)
TYPE_RULES = [
    ("イベント", ["イベント", "フェス", "抽選", "プレゼント", "展示", "出展", "ブース", "体験会"]),
    ("セール", ["セール", "タイムセール", "特価", "割引", "値下げ", "弾丸", "運賃", "OFF", "オフ"]),
    ("キャンペーン", ["キャンペーン", "クーポン", "マイル", "ポイント", "特典", "記念", "無料"]),
]


def log(msg):
    print(msg, flush=True)


def fetch_url(url):
    """URL を取得して文字列で返す。urllib が SSL で失敗したら curl にフォールバック。"""
    req = Request(url, headers={"User-Agent": UA})
    try:
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=TIMEOUT, context=ctx) as res:
            return res.read().decode("utf-8", errors="replace")
    except (ssl.SSLError, URLError) as e:
        log(f"  urllib 失敗({e}) → curl で再試行")
        try:
            out = subprocess.run(
                ["curl", "-sL", "-A", UA, "--max-time", str(TIMEOUT), url],
                capture_output=True, timeout=TIMEOUT + 5,
            )
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", errors="replace")
        except Exception as e2:
            log(f"  curl も失敗: {e2}")
    return None


def localname(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(elem, names):
    """localname が names のいずれかに一致する子要素のテキストを返す。"""
    for c in elem:
        if localname(c.tag) in names:
            return (c.text or "").strip()
    return ""


def parse_feed(xml_text):
    """RSS1.0(RDF) / RSS2.0 を許容してアイテム一覧を返す。"""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log(f"  XML 解析エラー: {e}")
        return items
    for elem in root.iter():
        if localname(elem.tag) != "item":
            continue
        title = child_text(elem, ["title"])
        link = child_text(elem, ["link"])
        if not link:
            # RSS1.0 は rdf:about 属性に URL が入ることがある
            for k, v in elem.attrib.items():
                if localname(k) == "about":
                    link = v.strip()
        desc = child_text(elem, ["description", "summary"])
        date = child_text(elem, ["date", "pubDate", "published", "updated"])
        if title and link:
            items.append({"title": title, "link": link, "description": desc, "date": date})
    return items


def parse_date(s):
    """様々な日付表記を JST の datetime に。失敗したら None。"""
    if not s:
        return None
    s = s.strip()
    # ISO 8601 (PR TIMES: 2026-05-14T16:44:48+09:00)
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone(JST)
    except ValueError:
        pass
    # RFC822 (RSS2.0: Wed, 14 May 2026 16:44:48 +0900)
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(s, fmt).astimezone(JST)
        except ValueError:
            continue
    return None


def clean_text(s):
    s = html.unescape(s or "")                       # &nbsp; 等を復元
    s = re.sub(r"<[^>]+>", "", s)                     # HTMLタグ除去
    s = re.sub(r"\[画像\d*[:：][^\]]*\]", "", s)      # [画像1: ...] プレースホルダ除去
    s = re.sub(r"\[(?:動画|表)\d*[:：][^\]]*\]", "", s)
    s = s.replace(" ", " ")                      # ノーブレークスペース
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_summary(s):
    """PR TIMES 概要先頭の「[社名] 2026年7月8日 」等の定型接頭辞を除去。"""
    s = clean_text(s)
    s = re.sub(r"^\[[^\]]*\]\s*", "", s)                  # [会社名]
    s = re.sub(r"^\d{4}年\d{1,2}月\d{1,2}日\s*", "", s)   # 日付
    return s.strip()


def is_relevant(title, desc):
    text = f"{title} {desc}"
    if any(k in text for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in text for k in INCLUDE_KEYWORDS)


def classify_type(title, desc):
    text = f"{title} {desc}"
    for label, kws in TYPE_RULES:
        if any(k in text for k in kws):
            return label
    return "キャンペーン"


def make_id(link):
    h = hashlib.md5(link.encode("utf-8")).hexdigest()[:10]
    return f"auto-{h}"


def build_entry(item, airline):
    title = clean_text(item["title"])
    desc = clean_summary(item["description"])
    summary = (desc[:110] + "…") if len(desc) > 110 else desc
    d = parse_date(item["date"])
    posted = d.isoformat() if d else datetime.now(JST).isoformat()
    return {
        "id": make_id(item["link"]),
        "airline": airline,
        "type": classify_type(title, desc),
        "title": title,
        "summary": summary or "(詳細は公式ページをご覧ください)",
        "url": item["link"],
        "priceFrom": None,
        "currency": "JPY",
        "routes": [],
        "saleStart": "",
        "saleEnd": "",
        "travelPeriod": "",
        "postedAt": posted,
        "tags": ["自動取得"],
        "source": "PR TIMES",
    }, d


def main():
    sources = json.load(open(SOURCES_PATH, encoding="utf-8")).get("sources", [])
    now = datetime.now(JST)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)

    auto_entries = []
    for src in sources:
        if not src.get("enabled", True):
            continue
        airline = src["airline"]
        url = src["url"]
        log(f"取得: {airline}  {url}")
        xml_text = fetch_url(url)
        if not xml_text:
            log("  → 取得失敗、スキップ")
            continue
        items = parse_feed(xml_text)
        log(f"  {len(items)} 件のリリース")
        kept = 0
        for it in items:
            if kept >= MAX_PER_SOURCE:
                break
            if not is_relevant(it["title"], it["description"]):
                continue
            entry, d = build_entry(it, airline)
            if d and d < cutoff:
                continue
            auto_entries.append(entry)
            kept += 1
        log(f"  → {kept} 件を採用")

    # 手動データを読み込み(あれば)
    manual = []
    if os.path.exists(MANUAL_PATH):
        manual = json.load(open(MANUAL_PATH, encoding="utf-8")).get("sales", [])
        for m in manual:
            m.setdefault("source", "manual")

    # 重複除去(URL基準):手動を優先し、同一URLの自動分は除外
    seen = set(m.get("url", "") for m in manual)
    deduped_auto = []
    for e in auto_entries:
        if e["url"] in seen:
            continue
        seen.add(e["url"])
        deduped_auto.append(e)

    combined = manual + deduped_auto

    # postedAt の新しい順で並べ替え
    def sort_key(x):
        d = parse_date(x.get("postedAt", ""))
        return d or datetime.min.replace(tzinfo=JST)
    combined.sort(key=sort_key, reverse=True)

    out = {
        "updatedAt": now.isoformat(),
        "note": "PR TIMES 等から自動取得した情報と、手動分(data/manual.json)を統合しています。"
                "価格・締切などが空の項目は自動取得分です。詳細は各公式ページでご確認ください。",
        "sales": combined,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    log("")
    log(f"完了: 手動 {len(manual)} 件 + 自動 {len(deduped_auto)} 件 = 合計 {len(combined)} 件")
    log(f"出力: {OUTPUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
