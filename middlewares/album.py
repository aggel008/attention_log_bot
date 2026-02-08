import asyncio
import time
from typing import Any, Dict, List
from aiogram import BaseMiddleware
from aiogram.types import Message

class AlbumMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.5, cleanup_timeout: float = 60.0):
        self.latency = latency
        self.cleanup_timeout = cleanup_timeout
        self.album_data: Dict[str, tuple[List[Message], float]] = {}

    async def __call__(self, handler, event: Message, data: Dict[str, Any]) -> Any:
        if not event.media_group_id:
            return await handler(event, data)

        media_group_id = event.media_group_id
        current_time = time.time()

        # Cleanup old albums (memory leak prevention)
        to_remove = [
            group_id for group_id, (_, timestamp) in self.album_data.items()
            if current_time - timestamp > self.cleanup_timeout
        ]
        for group_id in to_remove:
            self.album_data.pop(group_id, None)

        if media_group_id in self.album_data:
            self.album_data[media_group_id][0].append(event)
            return

        self.album_data[media_group_id] = ([event], current_time)
        await asyncio.sleep(self.latency)

        album_messages, _ = self.album_data.pop(media_group_id, ([], 0))
        if album_messages:
            album_messages.sort(key=lambda x: x.message_id)
            data["album"] = album_messages

        return await handler(event, data)