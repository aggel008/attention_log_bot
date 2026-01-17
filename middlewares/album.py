import asyncio
from typing import Any, Dict, List, Union
from aiogram import BaseMiddleware
from aiogram.types import Message

class AlbumMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.5):
        self.latency = latency
        self.album_data: Dict[str, List[Message]] = {}

    async def __call__(self, handler, event: Message, data: Dict[str, Any]) -> Any:
        if not event.media_group_id:
            return await handler(event, data)

        media_group_id = event.media_group_id

        if media_group_id in self.album_data:
            self.album_data[media_group_id].append(event)
            return

        self.album_data[media_group_id] = [event]
        await asyncio.sleep(self.latency)

        data["album"] = self.album_data.pop(media_group_id)
        data["album"].sort(key=lambda x: x.message_id)
        
        return await handler(event, data)