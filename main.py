import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
import google.genai as genai

# --- ПРИМЕР ПРОМТА ---
SYSTEM_INSTRUCTION = """
Ты — элитный технический секретарь для IT-студента и Пентестера. Твоя задача — структурировать входящий поток информации в идеальную заметку формата Markdown для Obsidian.

ТВОИ ПРАВИЛА:
1.  **Формат:** Только чистый Markdown.
2.  **Структура:**
    * Заголовок H1 (#) с краткой сутью.
    * Краткое резюме (TL;DR) курсивом.
    * Основной контент (H2, H3).
    * Код всегда в блоках (```python, ```bash).
3.  **Стилизация:** Используй Callouts (> [!INFO], > [!WARNING] для опасных команд).
4.  **Авто-тегирование:** В конце заметки (#pentesting, #homelab, #python, #inbox/gemini).
5.  **Контекст:** Flipper Zero, HackRF, RPi 5, Linux, Python.
"""

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = "8389852577:AAFnywdSVkkwQ5-ZQ--IoFFY9ybApJ86FSo"
GEMINI_KEY = "AIzaSyD9p6aUx9y8PMugOhPW-5H0HoOY945g10M"

# Путь (На Linux RPi путь должен быть полным, например /home/pi/...)
OBSIDIAN_INBOX_PATH = "/home/pi/Obsidian/nosort" 
# Если тестируешь на Windows, раскомментируй строку ниже:
# OBSIDIAN_INBOX_PATH = "Obsidian_Inbox"

# Время ожидания следующего сообщения (в секундах)
COLLECTION_DELAY = 2.5 

# --- ИНИЦИАЛИЗАЦИЯ ---
client = genai.Client(api_key=GEMINI_KEY)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Словари для буферизации
user_buffers = {}      # {user_id: [text1, text2, ...]}
processing_tasks = {}  # {user_id: Task}

# --- ЛОГИКА ОБРАБОТКИ БУФЕРА ---
async def process_buffered_messages(chat_id: int, user_id: int):
    """Функция, которая запускается после таймера и обрабатывает накопленный текст."""
    await asyncio.sleep(COLLECTION_DELAY)
    
    # Если есть новые сообщения, таймер был бы сброшен, и мы бы сюда не дошли
    # (так как задача была бы отменена). Если мы здесь — поток закончился.
    
    if user_id not in user_buffers or not user_buffers[user_id]:
        return

    # 1. Склеиваем сообщения
    full_text = "\n\n".join(user_buffers[user_id])
    # Очищаем буфер сразу
    del user_buffers[user_id]
    del processing_tasks[user_id]

    # Отправляем статусное сообщение
    status_msg = await bot.send_message(chat_id, "⏳ Данные приняты. Структурирую заметку...")

    try:
        loop = asyncio.get_running_loop()
        
        # 2. Запрос в Gemini (Асинхронная обертка)
        response = await loop.run_in_executor(
            None, 
            lambda: client.models.generate_content(
                model="gemini-1.5-flash", # Используем стабильную модель
                contents=full_text,
                config={"system_instruction": SYSTEM_INSTRUCTION}
            )
        )

        formatted_note = response.text
        
        # 3. Генерация файла
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        # Берем заголовок из первых символов полного текста
        safe_title = "".join([c for c in full_text[:20] if c.isalnum() or c in (' ', '_', '-')]).strip().replace(" ", "_")
        filename = f"Gemini_{timestamp}_{safe_title}.md"
        
        # Создаем папку, если нет
        os.makedirs(OBSIDIAN_INBOX_PATH, exist_ok=True)
        filepath = os.path.join(OBSIDIAN_INBOX_PATH, filename)
        
        # 4. Сохранение
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_note)
            
        await status_msg.edit_text(f"✅ Заметка сохранена: `{filename}`\n(Объединено сообщений: {full_text.count(chr(10)*2) + 1})")
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")


# --- ХЕНДЛЕРЫ ---

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # 1. Инициализируем буфер для пользователя
    if user_id not in user_buffers:
        user_buffers[user_id] = []
    
    # 2. Добавляем текст в буфер
    user_buffers[user_id].append(message.text)
    
    # 3. Отменяем предыдущий таймер, если он был (сброс таймера)
    if user_id in processing_tasks:
        processing_tasks[user_id].cancel()
    
    # 4. Запускаем новый таймер
    processing_tasks[user_id] = asyncio.create_task(
        process_buffered_messages(chat_id, user_id)
    )

@dp.message(F.photo)
async def handle_photo(message: Message):
    await message.answer("📸 Фото пока не поддерживается в режиме склейки сообщений.")

# --- ЗАПУСК ---
async def main():
    # Удаляем вебхуки на всякий случай и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")