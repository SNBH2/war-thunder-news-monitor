
import os
import requests
from datetime import datetime, timezone

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

def main():
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured.")

    payload = {
        "username": "War Thunder News Monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": "🇯🇵 Discord通知テスト成功！",
            "description": (
                "War Thunder News Monitorからのテスト送信です。\n"
                "Discord Webhookとの接続を確認しました。"
            ),
            "color": 0x2ECC71,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    }

    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        timeout=25
    )

    if response.status_code not in (200, 204):
        raise RuntimeError(
            f"Discord webhook failed: HTTP {response.status_code}"
        )

    print("Discord test notification sent successfully.")

if __name__ == "__main__":
    main()

