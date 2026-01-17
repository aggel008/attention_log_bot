import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from config import Config, load_config
from services.gpt import GPTService
from utils.states import PostState

admin_router = Router()

def final_fix(text):
    # Убираем все звездочки, если они вдруг пролезли
    text = text.replace("*", "")
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

# --- ЛОГИКА ---

# ИСПРАВЛЕНИЕ: Теперь мы загружаем реальный ID через load_config().admin_id
@admin_router.message(F.forward_origin, F.from_user.id == load_config().admin_id)
async def handle_forward(message: Message, state: FSMContext, bot: Bot, config: Config, gpt: GPTService, album: list[Message] = None):
    """Принимаем форвард (одиночный или альбом)"""
    
    # 1. Достаем текст и медиа
    original_text = message.caption or message.text or ""
    
    # Если это альбом
    if album:
        media_group = []
        for msg in album:
            if msg.photo:
                media_group.append({"type": "photo", "media": msg.photo[-1].file_id})
            # Видео пока пропускаем для простоты, или берем превью, если нужно
        
        # Берем текст из первого сообщения альбома, если он там есть
        if not original_text and album[0].caption:
            original_text = album[0].caption
            
        await state.update_data(media_group=media_group, is_album=True)
    else:
        # Одиночное медиа или текст
        if message.photo:
            await state.update_data(media_type="photo", file_id=message.photo[-1].file_id, is_album=False)
        elif message.video:
            await state.update_data(media_type="video", file_id=message.video.file_id, is_album=False)
        else:
            await state.update_data(media_type="text", is_album=False)

    # 2. Информируем админа (Индикатор работы)
    processing_msg = await message.answer("⏳ Processing...")

    # 3. Генерируем
    generated_text = await gpt.generate_content(original_text)
    
    # Очистка (Post-processing)
    generated_text = final_fix(generated_text)
    
    # 4. Сохраняем в FSM
    await state.update_data(generated_text=generated_text, original_text=original_text)
    
    # 5. Показываем превью
    await processing_msg.delete()
    await send_preview(message, state, generated_text, is_new=True)

async def send_preview(message: Message, state: FSMContext, text: str, is_new: bool = False):
    """Отправляет превью поста админу"""
    data = await state.get_data()
    
    if is_new:
        if data.get("is_album") and data.get("media_group"):
            # Для альбома показываем первое фото как превью
            first_media = data["media_group"][0]
            await message.answer_photo(first_media["media"], caption=f"[ALBUM] {text}", reply_markup=get_action_keyboard())
        elif data.get("media_type") == "photo":
            await message.answer_photo(photo=data["file_id"], caption=text, reply_markup=get_action_keyboard())
        elif data.get("media_type") == "video":
            await message.answer_video(video=data["file_id"], caption=text, reply_markup=get_action_keyboard())
        else:
            # Если текст пустой, заменяем на плейсхолдер, иначе Telegram вернет ошибку
            msg_text = text if text else "⚠️ (Нет текста)"
            await message.answer(msg_text, reply_markup=get_action_keyboard())
    else:
        # Рекурсивно вызываем is_new=True, чтобы отправить свежее сообщение
        await send_preview(message, state, text, is_new=True)
    
    await state.set_state(PostState.viewing_preview)

# --- КНОПКИ ---

@admin_router.callback_query(F.data == "regen", StateFilter(PostState.viewing_preview))
async def on_regen(callback: CallbackQuery, state: FSMContext, gpt: GPTService):
    # Убираем кнопки, чтобы показать процесс
    await callback.message.edit_reply_markup(reply_markup=None)
    
    data = await state.get_data()
    new_text = await gpt.generate_content(data["original_text"])
    
    # Очистка (Post-processing)
    new_text = final_fix(new_text)
    
    await state.update_data(generated_text=new_text)
    
    await callback.message.delete()
    await send_preview(callback.message, state, new_text, is_new=True)

@admin_router.callback_query(F.data == "edit_manual", StateFilter(PostState.viewing_preview))
async def on_edit_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Пришли мне новый текст поста:")
    # Запоминаем ID сообщения превью, чтобы потом попытаться его обновить (опционально)
    await state.update_data(preview_message_id=callback.message.message_id)
    await state.set_state(PostState.waiting_for_correction)
    await callback.answer()

@admin_router.callback_query(F.data == "delete", StateFilter(PostState.viewing_preview))
async def on_delete(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.clear()
    await callback.answer("Отменено")

@admin_router.callback_query(F.data == "publish", StateFilter(PostState.viewing_preview))
async def on_publish(callback: CallbackQuery, state: FSMContext, bot: Bot, config: Config):
    data = await state.get_data()
    text = data["generated_text"]
    chat_id = config.channel_id
    
    try:
        if data.get("is_album") and data.get("media_group"):
            media = []
            for i, item in enumerate(data["media_group"]):
                caption = text if i == 0 else None
                media.append(InputMediaPhoto(media=item["media"], caption=caption))
            await bot.send_media_group(chat_id=chat_id, media=media)
        
        elif data.get("media_type") == "photo":
            await bot.send_photo(chat_id=chat_id, photo=data["file_id"], caption=text)
            
        elif data.get("media_type") == "video":
            await bot.send_video(chat_id=chat_id, video=data["file_id"], caption=text)
            
        else:
            if not text:
                await callback.answer("❌ Ошибка: текст пустой, нечего публиковать!", show_alert=True)
                return
            await bot.send_message(chat_id=chat_id, text=text)
            
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("✅ Опубликовано!")
        await state.clear()
        
    except Exception as e:
        await callback.message.answer(f"Ошибка публикации: {e}")

# --- РУЧНОЕ РЕДАКТИРОВАНИЕ ---

@admin_router.message(StateFilter(PostState.waiting_for_correction))
async def on_manual_text(message: Message, state: FSMContext, bot: Bot):
    new_text = message.text
    await state.update_data(generated_text=new_text)
    
    # Пытаемся удалить сообщение пользователя с правкой (для чистоты)
    try:
        await message.delete()
    except:
        pass
    
    # Возвращаем новое превью
    await send_preview(message, state, new_text, is_new=True)