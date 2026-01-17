import os
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()

@dataclass
class Config:
    bot_token: str
    admin_id: int
    channel_id: str
    openai_key: str
    system_instruction: str

def load_config() -> Config:
    admin_id = os.getenv('ADMIN_ID')
    if not admin_id:
        raise ValueError('ADMIN_ID is not set in environment variables')

    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        raise ValueError('OPENAI_API_KEY is not set in environment variables')

    return Config(
        bot_token=os.getenv('BOT_TOKEN'),
        admin_id=int(admin_id),
        channel_id=os.getenv('CHANNEL_ID'),
        openai_key=openai_key,
        system_instruction=(
            "Ты — помощник в стиле Crypto Twitter\n"
            "ПРАВИЛА ОФОРМЛЕНИЯ:\n"
            "1. Для выделения жирным используй ТОЛЬКО HTML-теги: <b>текст</b>\n"
            "2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать любые звездочки (*)\n"
            "3. Используй обычные двойные кавычки для названий\n"
            "4. НИКОГДА не ставь точку в конце последнего предложения абзаца"
        )
    )