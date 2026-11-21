#!/usr/bin/env python3
"""Monitor War Thunder DMM JP and Gaijin EN news and post new items to Discord."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path("state.json")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

SITES = [
    {
        "name": "War Thunder 日本語公式 (DMM)",
        "language": "日本語",
        "url": "https://warthunder.dmm.com/news",
        "host": "warthunder.dmm.com",
    },
    {
        "name": "War Thunder English Official",
        "language": "ENGLISH",
        "url": "https://warthunder.com/en/news",
        "host": "warthunder.com",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WarThunderNewsMonitor/1.0; +https://github.com/)",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
TIMEOUT = 25
MAX_ITEMS_PER_SITE = 40


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    # Remove tracking query and fragment; preserve path.
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def stable_id(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


def get_page(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def looks_like_article(url: str, host: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and not (parsed.netloc == host or parsed.netloc.endswith("." + host)):
        return False
    path = parsed.path.lower()
    if not path or path in {"/", "/en", "/en/"}:
        return False
    if any(x in path for x in ["/tag/", "/category/", "/search", "/login", "/account"]):
        return False
    return True


def extract_items(site: dict) -> list[dict]:
    soup = get_page(site["url"])
    found: dict[str, dict] = {}

    # General-purpose extraction: inspect links and their nearest card-like container.
    for anchor in soup.select("a[href]"):
        href = urljoin(site["url"], anchor.get("href", "").strip())
        if not looks_like_article(href, site["host"]):
            continue

        anchor_text = clean_text(anchor.get_text(" ", strip=True))
        parent = anchor
        best_text = anchor_text
        for _ in range(4):
            if parent.parent:
                parent = parent.parent
            candidate = clean_text(parent.get_text(" ", strip=True))
            if 12 <= len(candidate) <= 700:
                best_text = candidate
                break

        title = anchor_text
        if len(title) < 4:
            heading = parent.find(["h1", "h2", "h3", "h4"])
            if heading:
                title = clean_text(heading.get_text(" ", strip=True))
        if len(title) < 4:
            continue

        # Exclude navigation and generic links.
        if title.lower() in {"read more", "続きを読む", "詳細", "more", "news", "ニュース"}:
            continue

        date_text = ""
        time_tag = parent.find("time")
        if time_tag:
            date_text = clean_text(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
        if not date_text:
            date_match = re.search(r"\b20\d{2}[./年-]\s?\d{1,2}[./月-]\s?\d{1,2}日?\b", best_text)
            if date_match:
                date_text = date_match.group(0)

        item = {
            "id": stable_id(href),
            "title": title[:250],
            "url": canonical_url(href),
            "date": date_text[:80],
            "site": site["name"],
            "language": site["language"],
        }
        found[item["id"]] = item

    # Prefer items with a plausible title and limit noisy footer/navigation links.
    items = list(found.values())
    return items[:MAX_ITEMS_PER_SITE]


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print("WARNING: state.json could not be read; treating as first run.", file=sys.stderr)
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def post_to_discord(item: dict) -> None:
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret is missing.")

    flag = "🇯🇵" if item["language"] == "日本語" else "🇬🇧"
    date_line = f"公開日時：{item['date']}\n" if item.get("date") else ""
    payload = {
        "username": "War Thunder News Monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": f"{flag} [{item['language']}] {item['title']}"[:256],
            "url": item["url"],
            "description": f"**サイト：** {item['site']}\n{date_line}[公式記事を開く]({item['url']})",
            "color": 0x3498DB if item["language"] == "ENGLISH" else 0x2ECC71,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=TIMEOUT)
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Discord webhook failed: HTTP {response.status_code}: {response.text[:500]}")


def main() -> None:
    if not DISCORD_WEBHOOK:
        raise RuntimeError("Set DISCORD_WEBHOOK_URL in GitHub Actions secrets.")

    state = load_state()
    is_first_run = not bool(state)
    current_ids: dict[str, dict] = {}
    errors = []

    for site in SITES:
        try:
            items = extract_items(site)
            if not items:
                print(f"WARNING: no article links detected on {site['name']}.")
            for item in items:
                current_ids[item["id"]] = item
            print(f"{site['name']}: found {len(items)} candidate items.")
        except Exception as exc:
            errors.append(f"{site['name']}: {exc}")
            print(f"ERROR: {site['name']}: {exc}", file=sys.stderr)

    if is_first_run:
        if errors:
            # Do not create a partial baseline: otherwise a temporarily unavailable
            # site could produce a burst of old notifications when it comes back.
            raise RuntimeError(
                "Initial baseline was not saved because at least one site failed. "
                "Fix/retry the workflow. Details: " + " | ".join(errors)
            )
        print("First run: saving current articles as baseline; no Discord notifications.")
        save_state({key: {"title": item["title"], "url": item["url"]} for key, item in current_ids.items()})
        return

    new_items = [item for key, item in current_ids.items() if key not in state]

    # Save only after successful fetches for the relevant site; state is merged to avoid
    # forgetting known posts if one of the two websites is temporarily unavailable.
    updated_state = dict(state)
    for key, item in current_ids.items():
        updated_state[key] = {"title": item["title"], "url": item["url"]}

    # Send oldest-first within the discovered batch, so the Discord channel reads naturally.
    for item in reversed(new_items):
        post_to_discord(item)
        print(f"Posted: [{item['language']}] {item['title']}")

    # Keep a rolling history to avoid an unbounded state file.
    if len(updated_state) > 1500:
        updated_state = dict(list(updated_state.items())[-1200:])
    save_state(updated_state)

    if errors:
        print("Some sources failed: " + " | ".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
