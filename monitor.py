
#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path("state.json")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

TIMEOUT = 25
DELAY_SECONDS = 0.3
STATE_VERSION = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WarThunderNewsMonitor/2.0)"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

SITES = [
    {
        "name": "War Thunder 日本語公式 (DMM)",
        "language": "日本語",
        "url": "https://warthunder.dmm.com/news",
        "host": "warthunder.dmm.com",
        "article_pattern": re.compile(
            r"^/news/detail/\d+/?$"
        ),
    },
    {
        "name": "War Thunder English Official",
        "language": "ENGLISH",
        "url": "https://warthunder.com/en/news",
        "host": "warthunder.com",
        "article_pattern": re.compile(
            r"^/en/news/\d+-[^/]+/?$"
        ),
    },
]

session = requests.Session()
session.headers.update(HEADERS)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    ).rstrip("/")


def make_id(url: str) -> str:
    return hashlib.sha256(
        canonical_url(url).encode("utf-8")
    ).hexdigest()


def get_page(url: str) -> BeautifulSoup:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def is_article_url(url: str, site: dict) -> bool:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False

    if parsed.netloc.lower() != site["host"]:
        return False

    return bool(site["article_pattern"].fullmatch(parsed.path))


def extract_title(anchor) -> str:
    # まずリンク自身の文字を確認
    title = clean_text(anchor.get_text(" ", strip=True))

    # リンクの周辺にある見出しを優先
    parent = anchor

    for _ in range(5):
        if parent.parent is None:
            break

        parent = parent.parent

        heading = parent.find(
            ["h1", "h2", "h3", "h4"]
        )

        if heading:
            heading_text = clean_text(
                heading.get_text(" ", strip=True)
            )

            if 4 <= len(heading_text) <= 250:
                return heading_text

    if 4 <= len(title) <= 250:
        return title

    return ""


def extract_date(soup: BeautifulSoup) -> str:
    time_tag = soup.find("time")

    if time_tag:
        value = (
            time_tag.get("datetime")
            or time_tag.get_text(" ", strip=True)
        )
        value = clean_text(value)

        if value:
            return value[:80]

    # 日付らしい表記を探す
    text = clean_text(soup.get_text(" ", strip=True))

    patterns = [
        r"20\d{2}[./年-]\s?\d{1,2}[./月-]\s?\d{1,2}日?",
        r"\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(0)[:80]

    return ""


def extract_listing(site: dict) -> list[dict]:
    soup = get_page(site["url"])
    found = {}

    for anchor in soup.select("a[href]"):
        href = urljoin(
            site["url"],
            anchor.get("href", "").strip()
        )

        href = canonical_url(href)

        if not is_article_url(href, site):
            continue

        title = extract_title(anchor)

        if not title:
            print(f"WARNING: title not found: {href}")
            continue

        item_id = make_id(href)

        found[item_id] = {
            "id": item_id,
            "url": href,
            "title": title,
            "date": "",
            "site": site["name"],
            "language": site["language"],
        }

    items = list(found.values())

    if not items:
        raise RuntimeError(
            "記事が0件でした。取得失敗またはHTML構造の変更の可能性があります。"
        )

    return items


def extract_article_content(soup: BeautifulSoup) -> str:
    # 記事本文と思われる領域を優先
    selectors = [
        "article",
        ".news-content",
        ".news__content",
        ".article-content",
        ".article__content",
        ".content",
        "main",
    ]

    for selector in selectors:
        element = soup.select_one(selector)

        if element:
            text = clean_text(
                element.get_text(" ", strip=True)
            )

            if len(text) >= 100:
                return text[:50000]

    # 本文領域が見つからない場合は説明文を使う
    description = soup.find(
        "meta",
        attrs={"name": "description"}
    )

    if description and description.get("content"):
        return clean_text(
            description["content"]
        )[:5000]

    og_description = soup.find(
        "meta",
        property="og:description"
    )

    if og_description and og_description.get("content"):
        return clean_text(
            og_description["content"]
        )[:5000]

    raise RuntimeError(
        "記事本文・説明文を取得できませんでした。"
    )


def get_article_fingerprint(item: dict) -> dict:
    soup = get_page(item["url"])

    # 記事ページのタイトルを取得
    heading = soup.find("h1")

    if heading:
        page_title = clean_text(
            heading.get_text(" ", strip=True)
        )
        if page_title:
            item["title"] = page_title

    # 日時を取得
    item["date"] = extract_date(soup)

    # 本文を取得
    content = extract_article_content(soup)

    # タイトル・日時・本文をまとめてハッシュ化
    fingerprint_source = "\n".join([
        item["title"],
        item["date"],
        content,
    ])

    fingerprint = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()

    return {
        "id": item["id"],
        "url": item["url"],
        "title": item["title"],
        "date": item["date"],
        "fingerprint": fingerprint,
        "site": item["site"],
        "language": item["language"],
    }


def load_state() -> tuple[dict, bool]:
    if not STATE_FILE.exists():
        print("初回実行：状態ファイルがありません。")
        return {}, True

    try:
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"state.jsonを読み込めません: {exc}"
        )

    # 新形式か確認
    if (
        isinstance(data, dict)
        and data.get("version") == STATE_VERSION
        and isinstance(data.get("items"), dict)
    ):
        return data["items"], False

    # 旧形式なら初回扱いにして全記事を通知
    print(
        "旧形式のstate.jsonを検出。"
        "新方式の初回通知を実行します。"
    )

    return {}, True


def save_state(items: dict) -> None:
    data = {
        "version": STATE_VERSION,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "items": items,
    }

    temp_file = STATE_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8",
    )

    temp_file.replace(STATE_FILE)


def post_to_discord(item: dict, status: str) -> None:
    if not WEBHOOK:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URLが設定されていません。"
        )

    flag = (
        "🇯🇵"
        if item["language"] == "日本語"
        else "🇬🇧"
    )

    if status == "new":
        label = "新着記事"
        color = 0x2ECC71
    else:
        label = "記事更新"
        color = 0xF1C40F

    date_line = ""

    if item.get("date"):
        date_line = f"公開日時：{item['date']}\n"

    payload = {
        "username": "War Thunder News Monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": (
                f"{flag} [{label}] {item['title']}"
            )[:256],
            "url": item["url"],
            "description": (
                f"サイト：{item['site']}\n"
                f"{date_line}"
                f"[公式記事を開く]({item['url']})"
            ),
            "color": color,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }],
    }

    # Discordのレート制限に対応
    for attempt in range(4):
        response = session.post(
            WEBHOOK,
            json=payload,
            timeout=TIMEOUT
        )

        if response.status_code in (200, 204):
            return

        if response.status_code == 429:
            try:
                wait = float(
                    response.json().get("retry_after", 2)
                )
            except (ValueError, TypeError):
                wait = 2

            print(
                f"Discord rate limit: {wait}秒待機"
            )
            time.sleep(wait + 1)
            continue

        raise RuntimeError(
            f"Discord送信失敗: HTTP "
            f"{response.status_code}: "
            f"{response.text[:300]}"
        )

    raise RuntimeError(
        "Discordのレート制限を複数回受けました。"
    )


def collect_site(site: dict) -> list[dict]:
    print(f"\n取得開始：{site['name']}")

    listing = extract_listing(site)

    print(
        f"記事一覧から {len(listing)} 件を検出"
    )

    detailed_items = []

    for index, item in enumerate(listing, start=1):
        print(
            f"  記事確認 {index}/{len(listing)}: "
            f"{item['url']}"
        )

        detailed_items.append(
            get_article_fingerprint(item)
        )

        time.sleep(DELAY_SECONDS)

    print(
        f"取得完了：{site['name']} "
        f"({len(detailed_items)}件)"
    )

    return detailed_items


def main() -> None:
    if not WEBHOOK:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URLが設定されていません。"
        )

    old_items, is_first_run = load_state()

    new_state = dict(old_items)

    total_new = 0
    total_updated = 0
    total_unchanged = 0

    for site in SITES:
        try:
            current_items = collect_site(site)

        except Exception as exc:
            print(
                f"ERROR: {site['name']}: {exc}",
                file=sys.stderr
            )
            # このサイトの状態は変更しない
            continue

        for item in reversed(current_items):
            item_id = item["id"]
            previous = old_items.get(item_id)

            if is_first_run or previous is None:
                status = "new"
                total_new += 1

            elif previous.get("fingerprint") != item["fingerprint"]:
                status = "updated"
                total_updated += 1

            else:
                total_unchanged += 1
                new_state[item_id] = item
                continue

            try:
                post_to_discord(item, status)

                print(
                    f"通知成功 [{status}]: "
                    f"{item['title']}"
                )

                # 通知成功後に保存
                new_state[item_id] = item
                save_state(new_state)

                time.sleep(1)

            except Exception as exc:
                print(
                    f"通知失敗: {item['title']} : {exc}",
                    file=sys.stderr
                )
                # 失敗した記事は未通知のまま残す
                continue

        # 変更なしの記事も最新状態として保持
        for item in current_items:
            if item["id"] not in new_state:
                new_state[item["id"]] = item

        save_state(new_state)

    print("\n========== 実行結果 ==========")
    print(f"新着通知：{total_new}件")
    print(f"更新通知：{total_updated}件")
    print(f"変更なし：{total_unchanged}件")
    print("==============================")

    print("監視処理終了")


if __name__ == "__main__":
    main()
