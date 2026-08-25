"""
Telegram alerting for intrusion events (stretch — first item on the cut list
in PROJECT_CONTEXT.md section 5 if the team falls behind schedule).

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as environment variables.
If either is unset, this silently skips sending — the rest of the pipeline
never depends on Telegram being configured.

Setup (do this yourself, nothing is hardcoded here):
1. Message @BotFather on Telegram, send /newbot, follow the prompts — you get
   a bot token back.
2. Add the bot to whatever chat/group should receive alerts.
3. Send that chat any message, then visit
   https://api.telegram.org/bot<your_token>/getUpdates in a browser to find
   the chat_id in the response.
4. Put both values in your .env as TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""

import logging
import os

import httpx

logger = logging.getLogger("ibvap.alerting.telegram")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# snapshot_path on the event is a served URL like "/snapshots/cam_01/xxxx.jpg";
# map it back to the file on disk so we can upload the actual bytes to
# Telegram (works even before the backend is publicly reachable, e.g. behind
# NAT at a BOP).
_SNAPSHOT_ROOT = os.path.join(os.path.dirname(__file__), "..", "storage", "snapshots")


async def maybe_send_intrusion_alert(event: dict) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        logger.info("Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID unset) — skipping alert")
        return

    camera_id = event.get("camera_id")
    caption = f"Intrusion detected — camera: {camera_id} — track: {event.get('track_id')}"
    snapshot_path = event.get("snapshot_path")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            filepath = None
            if snapshot_path:
                relative = snapshot_path.replace("/snapshots/", "", 1)
                candidate = os.path.join(_SNAPSHOT_ROOT, relative)
                if os.path.exists(candidate):
                    filepath = candidate

            if filepath:
                with open(filepath, "rb") as f:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                        data={"chat_id": CHAT_ID, "caption": caption},
                        files={"photo": f},
                    )
            else:
                resp = await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": caption},
                )
            resp.raise_for_status()
            logger.info(f"[{camera_id}] Telegram alert sent")
    except httpx.HTTPError as exc:
        logger.warning(f"[{camera_id}] failed to send Telegram alert: {exc}")
