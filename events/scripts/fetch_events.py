#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同人イベント・アニメイベント・キャンペーン情報の自動収集スクリプト
(Python 標準ライブラリのみ・pip インストール不要)

やること:
  1. scripts/sources.json の情報源から情報を取得
       ・赤ブーブー通信社 / ケットコム … 同人誌即売会の開催スケジュール(専用パーサ)
       ・各種ニュースRSS               … アニメイベント / キャンペーン情報
  2. タイトル・本文から「開催日」「会場」「都道府県」を推定
  3. 3つのカテゴリ(同人イベント / アニメイベント / キャンペーン)に自動分類
  4. 前回の結果(data/events.json)と統合し、終了したものを整理して書き出し

使い方:
  python3 events/scripts/fetch_events.py
"""

import gzip
import hashlib
import html as htmllib
import io
import json
import os
import re
import ssl
import sys
import time
import unicodedata
from datetime import datetime, timezone, timedelta, date
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- 設定

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # events/
SOURCES_PATH = os.path.join(ROOT, "scripts", "sources.json")
MANUAL_PATH = os.path.join(ROOT, "data", "manual.json")
OUTPUT_PATH = os.path.join(ROOT, "data", "events.json")

JST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
TIMEOUT = 30
POLITE_WAIT = 1.0        # 各リクエストの間隔(秒)
KEEP_AFTER_END_DAYS = 3  # 終了後これだけ経ったら一覧から削除
MAX_NEWS_AGE_DAYS = 90   # 日付が分からないニュースを保持する日数
MAX_ITEMS = 6000         # 出力の上限件数(超えた分は開催が遠いものから落とす)

# ------------------------------------------------- カテゴリ判定キーワード

# 同人イベント
KW_DOUJIN = [
    "同人誌即売会", "即売会", "同人イベント", "オンリーイベント", "オンリー即売会",
    "コミケ", "コミックマーケット", "コミティア", "COMITIA", "コミックシティ",
    "COMIC CITY", "サンクリ", "サンシャインクリエイション", "赤ブーブー",
    "プチオンリー", "同人誌", "サークル参加", "文学フリマ", "デザインフェスタ",
    "コミトレ", "こみトレ", "エアコミケ", "pictSQUARE", "ピクスク",
]

# アニメ・オタク系イベント
KW_EVENT = [
    "イベント", "フェス", "フェア", "展示", "展覧会", "原画展", "企画展",
    "ポップアップ", "POP UP", "ストア", "上映会", "先行上映", "舞台挨拶",
    "トークショー", "ライブ", "コンサート", "公演", "舞台", "ミュージカル",
    "オーケストラ", "アニサマ", "ワンフェス", "ワンダーフェスティバル",
    "AnimeJapan", "アニメジャパン", "コスプレ", "痛車", "オフ会", "生誕祭",
    "握手会", "サイン会", "体験会", "試遊", "出展", "ブース", "聖地巡礼",
    "スタンプラリー", "謎解き", "リアル脱出", "カフェ", "コラボカフェ",
]

# キャンペーン・コラボ
KW_CAMPAIGN = [
    "キャンペーン", "コラボ", "コラボレーション", "タイアップ", "抽選",
    "プレゼント", "くじ", "一番くじ", "応募", "特典", "先着", "限定",
    "期間限定", "割引", "セール", "クーポン", "フェア", "配布", "無料",
    "受注生産", "予約受付", "発売記念", "公開記念", "放送記念", "周年",
]

# 明らかに対象外(1つでも含めば除外)
KW_EXCLUDE = [
    "決算", "配当", "株主優待", "有価証券", "IR説明会", "役員人事", "組織変更",
    "資金調達", "業務提携のお知らせ", "M&A", "上場", "求人", "採用情報",
    "本日発売のマンガ単行本リスト", "今日のマンガ", "訃報", "逮捕", "死去",
]

# アニメ・オタク関連の話題かどうか(PR TIMES など雑多なソース向け)
KW_OTAKU = [
    "アニメ", "マンガ", "漫画", "コミック", "ラノベ", "ライトノベル", "声優",
    "同人", "コスプレ", "オタク", "二次元", "キャラクター", "TVアニメ",
    "劇場版", "アニメ化", "Vtuber", "VTuber", "バーチャル", "ゲーム",
    "ボカロ", "ボーカロイド", "初音ミク", "アイドルマスター", "ウマ娘",
    "ポケモン", "サンリオ", "ジャンプ", "少年", "少女", "特撮", "仮面ライダー",
    "ガンダム", "エヴァ", "鬼滅", "呪術廻戦", "ちいかわ", "ぬいぐるみ",
    "アクリルスタンド", "アクスタ", "缶バッジ", "フィギュア", "プラモデル",
    "2.5次元", "舞台化", "原画", "イラスト", "アニメイト", "とらのあな",
    "メロンブックス", "秋葉原", "池袋", "乙女ロード",
]

# ------------------------------------------------------ 都道府県・会場

PREFECTURES = [
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島", "茨城", "栃木",
    "群馬", "埼玉", "千葉", "東京", "神奈川", "新潟", "富山", "石川", "福井",
    "山梨", "長野", "岐阜", "静岡", "愛知", "三重", "滋賀", "京都", "大阪",
    "兵庫", "奈良", "和歌山", "鳥取", "島根", "岡山", "広島", "山口", "徳島",
    "香川", "愛媛", "高知", "福岡", "佐賀", "長崎", "熊本", "大分", "宮崎",
    "鹿児島", "沖縄",
]

REGION_OF = {}
for _r, _ps in {
    "北海道・東北": ["北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島"],
    "関東": ["茨城", "栃木", "群馬", "埼玉", "千葉", "東京", "神奈川"],
    "中部": ["新潟", "富山", "石川", "福井", "山梨", "長野", "岐阜", "静岡", "愛知"],
    "近畿": ["三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山"],
    "中国・四国": ["鳥取", "島根", "岡山", "広島", "山口", "徳島", "香川", "愛媛", "高知"],
    "九州・沖縄": ["福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄"],
}.items():
    for _p in _ps:
        REGION_OF[_p] = _r

# 有名会場から都道府県を割り出す
VENUE_PREF = [
    ("東京ビッグサイト", "東京"), ("ビッグサイト", "東京"), ("東京国際展示場", "東京"),
    ("インテックス大阪", "大阪"), ("大阪南港", "大阪"), ("ATCホール", "大阪"),
    ("ポートメッセなごや", "愛知"), ("名古屋市国際展示場", "愛知"), ("吹上ホール", "愛知"),
    ("幕張メッセ", "千葉"), ("makuhari", "千葉"),
    ("パシフィコ横浜", "神奈川"), ("横浜ア", "神奈川"), ("Kアリーナ", "神奈川"),
    ("大田区産業プラザ", "東京"), ("PiO", "東京"), ("TRC", "東京"),
    ("東京流通センター", "東京"), ("サンシャインシティ", "東京"), ("池袋", "東京"),
    ("秋葉原", "東京"), ("有明", "東京"), ("浜松町", "東京"), ("両国", "東京"),
    ("科学技術館", "東京"), ("東京드", "東京"), ("東京ドーム", "東京"),
    ("さいたまスーパーアリーナ", "埼玉"), ("ソニックシティ", "埼玉"),
    ("神戸国際展示場", "兵庫"), ("神戸サンボー", "兵庫"),
    ("京都パルスプラザ", "京都"), ("みやこめっせ", "京都"),
    ("マリンメッセ福岡", "福岡"), ("福岡国際センター", "福岡"), ("博多", "福岡"),
    ("札幌コンベンション", "北海道"), ("アクセスサッポロ", "北海道"),
    ("仙台", "宮城"), ("夢メッセ", "宮城"),
    ("広島産業会館", "広島"), ("岡山コンベンション", "岡山"),
    ("ツインメッセ静岡", "静岡"), ("アオーレ長岡", "新潟"),
    ("オンライン", "オンライン"), ("pictSQUARE", "オンライン"),
]

# 主要都市名から都道府県を割り出す(会場名に県名が入らないケース向け)
CITY_PREF = [
    ("神戸", "兵庫"), ("姫路", "兵庫"), ("西宮", "兵庫"), ("尼崎", "兵庫"),
    ("浦和", "埼玉"), ("大宮", "埼玉"), ("川越", "埼玉"), ("所沢", "埼玉"),
    ("横浜", "神奈川"), ("川崎", "神奈川"), ("藤沢", "神奈川"), ("相模原", "神奈川"),
    ("名古屋", "愛知"), ("豊橋", "愛知"), ("岡崎", "愛知"),
    ("札幌", "北海道"), ("函館", "北海道"), ("旭川", "北海道"),
    ("仙台", "宮城"), ("郡山", "福島"), ("いわき", "福島"),
    ("博多", "福岡"), ("天神", "福岡"), ("小倉", "福岡"), ("北九州", "福岡"),
    ("難波", "大阪"), ("なんば", "大阪"), ("梅田", "大阪"), ("心斎橋", "大阪"),
    ("堺", "大阪"), ("船橋", "千葉"), ("柏", "千葉"), ("幕張", "千葉"),
    ("新潟", "新潟"), ("金沢", "石川"), ("松山", "愛媛"), ("高松", "香川"),
    ("那覇", "沖縄"), ("鹿児島", "鹿児島"), ("熊本", "熊本"), ("長崎", "長崎"),
    ("岡山", "岡山"), ("広島", "広島"), ("松江", "島根"), ("鳥取", "鳥取"),
    ("渋谷", "東京"), ("新宿", "東京"), ("原宿", "東京"), ("中野", "東京"),
    ("上野", "東京"), ("お台場", "東京"), ("立川", "東京"), ("町田", "東京"),
]

# 海外都市(国内の都道府県フィルタから外す)
OVERSEAS = ["台北", "台湾", "上海", "香港", "ソウル", "北京", "広州", "シンガポール",
            "バンコク", "ニューヨーク", "ロサンゼルス", "パリ", "ロンドン", "ベルリン"]

# --------------------------------------------------------- HTTP 取得


def fetch(url, encoding=None, retries=2):
    """URL を取得して文字列で返す。失敗したら None。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en;q=0.8",
                "Accept-Encoding": "gzip",
            })
            with urlopen(req, timeout=TIMEOUT, context=ctx) as res:
                raw = res.read()
                if res.headers.get("Content-Encoding") == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                if encoding:
                    return raw.decode(encoding, "replace")
                # charset をヘッダ or メタタグから推測
                ctype = res.headers.get("Content-Type", "")
                m = re.search(r"charset=([\w\-]+)", ctype, re.I)
                enc = m.group(1) if m else None
                if not enc:
                    head = raw[:2048].decode("ascii", "ignore")
                    m = re.search(r'charset=["\']?([\w\-]+)', head, re.I)
                    enc = m.group(1) if m else "utf-8"
                if enc.lower() in ("shift_jis", "sjis", "x-sjis", "shift-jis"):
                    enc = "cp932"
                try:
                    return raw.decode(enc, "replace")
                except LookupError:
                    return raw.decode("utf-8", "replace")
        except (URLError, HTTPError, OSError, ssl.SSLError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    log(f"  × 取得失敗: {url} ({last_err})")
    return None


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------- テキストユーティリティ


def strip_tags(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    s = s.replace("　", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def norm(s):
    """全角英数を半角にそろえた比較用の文字列。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s).lower()


def has_any(text, words):
    t = norm(text)
    return any(norm(w) in t for w in words)


def matched(text, words):
    t = norm(text)
    return [w for w in words if norm(w) in t]


# ------------------------------------------------------------ 日付抽出

TODAY = datetime.now(JST).date()

_MD = r"(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
_SEP = r"\s*(?:～|〜|~|から|-|–|—|ー|より)\s*"

RE_RANGE_FULL = re.compile(_MD + _SEP + _MD)
RE_RANGE_DAY = re.compile(_MD + _SEP + r"(\d{1,2})\s*日")
RE_SINGLE = re.compile(_MD)
RE_SLASH = re.compile(r"(?<![\d/])(20\d{2})\s*[/.]\s*(\d{1,2})\s*[/.]\s*(\d{1,2})(?![\d/])")


def _mk(year, month, day, base=None):
    """年が無い場合は「今日から見て一番近い未来」の年を採用する。"""
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if year:
        try:
            return date(int(year), month, day)
        except ValueError:
            return None
    base = base or TODAY
    for y in (base.year, base.year + 1, base.year - 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if (d - base).days >= -45:
            return d
    return None


def extract_dates(text):
    """文章から (開始日, 終了日, 元の表記) を推定する。見つからなければ (None, None, None)。"""
    if not text:
        return None, None, None
    t = unicodedata.normalize("NFKC", text)

    m = RE_SLASH.search(t)
    if m:
        d = _mk(m.group(1), int(m.group(2)), int(m.group(3)))
        if d:
            return d, None, m.group(0)

    m = RE_RANGE_FULL.search(t)
    if m:
        y1, m1, d1, y2, m2, d2 = m.groups()
        s = _mk(y1, int(m1), int(d1))
        e = _mk(y2 or y1, int(m2), int(d2), base=s or TODAY)
        if s and e and e < s:
            try:
                e = date(s.year + 1, e.month, e.day)
            except ValueError:
                e = None
        if s:
            return s, e, m.group(0)

    m = RE_RANGE_DAY.search(t)
    if m:
        y1, m1, d1, d2 = m.groups()
        s = _mk(y1, int(m1), int(d1))
        e = _mk(y1 or (s.year if s else None), int(m1), int(d2))
        if s:
            return s, e, m.group(0)

    m = RE_SINGLE.search(t)
    if m:
        s = _mk(m.group(1), int(m.group(2)), int(m.group(3)))
        if s:
            return s, None, m.group(0)

    return None, None, None


def detect_pref(text):
    """文章から都道府県を推定する。"""
    if not text:
        return None
    t = unicodedata.normalize("NFKC", text)
    for venue, pref in VENUE_PREF:
        if venue in t:
            return pref
    for p in PREFECTURES:
        if p + "都" in t or p + "府" in t or p + "県" in t or p == "北海道" and p in t:
            return p
    for city in OVERSEAS:
        if city in t:
            return "海外"
    for p in PREFECTURES:
        if p in t:
            return p
    for city, pref in CITY_PREF:
        if city in t:
            return pref
    if "オンライン" in t or "配信" in t:
        return "オンライン"
    return None


# ------------------------------------------------------------ 分類


def classify(title, body, source_id, default=None):
    """カテゴリを判定する。対象外なら None を返す。"""
    text = f"{title}\n{body}"
    if has_any(text, KW_EXCLUDE):
        return None
    if default:
        return default
    if has_any(text, KW_DOUJIN):
        return "doujin"
    is_event = has_any(text, KW_EVENT)
    is_camp = has_any(text, KW_CAMPAIGN)
    # 「コラボカフェ」のように両方に当たる場合はイベント寄りの語を優先
    if is_event and not is_camp:
        return "anime_event"
    if is_camp and not is_event:
        return "campaign"
    if is_event and is_camp:
        strong_event = has_any(text, [
            "上映会", "舞台挨拶", "ライブ", "コンサート", "公演", "展覧会", "原画展",
            "企画展", "ポップアップ", "イベント開催", "出展", "フェス", "サイン会",
        ])
        return "anime_event" if strong_event else "campaign"
    return None


def make_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def title_key(title):
    """重複判定用のキー(記号を落として比較)。"""
    t = norm(title)
    t = re.sub(r"[「」『』【】\[\]()（）!！?？・、。,\.\-–—~〜:：/]", "", t)
    return t[:60]


# -------------------------------------------------- 赤ブーブー通信社パーサ

RE_AKA_SECTION = re.compile(
    r'<div id="(\d{4})"></div>\s*<font[^>]*>\s*<b>\s*(\d{1,2})/(\d{1,2})\(([^)]*)\)([^<]*)</b>')
RE_AKA_ROW = re.compile(
    r'<td[^>]*bgcolor="#FFEBEB"[^>]*>\s*<a href="([^"]+)">\s*<b>(.*?)</b>\s*</a>\s*(?:<br\s*/?>)?(.*?)</td>'
    r'(.*?)(?=<td[^>]*bgcolor="#FFEBEB"|</table>|<div id=")',
    re.S | re.I)


def parse_akaboo(url, page_year_hint=None):
    """赤ブーブー通信社のイベント一覧ページを解析する。"""
    html = fetch(url)
    if not html:
        return []

    # ページ冒頭の「20XX年」見出しから対象年を得る
    year = page_year_hint
    m = re.search(r"<font[^>]*size=\"5\"[^>]*>\s*<b>\s*(20\d{2})年", html)
    if m:
        year = int(m.group(1))
    if not year:
        m = re.search(r"(20\d{2})年", html)
        year = int(m.group(1)) if m else TODAY.year

    # 日付見出しごとにページを区切る
    sections = []
    marks = list(RE_AKA_SECTION.finditer(html))
    for i, mk in enumerate(marks):
        start = mk.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        mm, dd = int(mk.group(2)), int(mk.group(3))
        try:
            d = date(year, mm, dd)
        except ValueError:
            continue
        head = strip_tags(mk.group(5))
        venue = head.split("：")[0].split(":")[0].strip() or None
        sections.append((d, venue, html[start:end]))

    out = []
    for d, venue, chunk in sections:
        for rm in RE_AKA_ROW.finditer(chunk):
            link, title_html, genre_html, rest_html = rm.groups()
            title = strip_tags(title_html)
            if not title:
                continue
            genre = strip_tags(genre_html)
            cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rest_html, re.S | re.I)]
            fee = cells[0] if len(cells) > 0 else ""
            deadline_txt = cells[2] if len(cells) > 2 else ""
            entry_txt = cells[4] if len(cells) > 4 else ""
            cosplay_txt = cells[5] if len(cells) > 5 else ""

            deadline = None
            dm = re.search(r"(\d{1,2})/(\d{1,2})", deadline_txt or "")
            if dm:
                try:
                    deadline = date(year, int(dm.group(1)), int(dm.group(2)))
                    if deadline > d:
                        deadline = date(year - 1, int(dm.group(1)), int(dm.group(2)))
                except ValueError:
                    deadline = None

            pref = detect_pref(venue or "") or detect_pref(title)
            tags = [t for t in [genre] if t]
            if cosplay_txt and "可" in cosplay_txt:
                tags.append("コスプレ可")

            out.append({
                "id": make_id("akaboo", link),
                "category": "doujin",
                "title": title,
                # 会場・日付はカード側で別に表示するので、要約にはジャンルと参加費だけ入れる
                "summary": " / ".join(x for x in [genre, fee and f"1スペース {fee}"] if x),
                "url": link if link.startswith("http") else "https://www.akaboo.jp" + link,
                "source": "赤ブーブー通信社",
                "source_id": "akaboo",
                "start_date": d.isoformat(),
                "end_date": None,
                "date_text": None,
                "venue": venue,
                "prefecture": pref,
                "region": REGION_OF.get(pref or "", None),
                "deadline": deadline.isoformat() if deadline else None,
                "entry": entry_txt or None,
                "tags": tags,
            })
    log(f"  ・{url} → {len(out)} 件")
    return out


# ------------------------------------------------------- ケットコムパーサ


RE_KETTO_TITLE_LINK = re.compile(r'<A\s+HREF="([^"]+)"[^>]*>\s*「([^」]{2,80})」\s*</A>', re.I)
RE_KETTO_PLACE = re.compile(
    r"\([^)]{1,8}\)\s*(?:\d{1,2}:\d{2}\s*[-〜～~]\s*\d{1,2}:\d{2})?\s*([^\s:：\[|]{2,5})[:：]\s*([^\[\n|]{2,50})")


def parse_ketto(url, encoding="cp932"):
    """ケットコムのトップページ(オンリーイベント一覧)を解析する。"""
    html = fetch(url, encoding=encoding)
    if not html:
        return []
    out = []
    for block in html.split("<HR>"):
        text = strip_tags(block)
        dm = re.search(r"(20\d{2})/(\d{1,2})/(\d{1,2})", text)
        if not dm:
            continue
        try:
            d = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            continue

        after = text[dm.end():]

        # 「タイトル」がリンクになっていればURLも一緒に取れる
        title = link = None
        tl = RE_KETTO_TITLE_LINK.search(block)
        if tl:
            link, title = tl.group(1), tl.group(2).strip()
        else:
            tm = re.search(r"「([^」]{2,80})」", after)
            if tm:
                title = tm.group(1).strip()
        if not title or title in ("ケットコム",):
            continue

        time_m = re.search(r"(\d{1,2}:\d{2}\s*[-〜～~]\s*\d{1,2}:\d{2})", after)
        time_text = time_m.group(1).replace(" ", "") if time_m else None

        venue = None
        vm = re.search(r"会場[:：]\s*([^\n\[|]{2,40})", after)
        if vm:
            venue = vm.group(1).strip()
        else:
            vm = RE_KETTO_PLACE.search(after)
            if vm:
                venue = vm.group(2).strip()
        if venue:
            venue = re.sub(r"\s{2,}", " ", venue).strip(" 　-")

        # ジャンル(s5.cgi のリンクテキスト)
        genres = [strip_tags(g) for g in re.findall(r"s5\.cgi\?[^\"']*\"[^>]*>([^<]{1,30})</A>", block, re.I)]
        genres = [g for g in genres if g and g not in ("単独開催",)]

        tags = re.findall(r"\[([^\]\[]{1,20})\]", after)
        tags = [t.strip() for t in tags if t.strip() and not t.startswith("〆切") and not t.startswith("#")]

        deadline = None
        dl = re.search(r"〆切\s*(20\d{2})/(\d{1,2})/(\d{1,2})", after)
        if dl:
            try:
                deadline = date(int(dl.group(1)), int(dl.group(2)), int(dl.group(3)))
            except ValueError:
                deadline = None

        if not link:
            link = "https://ketto.com/"

        pm = RE_KETTO_PLACE.search(after)
        pref = pm.group(1) if pm else None
        if pref not in PREFECTURES:
            pref = detect_pref(" ".join([venue or "", after[:60], title]))

        out.append({
            "id": make_id("ketto", title, d.isoformat()),
            "category": "doujin",
            "title": title,
            "summary": "・".join(genres[:3]),
            "url": link,
            "source": "ケットコム",
            "source_id": "ketto",
            "start_date": d.isoformat(),
            "end_date": None,
            "date_text": time_text,
            "venue": venue,
            "prefecture": pref,
            "region": REGION_OF.get(pref or "", None),
            "deadline": deadline.isoformat() if deadline else None,
            "entry": None,
            "tags": (genres[:3] + tags)[:6],
        })
    log(f"  ・{url} → {len(out)} 件")
    return out


# ------------------------------------------------------------ RSS/Atom

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_feed(feed):
    """RSS 2.0 / RSS 1.0(RDF) / Atom を読み取り、共通の辞書リストにする。"""
    xml = fetch(feed["url"])
    if not xml:
        return []
    xml = xml.lstrip("﻿ \n\r\t")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        log(f"  × XML解析に失敗: {feed['url']} ({e})")
        return []

    entries = []
    # RSS 2.0
    for it in root.findall(".//item"):
        entries.append({
            "title": _text(it.find("title")),
            "link": _text(it.find("link")) or (it.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or ""),
            "desc": _text(it.find("description")) or _text(it.find("content:encoded", NS)),
            "date": _text(it.find("pubDate")) or _text(it.find("dc:date", NS)),
        })
    # RSS 1.0 (RDF, 名前空間つき)
    if not entries:
        for it in root.findall(".//rss:item", NS):
            entries.append({
                "title": _text(it.find("rss:title", NS)),
                "link": _text(it.find("rss:link", NS)),
                "desc": _text(it.find("rss:description", NS)),
                "date": _text(it.find("dc:date", NS)),
            })
    # Atom
    if not entries:
        for it in root.findall(".//atom:entry", NS):
            link_el = it.find("atom:link", NS)
            link = link_el.get("href") if link_el is not None else ""
            entries.append({
                "title": _text(it.find("atom:title", NS)),
                "link": link,
                "desc": _text(it.find("atom:summary", NS)) or _text(it.find("atom:content", NS)),
                "date": _text(it.find("atom:updated", NS)) or _text(it.find("atom:published", NS)),
            })

    out = []
    for e in entries:
        title = strip_tags(e["title"])
        if not title or not e["link"]:
            continue
        body = strip_tags(e["desc"])[:600]
        blob = f"{title}\n{body}"

        # 雑多なソース(PR TIMES 等)はオタク関連の話題に絞る
        if feed.get("strict") and not has_any(blob, KW_OTAKU):
            continue

        cat = classify(title, body, feed["id"])
        if not cat:
            continue

        published = parse_pubdate(e["date"])
        s, en, dtext = extract_dates(blob)
        pref = detect_pref(blob)
        venue = extract_venue(blob)

        out.append({
            "id": make_id(feed["id"], e["link"]),
            "category": cat,
            "title": title,
            "summary": body[:180],
            "url": e["link"],
            "source": feed["name"],
            "source_id": feed["id"],
            "start_date": s.isoformat() if s else None,
            "end_date": en.isoformat() if en else None,
            "date_text": dtext,
            "venue": venue,
            "prefecture": pref,
            "region": REGION_OF.get(pref or "", None),
            "deadline": None,
            "entry": None,
            "tags": sorted(set(matched(blob, KW_CAMPAIGN + KW_EVENT)))[:5],
            "published": published.isoformat() if published else None,
        })
    log(f"  ・{feed['name']} → {len(out)} 件 (全 {len(entries)} 件中)")
    return out


RE_VENUE = re.compile(
    r"(?:会場|開催場所|場所)[はに:：]?\s*([^\n。、]{2,40})|"
    r"([^\s。、]{2,20}(?:ビッグサイト|メッセ|アリーナ|ホール|会館|ドーム|スタジアム|美術館|博物館|劇場|シアター|パルコ|ヒカリエ|センター))")


def extract_venue(text):
    m = RE_VENUE.search(text or "")
    if not m:
        return None
    v = (m.group(1) or m.group(2) or "").strip()
    return v[:40] or None


def parse_pubdate(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=JST)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ------------------------------------------------------------ 統合・出力


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def is_expired(ev):
    """終了して一覧から外してよいか判定する。"""
    end = ev.get("end_date") or ev.get("start_date")
    if end:
        try:
            d = date.fromisoformat(end)
            return (TODAY - d).days > KEEP_AFTER_END_DAYS
        except ValueError:
            pass
    first = ev.get("first_seen")
    if first:
        try:
            d = datetime.fromisoformat(first).date()
            return (TODAY - d).days > MAX_NEWS_AGE_DAYS
        except ValueError:
            pass
    return False


# 出力から省くキー(アプリ側で計算できる / 表示に使わない)
# source は source_id と対応表(source_names)から復元できるので出力しない
DROP_KEYS = {"region", "last_seen", "source"}


def slim(ev):
    """空の項目を落として JSON を軽くする。"""
    out = {}
    for k, v in ev.items():
        if k in DROP_KEYS:
            continue
        if v is None or v == "" or v == [] or v is False:
            continue
        out[k] = v
    return out


def sort_key(ev):
    """開催が近いものを上に。日付不明はその後ろに新着順で並べる。"""
    s = ev.get("start_date")
    if s:
        try:
            d = date.fromisoformat(s)
            days = (d - TODAY).days
            return (0, days if days >= 0 else 9999 - days, ev.get("title", ""))
        except ValueError:
            pass
    return (1, -(_epoch(ev.get("published") or ev.get("first_seen"))), ev.get("title", ""))


def _epoch(iso):
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return 0


def main():
    log("=" * 56)
    log(f"イベント情報の収集を開始します ({datetime.now(JST):%Y-%m-%d %H:%M} JST)")
    log("=" * 56)

    sources = load_json(SOURCES_PATH, {"sites": [], "feeds": []})
    collected = []

    log("\n[1] 同人イベント(即売会スケジュール)")
    for site in sources.get("sites", []):
        if not site.get("enabled", True):
            continue
        log(f" {site['name']}")
        for i, url in enumerate(site.get("urls", [])):
            if site["parser"] == "akaboo":
                collected += parse_akaboo(url)
            elif site["parser"] == "ketto":
                collected += parse_ketto(url, site.get("encoding", "cp932"))
            time.sleep(POLITE_WAIT)

    log("\n[2] アニメイベント・キャンペーン(ニュース)")
    for feed in sources.get("feeds", []):
        if not feed.get("enabled", True):
            continue
        collected += parse_feed(feed)
        time.sleep(POLITE_WAIT)

    log("\n[3] 手動追加データ")
    manual = load_json(MANUAL_PATH, {"events": []}).get("events", [])
    for ev in manual:
        ev.setdefault("id", make_id("manual", ev.get("title", ""), ev.get("start_date", "")))
        ev.setdefault("source", "手動登録")
        ev.setdefault("source_id", "manual")
        ev.setdefault("category", "anime_event")
        ev["manual"] = True
        pref = ev.get("prefecture") or detect_pref(f"{ev.get('venue','')} {ev.get('title','')}")
        ev["prefecture"] = pref
        ev["region"] = REGION_OF.get(pref or "", None)
    collected += manual
    log(f"  ・{len(manual)} 件")

    # ---- 前回の結果とマージ ----
    prev = load_json(OUTPUT_PATH, {"events": []})
    prev_by_id = {e["id"]: e for e in prev.get("events", []) if e.get("id")}

    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    today_iso = TODAY.isoformat()
    merged = {}
    seen_titles = {}

    for ev in collected:
        eid = ev["id"]
        old = prev_by_id.get(eid)
        ev["first_seen"] = (old or {}).get("first_seen", today_iso)
        ev["last_seen"] = now_iso
        if old and old.get("manual"):
            ev["manual"] = True
        merged[eid] = ev

    # 前回あって今回取れなかったものも、期限内なら残す
    for eid, ev in prev_by_id.items():
        if eid not in merged:
            merged[eid] = ev

    # ---- 期限切れの除去と、タイトル重複の解消 ----
    events = []
    for ev in merged.values():
        if is_expired(ev):
            continue
        key = (ev.get("category"), title_key(ev.get("title", "")), ev.get("start_date"))
        if key in seen_titles:
            # 情報量の多い方を残す
            a = seen_titles[key]
            if len(json.dumps(ev, ensure_ascii=False)) <= len(json.dumps(a, ensure_ascii=False)):
                continue
            events.remove(a)
        seen_titles[key] = ev
        events.append(ev)

    events.sort(key=sort_key)
    events = events[:MAX_ITEMS]

    counts = {"doujin": 0, "anime_event": 0, "campaign": 0}
    for ev in events:
        counts[ev.get("category", "campaign")] = counts.get(ev.get("category", "campaign"), 0) + 1

    # source_id → 表示名 の対応表(各イベントから source 文字列を省くため)
    source_names = {}
    for ev in events:
        if ev.get("source_id") and ev.get("source"):
            source_names[ev["source_id"]] = ev["source"]
    for src in sources.get("sites", []) + sources.get("feeds", []):
        source_names.setdefault(src["id"], src["name"])
    source_names.setdefault("manual", "手動登録")

    payload = {
        "updated_at": now_iso,
        "total": len(events),
        "counts": counts,
        "source_names": source_names,
        "events": [slim(e) for e in events],
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    log("\n" + "=" * 56)
    log(f"完了: 全 {len(events)} 件を {os.path.relpath(OUTPUT_PATH, os.path.dirname(ROOT))} に保存しました")
    log(f"  同人イベント   : {counts.get('doujin', 0)} 件")
    log(f"  アニメイベント : {counts.get('anime_event', 0)} 件")
    log(f"  キャンペーン   : {counts.get('campaign', 0)} 件")
    log("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
