import re
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, LinkPreviewOptions, MessageEntity
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from config import Config
from services.llm import LLMService
from utils.states import PostState

_log = logging.getLogger(__name__)

admin_router = Router()

# In-memory storage for last used channel per user
_user_last_channel: dict[int, int] = {}

def final_fix(text):
    # Убираем все звездочки, если они вдруг пролезли
    text = text.replace("*", "")
    # Длинные тире (em-dash) → обычное тире
    text = text.replace("—", "-")
    text = text.replace("–", "-")
    # Убираем точки в конце строк/абзацев
    text = re.sub(r'\.(?=\s*(\n|$))', '', text)
    return text.strip()

# --- КЛАВИАТУРЫ ---
def get_action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Publish", callback_data="publish"),
         InlineKeyboardButton(text="✏️ Edit", callback_data="edit_manual")],
        [InlineKeyboardButton(text="🔄 Regenerate", callback_data="regen"),
         InlineKeyboardButton(text="🗑 Delete", callback_data="delete")]
    ])

def get_channel_keyboard(config: Config, last_idx: int | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for i, ch in enumerate(config.channels):
        if i == last_idx:
            label = f"✓ {ch.name} (последний)"
            buttons.insert(0, [InlineKeyboardButton(text=label, callback_data=f"channel:{i}")])
        else:
            buttons.append([InlineKeyboardButton(text=ch.name, callback_data=f"channel:{i}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_publish")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ЛОГИКА ---

# Используем config из dependency injection вместо load_config() в фильтре
@admin_router.message(F.forward_origin)
async def handle_forward(message: Message, state: FSMContext, bot: Bot, config: Config, llm: LLMService, album: list[Message] = None):
    """Принимаем форвард (одиночный или альбом)"""

    # Проверка прав доступа
    if message.from_user.id != config.admin_id:
        return

    # 1. Достаем текст, медиа и entities
    # Для альбомов текст и entities берем из первого сообщения альбома
    if album:
        original_text = album[0].caption or ""
        entities = album[0].caption_entities or []
        _log.info(f"[ADMIN] Album forward: text_len={len(original_text)}, entities={len(entities)}")
        _log.info(f"[ADMIN] Album received: text_len={len(original_text)}, entities_count={len(entities)}")

        media_group = []
        for msg in album:
            if msg.photo:
                media_group.append({"type": "photo", "media": msg.photo[-1].file_id})
            elif msg.video:
                media_group.append({"type": "video", "media": msg.video.file_id})

        await state.update_data(media_group=media_group, is_album=True)
    else:
        # Get text and entities (works for both text and caption)
        original_text = message.caption or message.text or ""
        entities = message.caption_entities or message.entities or []
        _log.info(f"[ADMIN] Message received: text_len={len(original_text)}, entities_count={len(entities)}")
        for e in (entities or []):
            _log.info(f"[ADMIN]   Entity: type={e.type}, offset={e.offset}, length={e.length}, url={getattr(e, 'url', None)}")

        # Вот этот блок ниже должен стоять ровно под original_text
        if message.photo:
            await state.update_data(media_type="photo", file_id=message.photo[-1].file_id, is_album=False)
        elif message.video:
            await state.update_data(media_type="video", file_id=message.video.file_id, is_album=False)
        else:
            await state.update_data(media_type="text", is_album=False)

    # 2. Информируем админа (Индикатор работы)
    processing_msg = await message.answer("⏳ Processing...")

    # 3. Генерируем (передаем entities для сохранения text_link)
    try:
        generated_text, generated_entities = await llm.rewrite_text(original_text, entities=entities)
        # Очистка (Post-processing)
        generated_text = final_fix(generated_text)
    except Exception as e:
        _log.error(f"[ADMIN] GPT rewrite error: {e}", exc_info=True)
        await processing_msg.edit_text(f"❌ Ошибка генерации текста: {e}")
        return

    # 4. Сохраняем в FSM (включая entities для regenerate и публикации)
    # Convert Telegram MessageEntity objects to dicts for FSM serialization
    original_entities_dicts = []
    for e in entities:
        d = {"type": e.type, "offset": e.offset, "length": e.length}
        if e.url:
            d["url"] = e.url
        original_entities_dicts.append(d)

    await state.update_data(
        generated_text=generated_text,
        generated_entities=generated_entities,
        original_text=original_text,
        original_entities=original_entities_dicts
    )
    
    # 5. Показываем превью
    await processing_msg.delete()
    await send_preview(message, state, generated_text, is_new=True)

async def send_preview(message: Message, state: FSMContext, text: str, is_new: bool = False):
    """Отправляет превью поста админу"""
    data = await state.get_data()

    # Get entities for preview (so admin sees clickable links)
    entities = data.get("generated_entities", [])
    tg_entities = [
        MessageEntity(
            type=e["type"],
            offset=e["offset"],
            length=e["length"],
            url=e.get("url")
        ) for e in entities
    ] if entities else None

    CAPTION_LIMIT = 1024

    if is_new:
        has_media = data.get("is_album") or data.get("media_type") in ("photo", "video")

        if has_media and len(text) > CAPTION_LIMIT:
            # Текст слишком длинный для caption — шлём медиа без подписи + текст отдельно
            if data.get("is_album") and data.get("media_group"):
                first_media = data["media_group"][0]
                album_prefix = "[ALBUM] "
                if first_media["type"] == "photo":
                    await message.answer_photo(first_media["media"])
                elif first_media["type"] == "video":
                    await message.answer_video(first_media["media"])
            elif data.get("media_type") == "photo":
                await message.answer_photo(photo=data["file_id"])
            elif data.get("media_type") == "video":
                await message.answer_video(video=data["file_id"])

            prefix = "[ALBUM] " if data.get("is_album") else ""
            msg_text = f"{prefix}{text}" if prefix else text
            # Shift entities for prefix if needed
            if prefix and tg_entities:
                tg_entities = [
                    MessageEntity(type=e.type, offset=e.offset + len(prefix), length=e.length, url=e.url)
                    for e in tg_entities
                ]
            await message.answer(msg_text, entities=tg_entities, reply_markup=get_action_keyboard())

        elif data.get("is_album") and data.get("media_group"):
            # Для альбома показываем первое медиа как превью
            first_media = data["media_group"][0]
            album_prefix = "[ALBUM] "
            # Shift entity offsets to account for prefix
            shifted_entities = [
                MessageEntity(
                    type=e["type"],
                    offset=e["offset"] + len(album_prefix),
                    length=e["length"],
                    url=e.get("url")
                ) for e in entities
            ] if entities else None

            caption_text = f"{album_prefix}{text}"
            if first_media["type"] == "photo":
                await message.answer_photo(
                    first_media["media"],
                    caption=caption_text,
                    caption_entities=shifted_entities,
                    reply_markup=get_action_keyboard()
                )
            elif first_media["type"] == "video":
                await message.answer_video(
                    first_media["media"],
                    caption=caption_text,
                    caption_entities=shifted_entities,
                    reply_markup=get_action_keyboard()
                )
        elif data.get("media_type") == "photo":
            await message.answer_photo(
                photo=data["file_id"],
                caption=text,
                caption_entities=tg_entities,
                reply_markup=get_action_keyboard()
            )
        elif data.get("media_type") == "video":
            await message.answer_video(
                video=data["file_id"],
                caption=text,
                caption_entities=tg_entities,
                reply_markup=get_action_keyboard()
            )
        else:
            msg_text = text if text else "⚠️ (Нет текста)"
            await message.answer(msg_text, entities=tg_entities, reply_markup=get_action_keyboard())

    await state.set_state(PostState.viewing_preview)

# --- КНОПКИ ---

@admin_router.callback_query(F.data == "regen", StateFilter(PostState.viewing_preview))
async def on_regen(callback: CallbackQuery, state: FSMContext, llm: LLMService):
    # Убираем кнопки, чтобы показать процесс
    await callback.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    entities = data.get("original_entities", [])

    try:
        new_text, new_entities = await llm.rewrite_text(data["original_text"], entities=entities)
        # Очистка (Post-processing)
        new_text = final_fix(new_text)
    except Exception as e:
        _log.error(f"[ADMIN] GPT regenerate error: {e}", exc_info=True)
        await callback.message.edit_text(f"❌ Ошибка регенерации: {e}")
        await callback.answer()
        return

    await state.update_data(generated_text=new_text, generated_entities=new_entities)

    await callback.message.delete()
    await send_preview(callback.message, state, new_text, is_new=True)

@admin_router.callback_query(F.data == "edit_manual", StateFilter(PostState.viewing_preview))
async def on_edit_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Пришли мне новый текст поста:")
    await state.update_data(preview_message_id=callback.message.message_id,
                            preview_chat_id=callback.message.chat.id)
    # Удаляем старое превью чтобы не было дублей
    try:
        await callback.message.delete()
    except Exception:
        pass
    await state.set_state(PostState.waiting_for_correction)
    await callback.answer()

@admin_router.callback_query(F.data == "delete", StateFilter(PostState.viewing_preview))
async def on_delete(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.clear()
    await callback.answer("Отменено")

@admin_router.callback_query(F.data == "publish", StateFilter(PostState.viewing_preview))
async def on_publish(callback: CallbackQuery, state: FSMContext, bot: Bot, config: Config):
    user_id = callback.from_user.id

    if len(config.channels) > 1:
        last_idx = _user_last_channel.get(user_id)
        await callback.message.edit_reply_markup(reply_markup=get_channel_keyboard(config, last_idx))
        await state.set_state(PostState.selecting_channel)
        await callback.answer("Выберите канал для публикации")
        return
    await _do_publish(callback, state, bot, config.channels[0].channel_id, channel_idx=0)

@admin_router.callback_query(F.data.startswith("channel:"), StateFilter(PostState.selecting_channel))
async def on_channel_selected(callback: CallbackQuery, state: FSMContext, bot: Bot, config: Config):
    idx = int(callback.data.split(":")[1])
    if idx < 0 or idx >= len(config.channels):
        await callback.answer("❌ Неверный канал", show_alert=True)
        return

    channel = config.channels[idx]
    await _do_publish(callback, state, bot, channel.channel_id, channel_idx=idx)

@admin_router.callback_query(F.data == "cancel_publish", StateFilter(PostState.selecting_channel))
async def on_cancel_publish(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=get_action_keyboard())
    await state.set_state(PostState.viewing_preview)
    await callback.answer("Отменено")

async def _do_publish(callback: CallbackQuery, state: FSMContext, bot: Bot, chat_id: str, channel_idx: int = 0):
    _log.info(f"[ADMIN] _do_publish called: chat_id={chat_id}, channel_idx={channel_idx}")
    data = await state.get_data()
    text = data["generated_text"]
    entities = data.get("generated_entities", [])

    _log.info(f"[ADMIN] Publishing: text_len={len(text)}, entities_count={len(entities)}")
    _log.info(f"[ADMIN] Media type: is_album={data.get('is_album')}, media_type={data.get('media_type')}")

    # Convert entity dicts to MessageEntity objects for Telegram API
    tg_entities = [
        MessageEntity(
            type=e["type"],
            offset=e["offset"],
            length=e["length"],
            url=e.get("url")
        ) for e in entities
    ] if entities else None

    try:
        if data.get("is_album") and data.get("media_group"):
            media = []
            for i, item in enumerate(data["media_group"]):
                if i == 0:
                    # First item gets caption + entities
                    if item["type"] == "photo":
                        media.append(InputMediaPhoto(
                            media=item["media"],
                            caption=text,
                            caption_entities=tg_entities
                        ))
                    elif item["type"] == "video":
                        media.append(InputMediaVideo(
                            media=item["media"],
                            caption=text,
                            caption_entities=tg_entities
                        ))
                else:
                    if item["type"] == "photo":
                        media.append(InputMediaPhoto(media=item["media"]))
                    elif item["type"] == "video":
                        media.append(InputMediaVideo(media=item["media"]))
            await bot.send_media_group(chat_id=chat_id, media=media)

        elif data.get("media_type") == "photo":
            await bot.send_photo(chat_id=chat_id, photo=data["file_id"], caption=text, caption_entities=tg_entities)

        elif data.get("media_type") == "video":
            await bot.send_video(chat_id=chat_id, video=data["file_id"], caption=text, caption_entities=tg_entities)

        else:
            if not text:
                await callback.answer("❌ Ошибка: текст пустой, нечего публиковать!", show_alert=True)
                return
            await bot.send_message(chat_id=chat_id, text=text, entities=tg_entities, link_preview_options=LinkPreviewOptions(is_disabled=True))

        _user_last_channel[callback.from_user.id] = channel_idx

        _log.info(f"[ADMIN] Successfully published to channel {chat_id}")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("✅ Опубликовано!")
        await state.clear()

    except Exception as e:
        _log.error(f"[ADMIN] Publish error: {e}", exc_info=True)
        await callback.message.answer(f"Ошибка публикации: {e}")

# --- РУЧНОЕ РЕДАКТИРОВАНИЕ ---

@admin_router.message(StateFilter(PostState.waiting_for_correction))
async def on_manual_text(message: Message, state: FSMContext, bot: Bot):
    new_text = message.text or ""

    # Preserve ALL entities from user's message (not just text_link)
    new_entities = []
    if message.entities:
        for entity in message.entities:
            entity_dict = {
                "offset": entity.offset,
                "length": entity.length,
                "type": entity.type
            }
            if entity.url:
                entity_dict["url"] = entity.url
            new_entities.append(entity_dict)

    await state.update_data(generated_text=new_text, generated_entities=new_entities)

    # Пытаемся удалить сообщение пользователя с правкой (для чистоты)
    try:
        await message.delete()
    except Exception:
        pass

    # Возвращаем новое превью
    await send_preview(message, state, new_text, is_new=True)