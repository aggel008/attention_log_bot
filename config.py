import os
import json
import logging
from dotenv import load_dotenv
from dataclasses import dataclass, field

load_dotenv()

_log = logging.getLogger(__name__)

@dataclass
class Channel:
    name: str
    channel_id: str

@dataclass
class Config:
    bot_token: str
    admin_id: int
    channels: list[Channel]
    openai_key: str

    @property
    def channel_id(self) -> str:
        """Backward compatibility: returns first channel ID."""
        return self.channels[0].channel_id if self.channels else ""

def _parse_channels() -> list[Channel]:
    """
    Parse channels from CHANNELS env var (JSON) or fallback to CHANNEL_ID.
    Format: [{"name": "Main", "id": "-100123"}, {"name": "News", "id": "-100456"}]
    """
    channels_json = os.getenv('CHANNELS')
    if channels_json:
        try:
            parsed = json.loads(channels_json)
            return [Channel(name=ch["name"], channel_id=ch["id"]) for ch in parsed]
        except (json.JSONDecodeError, KeyError):
            pass

    channel_id = os.getenv('CHANNEL_ID')
    if channel_id:
        return [Channel(name="Основной канал", channel_id=channel_id)]

    return []

def load_config() -> Config:
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        raise ValueError('BOT_TOKEN is not set in environment variables')

    admin_id = os.getenv('ADMIN_ID')
    if not admin_id:
        raise ValueError('ADMIN_ID is not set in environment variables')

    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        raise ValueError('OPENAI_API_KEY is not set in environment variables')

    channels = _parse_channels()
    if not channels:
        raise ValueError('No channels configured. Set CHANNELS or CHANNEL_ID.')

    _log.debug(f"[CONFIG] Loaded {len(channels)} channel(s)")

    return Config(
        bot_token=bot_token,
        admin_id=int(admin_id),
        channels=channels,
        openai_key=openai_key
    )