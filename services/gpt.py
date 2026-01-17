from openai import AsyncOpenAI
from config import Config

class GPTService:
    def __init__(self, config: Config):
        self.client = AsyncOpenAI(api_key=config.openai_key)
        self.model = "gpt-4o"
        self.system_instruction = (
            "Ты — профессиональный редактор Telegram-каналов. "
            "Твоя задача — переписать текст, исправить грамматические и орфографические ошибки, "
            "удалить все хештеги и оформить ключевые моменты жирным шрифтом."
        )

    async def generate_content(self, text: str) -> str:
        if not text:
            return ""
            
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_instruction},
                    {"role": "user", "content": text}
                ],
                temperature=0.7
            )
            content = response.choices[0].message.content
            return content.strip() if content else ""
        except Exception as e:
            return f"Ошибка OpenAI API: {e}"