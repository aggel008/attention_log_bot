import re
import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from google import genai
from google.genai import types
from config import Config

_log = logging.getLogger(__name__)

LINK_PATTERN = re.compile(r'https?://(?:[^\s<>\"()]|\([^\s<>\"()]*\))+')
LINK_TOKEN = "⟦LINK:{n}⟧"
TRACKING_PARAMS = {
    # UTM
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    # Common referral
    "ref", "referral", "source", "campaign",
    # Facebook / Meta
    "fbclid", "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    # Google
    "gclid", "gclsrc", "dclid", "_ga", "_gl", "_gac",
    # Yandex
    "yclid", "ysclid", "ymclid",
    # Email / marketing
    "mc_eid", "mc_cid", "mkt_tok",
    # Social
    "igshid", "share_id", "si", "feature", "share_source", "vn_source",
    # Twitter / X
    "twclid", "s", "t",
    # General tracking
    "spm", "scm", "aff_id", "aff_sub", "clickid", "trk", "tracking_id",
}


class LLMService:
    def __init__(self, config: Config):
        # Initialize Google GenAI client with Vertex AI
        self.client = genai.Client(
            vertexai=True,
            project=config.vertex_project_id,
            location=config.vertex_location
        )
        # Use model from config (default: gemini-2.5-pro)
        self.model_name = config.vertex_model
        _log.info(f"[LLM] Using model: {self.model_name}")

        # Generation config matching previous OpenAI settings
        self.generation_config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192
        )

    async def _make_request(self, system_instruction: str, text: str) -> str:
        if not text:
            return ""

        # Combine system instruction and user text into single prompt
        # Claude via Vertex AI works better with combined context
        full_prompt = f"{system_instruction}\n\n---\n\nИсходный текст для переработки:\n\n{text}"

        # Use async generate_content method from google-genai
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=full_prompt,
            config=self.generation_config
        )

        content = response.text
        return content.strip() if content else ""

    def _extract_all_links(self, text: str, entities: list | None) -> tuple[str, dict[str, dict]]:
        """Extract all links (entity + raw) and replace with non-linguistic tokens.

        LLM never sees URLs — only ⟦LINK:n⟧ tokens.
        Returns: (text_with_tokens, links)
        links: {token: {"anchor": str|None, "url": str}}
        """
        links = {}
        counter = 0

        # Step 1: Extract entity links (process from end to avoid offset shifts)
        # Support both Telegram MessageEntity objects and plain dicts
        if entities:
            def _get(e, key, default=None):
                if isinstance(e, dict):
                    return e.get(key, default)
                return getattr(e, key, default)

            # Log incoming entities for debugging
            _log.info(f"[LLM] Processing {len(entities)} entities")
            for e in entities:
                _log.info(f"[LLM]   Entity: type={_get(e, 'type')}, offset={_get(e, 'offset')}, length={_get(e, 'length')}, url={_get(e, 'url')}")

            # Filter entities: text_link (with url field) OR url type (URL in text)
            link_entities = []
            for e in entities:
                entity_type = _get(e, "type")
                if entity_type == "text_link" and _get(e, "url"):
                    link_entities.append(e)
                elif entity_type == "url":
                    # For 'url' type, the URL is in the text itself
                    link_entities.append(e)

            sorted_entities = sorted(link_entities, key=lambda e: _get(e, "offset"), reverse=True)

            for entity in sorted_entities:
                start = _get(entity, "offset")
                end = start + _get(entity, "length")
                anchor_or_url = text[start:end]  # This is either anchor text or the URL itself
                entity_type = _get(entity, "type")

                if entity_type == "text_link":
                    # text_link: custom anchor with hidden URL
                    url = _get(entity, "url")
                    token = LINK_TOKEN.format(n=counter)
                    links[token] = {"anchor": anchor_or_url, "url": url}
                    _log.info(f"[LLM]   Extracted text_link: anchor='{anchor_or_url[:30]}', url='{url[:50]}'")
                elif entity_type == "url":
                    # url: visible URL in text (no custom anchor)
                    url = anchor_or_url  # The URL is the text itself
                    token = LINK_TOKEN.format(n=counter)
                    links[token] = {"anchor": None, "url": url}
                    _log.info(f"[LLM]   Extracted url: url='{url[:50]}'")

                counter += 1
                text = text[:start] + token + text[end:]

        # Step 2: Extract raw URLs from modified text
        def replace_url(match):
            nonlocal counter
            url = match.group(0)
            token = LINK_TOKEN.format(n=counter)
            links[token] = {"anchor": None, "url": url}  # No anchor for raw URLs
            counter += 1
            return token

        text = LINK_PATTERN.sub(replace_url, text)
        return text, links

    def _restore_all_links(self, text: str, links: dict[str, dict]) -> tuple[str, list[dict]]:
        """Restore links from tokens and build entities for Telegram.

        Returns: (restored_text, entities)
        entities: [{"offset": int, "length": int, "type": "text_link", "url": str}]
        """
        _log.info(f"[LLM] Restoring {len(links)} link tokens from rewritten text")
        new_entities = []
        remaining = dict(links)

        # Process tokens in order of appearance (left to right)
        while remaining:
            # Find first token in current text
            first_token = None
            first_pos = len(text)
            for token in remaining:
                pos = text.find(token)
                if pos != -1 and pos < first_pos:
                    first_pos = pos
                    first_token = token

            if first_token is None:
                # Remaining tokens are missing
                for token, data in remaining.items():
                    _log.error(f"[LLM] LINK TOKEN MISSING: {token} -> {data['url'][:50]}")
                break

            data = remaining.pop(first_token)
            anchor = data["anchor"]
            url = data["url"]
            clean_url = self._clean_url(url)

            # Replacement text: anchor for entity links, URL for raw links
            replacement = anchor if anchor else clean_url

            # Replace token with replacement
            text = text[:first_pos] + replacement + text[first_pos + len(first_token):]

            # Build entity
            new_entities.append({
                "offset": first_pos,
                "length": len(replacement),
                "type": "text_link",
                "url": clean_url
            })
            _log.info(f"[LLM]   Restored {first_token}: '{replacement[:30]}' -> {clean_url[:50]}")

        return text, new_entities

    def _clean_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query, keep_blank_values=True)
            cleaned = {k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS}
            new_query = urlencode(cleaned, doseq=True) if cleaned else ""
            return urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            ))
        except Exception:
            return url

    def _normalize_paragraphs(self, text: str) -> str:
        """Normalize newlines for Telegram without breaking links or content."""
        if not text:
            return text
        # Collapse 3+ newlines into exactly 2 (clean up excessive spacing)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _adjust_entities_after_normalize(
        self, original: str, normalized: str, entities: list[dict]
    ) -> list[dict]:
        """Recalculate entity offsets after text normalization.

        Builds a character-level offset map from original to normalized text,
        so even duplicate anchors get correct positions.
        """
        if not entities:
            return []

        # Build offset mapping: original char index -> normalized char index
        # Walk both strings in parallel, skipping extra newlines in original
        # that were collapsed during normalization.
        o2n = {}
        ni = 0
        oi = 0
        while oi < len(original) and ni < len(normalized):
            if original[oi] == normalized[ni]:
                o2n[oi] = ni
                oi += 1
                ni += 1
            else:
                # This char was removed during normalization (extra newline)
                oi += 1

        adjusted = []
        for entity in entities:
            old_offset = entity["offset"]
            if old_offset in o2n:
                adjusted.append({
                    "offset": o2n[old_offset],
                    "length": entity["length"],
                    "type": entity["type"],
                    "url": entity["url"]
                })
            else:
                # Fallback: search by text
                link_text = original[old_offset:old_offset + entity["length"]]
                new_offset = normalized.find(link_text)
                if new_offset != -1:
                    adjusted.append({
                        "offset": new_offset,
                        "length": entity["length"],
                        "type": entity["type"],
                        "url": entity["url"]
                    })
                else:
                    _log.error(f"[LLM] Entity text not found after normalize: {link_text[:30]}")

        return adjusted

    async def rewrite_text(self, text: str, entities: list | None = None) -> tuple[str, list[dict]]:
        """Rewrite text and return (text, entities) for Telegram API.

        Returns:
            tuple: (rewritten_text, caption_entities)
            - caption_entities: list of {"offset", "length", "type", "url"} for text_link
        """
        _log.debug("[LLM] rewrite_text() called")

        instruction = (
            "ПЕРЕД ТЕМ КАК ПИСАТЬ — ДУМАЙ.\n\n"
            "ШАГ 1. ПОНЯТЬ ИНТЕНТ:\n"
            "Прочитай исходник и определи:\n"
            "— Что это: наблюдение, рефлексия, вопрос, опыт, фиксация факта, странный случай, что-то ещё?\n"
            "— Зачем этот пост существует? Какая мысль за ним стоит?\n"
            "— Нужна ли тут эмоция или нет?\n\n"
            "ШАГ 2. ЕСЛИ НЕПОНЯТНО — НЕ ПИШИ:\n"
            "— Если не понял, как именно это должно звучать — перечитай.\n"
            "— НЕ выбирай 'нейтральный', 'сухой', 'ироничный' или любой другой дефолт.\n"
            "— Писать без понимания интента ЗАПРЕЩЕНО.\n\n"
            "ШАГ 3. ТОНАЛЬНОСТЬ — СЛЕДСТВИЕ МЫСЛИ:\n"
            "— Тон должен вытекать из содержания, а не быть заданным заранее.\n"
            "— Мысль сухая → текст сухой.\n"
            "— Мысль странная → текст может быть странным.\n"
            "— Эмоция не нужна → не добавляй.\n\n"
            "ТОЛЬКО ПОСЛЕ ПОНИМАНИЯ ИНТЕНТА — ПИШИ:\n\n"
            "ПОЗИЦИЯ АВТОРА:\n"
            "— Неявная, родная. Читается из формулировок, структуры, фокуса.\n"
            "— НЕ пиши 'я думаю', 'я считаю'.\n\n"
            "ЯЗЫК:\n"
            "— НЕ формальный, НЕ академический.\n"
            "— НЕ объясняй 'для тех, кто не знает'.\n"
            "— НЕ продавай идеи, НЕ хайпуй, НЕ лей воду.\n\n"
            "СТРУКТУРА И АБЗАЦЫ:\n"
            "— Формат: Telegram-пост. Разделитель абзацев — ОДНА пустая строка (два переноса \\n\\n).\n"
            "— Один абзац = одна законченная мысль, 2–4 предложения. Не режь мысль на куски.\n"
            "— НЕ лепи стену текста — если мысль сменилась, начинай новый абзац.\n"
            "— НЕ делай абзацы из одного слова, одной фразы или одного предложения.\n"
            "— Оптимально: 2–5 абзацев на пост. Зависит от объёма мысли.\n"
            "— Тире, скобки внутри текста — ок, но не выноси их в отдельные строки.\n"
            "— Списки — только если это естественная форма для данной мысли.\n"
            "— Без вывода в конце — ок.\n"
            "— НЕ ставь точку в конце последнего предложения абзаца.\n\n"
            "ТЕРМИНОЛОГИЯ:\n"
            "— НЕ заменяй и НЕ упрощай профессиональный сленг.\n"
            "— 'промпт', 'агент', 'LLM', техжаргон — оставляй.\n\n"
            "ТОКЕНЫ ССЫЛОК (КРИТИЧЕСКИ ВАЖНО):\n"
            "— Если в исходном тексте есть токены вида ⟦LINK:0⟧, ⟦LINK:1⟧ — это маркеры ссылок.\n"
            "— Каждый токен ОБЯЗАН остаться в выходном тексте ровно один раз в ТОЧНО ТАКОМ ЖЕ виде.\n"
            "— Нельзя удалять, изменять формат, дублировать токены.\n"
            "— ЗАПРЕЩЕНО создавать новые токены ⟦LINK:N⟧, если их не было в исходнике.\n"
            "— ЗАПРЕЩЕНО заменять упоминания моделей, продуктов или версий на токены.\n"
            "— Пример: 'Claude Opus 4.6' остаётся как есть, НЕ превращается в токен.\n"
            "— Пропавший или лишний токен = критическая ошибка.\n\n"
            "ГЛУБИНА ПЕРЕРАБОТКИ:\n"
            "— Это НЕ пересказ и НЕ перефраз.\n"
            "— Пиши С НУЛЯ, вдохновляясь исходником.\n"
            "— Свободно меняй порядок идей.\n"
            "— Сжимай агрессивно.\n"
            "— Результат должен читаться как личный ход мысли, а не переписанный пост.\n\n"
            "ПУНКТУАЦИЯ:\n"
            "— Используй только обычное короткое тире (-), НИКОГДА не используй длинное тире (—) или среднее тире (–).\n"
            "— Не ставь точку в конце абзаца.\n\n"
            "ЗАПРЕЩЕНО:\n"
            "— Любая дефолтная тональность.\n"
            "— Любой стилистический шаблон.\n"
            "— Эмоциональные украшения, не оправданные самой мыслью.\n"
            "— 'В заключение', 'таким образом', 'следовательно'.\n"
            "— Длинное тире (—) и среднее тире (–). Только короткое (-)."
        )

        # Step 1: Extract ALL links (entity + raw) → non-linguistic tokens
        # LLM never sees URLs, only ⟦LINK:n⟧
        text_safe, links = self._extract_all_links(text, entities)

        _log.info(f"[LLM] Links extracted: {len(links)}")
        _log.info(f"[LLM] Text with tokens (preview): {text_safe[:200]}")

        # Step 2: LLM rewrite (sees only text + tokens, no URLs)
        raw = await self._make_request(instruction, text_safe)

        _log.info(f"[LLM] LLM response (preview): {raw[:200]}")
        # Check if tokens are preserved
        for token in links.keys():
            if token not in raw:
                _log.error(f"[LLM] TOKEN LOST BY LLM: {token} -> {links[token]['url'][:50]}")

        # Step 3: Restore tokens → text + build entities for Telegram
        restored, new_entities = self._restore_all_links(raw, links)

        _log.info(f"[LLM] Links restored: {len(new_entities)} entities built")

        # Step 4: Normalize paragraphs for Telegram (no length-based splitting)
        final_text = self._normalize_paragraphs(restored)

        # Step 5: Adjust entity offsets after normalization
        # (normalization may change text length, so recalculate offsets)
        adjusted_entities = self._adjust_entities_after_normalize(restored, final_text, new_entities)

        return final_text, adjusted_entities