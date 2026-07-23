import requests

from utils.logger_manager import logger
from utils.utils import read_discord_config


class DiscordNotifier:
    def __init__(self):
        config = read_discord_config()
        self.webhook_url = (config.get("webhook_url") or "").strip()
        self.mention_everyone = bool(config.get("mention_everyone", False))
        self.mention_user_ids = self._parse_id_list(config.get("mention_user_id"))
        self.mention_role_ids = self._parse_id_list(config.get("mention_role_id"))

    @staticmethod
    def _parse_id_list(raw) -> list[str]:
        if not raw:
            return []
        if isinstance(raw, str):
            raw = raw.strip()
            return [raw] if raw else []
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    def _build_mention_content(self) -> tuple[str | None, dict | None]:
        parts = []
        allowed_users: list[str] = []
        allowed_roles: list[str] = []

        if self.mention_everyone:
            parts.append("@everyone")

        for user_id in self.mention_user_ids:
            parts.append(f"<@{user_id}>")
            allowed_users.append(user_id)

        for role_id in self.mention_role_ids:
            parts.append(f"<@&{role_id}>")
            allowed_roles.append(role_id)

        if not parts:
            return None, None

        allowed_mentions: dict = {"parse": []}
        if self.mention_everyone:
            allowed_mentions["parse"] = ["everyone"]
        if allowed_users:
            allowed_mentions["users"] = allowed_users
        if allowed_roles:
            allowed_mentions["roles"] = allowed_roles

        return " ".join(parts), allowed_mentions

    def notify_live(
        self,
        username: str,
        room_id: str | None = None,
        *,
        title: str | None = None,
        avatar_url: str | None = None,
        nickname: str | None = None,
    ) -> None:
        if not self.webhook_url:
            logger.error(
                "Discord notifications enabled but webhook_url is missing in discord.json."
            )
            return

        live_url = f"https://www.tiktok.com/@{username}/live"
        author_name = nickname or f"@{username}"
        embed: dict = {
            "title": title or "Live now",
            "url": live_url,
            "color": 5793266,
            "description": f"**@{username}** is live on TikTok.\nRecording is starting.",
            "author": {
                "name": author_name,
                "url": f"https://www.tiktok.com/@{username}",
            },
        }

        if avatar_url:
            embed["author"]["icon_url"] = avatar_url
            embed["thumbnail"] = {"url": avatar_url}

        if room_id:
            embed["fields"] = [
                {"name": "Room ID", "value": str(room_id), "inline": True},
            ]

        payload = {"embeds": [embed]}

        content, allowed_mentions = self._build_mention_content()
        if content:
            payload["content"] = content
        if allowed_mentions:
            payload["allowed_mentions"] = allowed_mentions

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Discord live notification sent.")
        except requests.RequestException as e:
            logger.error(f"Failed to send Discord notification: {e}")
