import time
import requests
import re
import json
import os
from vk_api import VkApi
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.upload import VkUpload

# ===== НАСТРОЙКИ =====
VK_TOKEN = "vk1.a.4SIU_KDg8HIuhb9n3WEvaxgwuTeaDtBAI2trsPn95mIj2D9oBCu21dbekBxpiBZOoDKArfgo1RNb4PROaeLZzdhhONaNOTTwSsRXJ2kSNnq2EQZLe8wRqJzF7ssGqw-jGyCR0SqmRCQ89Fj-7cEdtu7P6De7QPSnNOzy7uLObtPdvDuNVOS7tJK334piDviPw6CTIkqrNiGAtSnDpmjbmg"
AITUNNEL_API_KEY = "sk-aitunnel-EJz97YJpiOwnaObmGNjf6mU8cT2OdP8L"
# ===============================================

SYSTEM_PROMPT = (
    "Ты — ИИ-помощник по созданию видео.\n"
    "Ты помогаешь пользователю сгенерировать видео, задавая уточняющие вопросы о:\n"
    "- сцене (что показать),\n"
    "- длительности (4, 6, 8, 10 сек),\n"
    "- разрешении (480p, 720p, 1080p),\n"
    "- формате (горизонтальный, вертикальный, квадратный),\n"
    "- наличии фото-референса.\n"
    "Ты не продаёшь товары, только помогаешь с видео. Отвечай кратко и структурированно."
)

# ===== ПАРСЕР СВОБОДНОЙ РЕЧИ =====

def parse_duration(text: str):
    """Находит длительность в тексте: 4, 6, 8, 10 или 1-4."""
    text = text.lower().strip()
    
    # Прямое попадание
    if text in {"1", "2", "3", "4"}:
        return {"1": 4, "2": 6, "3": 8, "4": 10}[text]
    
    # Ищем числа в тексте
    numbers = re.findall(r'\d+', text)
    for num in numbers:
        num = int(num)
        if num in {4, 6, 8, 10}:
            return num
        elif 1 <= num <= 4:
            return {1: 4, 2: 6, 3: 8, 4: 10}[num]
    
    # Ищем слова
    if "четыре" in text or "4" in text:
        return 4
    elif "шесть" in text or "6" in text:
        return 6
    elif "восемь" in text or "8" in text:
        return 8
    elif "десять" in text or "10" in text:
        return 10
    
    return None

def parse_resolution(text: str):
    """Находит разрешение: 480, 720, 1080 или 480p/720p/1080p."""
    text = text.lower()
    
    # Прямое попадание
    if text in {"1", "2", "3"}:
        return {"1": "480p", "2": "720p", "3": "1080p"}[text]
    
    if "480" in text or "480p" in text or "четыреста" in text:
        return "480p"
    elif "720" in text or "720p" in text or "семьсот" in text:
        return "720p"
    elif "1080" in text or "1080p" in text or "тысяча" in text:
        return "1080p"
    
    return None

def parse_format(text: str):
    """Находит формат: горизонтальный, вертикальный, квадратный."""
    text = text.lower()
    
    # Прямое попадание
    if text in {"1", "2", "3"}:
        return {"1": "horizontal", "2": "vertical", "3": "square"}[text]
    
    if any(word in text for word in ["горизонт", "16:9", "широк", "горизонталь"]):
        return "horizontal"
    elif any(word in text for word in ["вертикаль", "9:16", "портрет", "вертикальн"]):
        return "vertical"
    elif any(word in text for word in ["квадрат", "1:1", "квадратн"]):
        return "square"
    
    return None

def extract_all_params(text: str):
    """Вытаскивает все параметры из текста."""
    duration = parse_duration(text)
    resolution = parse_resolution(text)
    format_type = parse_format(text)
    
    # Очищаем текст от чисел и ключевых слов, чтобы оставить только сцену
    prompt = text
    # Убираем цифры и слова-параметры
    for word in ["секунд", "сек", "с", "формат", "разрешение", "разиришение", 
                 "480", "720", "1080", "480p", "720p", "1080p",
                 "16:9", "9:16", "1:1", "горизонтальный", "вертикальный", "квадратный",
                 "горизонт", "вертикаль", "квадрат"]:
        prompt = prompt.replace(word, "")
    
    # Убираем всё, что похоже на число
    prompt = re.sub(r'\d+', '', prompt)
    
    # Убираем лишние символы и пробелы
    prompt = re.sub(r'[^\w\s.,!?-]', ' ', prompt)
    prompt = ' '.join(prompt.split()).strip()
    
    # Если промпт пустой, возвращаем None
    if not prompt or len(prompt) < 3:
        prompt = None
    
    return {
        "duration": duration,
        "resolution": resolution,
        "format": format_type,
        "prompt": prompt
    }

# ===== ФУНКЦИИ РАБОТЫ С AITUNNEL =====

def ask_aitunnel(user_msg, history=None):
    if history is None:
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
    history.append({"role": "user", "content": user_msg})

    url = "https://api.aitunnel.ru/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": history,
        "temperature": 0.7,
        "max_tokens": 600
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        history.append({"role": "assistant", "content": answer})
        return answer, history
    except Exception as e:
        return f"❌ Ошибка DeepSeek: {str(e)}", history

def generate_video(prompt_text: str, image_url: str = None, duration: int = 4, size: str = "480x480") -> str:
    """Генерирует видео с заданными параметрами."""
    url = "https://api.aitunnel.ru/v1/videos"
    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Маппинг размера с учётом формата
    size_map = {
        "480p": "480x480",
        "720p": "720x720",
        "1080p": "1080x1080"
    }
    
    # Если пришло имя разрешения, преобразуем
    if size in size_map:
        size = size_map[size]
    
    data = {
        "model": "seedance-2.0-mini",
        "prompt": prompt_text,
        "size": size,
        "duration": duration,
    }
    
    if image_url:
        data["input_references"] = [
            {
                "type": "image_url",
                "image_url": {"url": image_url}
            }
        ]

    response = requests.post(url, headers=headers, json=data, timeout=30)
    if response.status_code == 401:
        raise PermissionError("Неверный или истёкший API-ключ AITunnel. Проверьте ключ и баланс.")
    response.raise_for_status()
    job = response.json()

    for _ in range(24):
        status_response = requests.get(job["polling_url"], headers=headers, timeout=30)
        status_response.raise_for_status()
        job = status_response.json()
        if job["status"] == "completed":
            break
        elif job["status"] == "failed":
            raise RuntimeError(job.get("error", "Generation failed"))
        time.sleep(5)
    else:
        raise TimeoutError("Видео не сгенерировалось за 2 минуты")

    video_url = job["unsigned_urls"][0]
    video_response = requests.get(video_url, headers=headers, timeout=60)
    video_response.raise_for_status()

    filename = f"video_{job['id']}.mp4"
    with open(filename, "wb") as f:
        f.write(video_response.content)
    return filename

def get_photo_url_from_event(event):
    if hasattr(event, 'attachments') and event.attachments:
        for att in event.attachments:
            if att['type'] == 'photo':
                sizes = att['photo']['sizes']
                largest = max(sizes, key=lambda x: x['width'] * x['height'])
                return largest['url']
    return None

def is_video_command(text: str) -> bool:
    text_lower = text.lower().strip()
    commands = ["видео", "сделай видео", "создай видео", "сгенерируй видео", "generate video", "make video"]
    return any(text_lower.startswith(cmd) or cmd in text_lower.split()[:2] for cmd in commands)

def extract_video_prompt(text: str) -> str:
    for prefix in ["видео", "сделай видео", "создай видео", "сгенерируй видео"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text if text else ""

# ===== ОСНОВНАЯ ФУНКЦИЯ =====

def main():
    print("🔄 Подключаюсь к ВК...")
    vk_session = VkApi(token=VK_TOKEN)
    longpoll = VkLongPoll(vk_session, wait=90)
    vk = vk_session.get_api()
    upload = VkUpload(vk)
    print("✅ Бот запущен (понимает свободную речь!)")

    dialogs = {}
    video_requests = {}

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            uid = event.user_id
            text = event.text.strip() if event.text else ""
            photo_url = get_photo_url_from_event(event)

            # === КОМАНДА ВИДЕО ===
            if text and is_video_command(text):
                prompt = extract_video_prompt(text)
                
                # Пробуем вытащить все параметры из текста
                params = extract_all_params(prompt) if prompt else {"duration": None, "resolution": None, "format": None, "prompt": None}
                
                # Если есть описание и есть все параметры - сразу генерируем
                if params["prompt"] and params["duration"] and params["resolution"] and params["format"]:
                    vk.messages.send(
                        user_id=uid,
                        message=f"✅ Все параметры распознаны!\n"
                                f"📝 Сцена: {params['prompt'][:100]}...\n"
                                f"⏱ Длительность: {params['duration']} сек\n"
                                f"📐 Разрешение: {params['resolution']}\n"
                                f"🔄 Формат: {params['format']}\n"
                                f"🎬 Начинаю генерацию...",
                        random_id=0
                    )
                    
                    try:
                        final_prompt = f"{params['prompt']}, {params['format']} format"
                        video_file = generate_video(
                            final_prompt,
                            image_url=photo_url,
                            duration=params["duration"],
                            size=params["resolution"]
                        )
                        video_data = upload.video(
                            video_file=video_file,
                            name="Сгенерированное видео",
                            description=f"{final_prompt}"
                        )
                        attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
                        vk.messages.send(
                            user_id=uid,
                            message="🎬 Видео готово!",
                            attachment=attachment,
                            random_id=0
                        )
                        os.remove(video_file)
                    except Exception as e:
                        vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                    continue
                
                # Если не хватает параметров - начинаем опрос
                video_requests[uid] = {
                    "stage": "awaiting_duration" if not params["duration"] else 
                              "awaiting_resolution" if not params["resolution"] else 
                              "awaiting_format" if not params["format"] else 
                              "awaiting_prompt",
                    "prompt": params["prompt"],
                    "photo_url": photo_url,
                    "duration": params["duration"],
                    "size": params["resolution"],
                    "format": params["format"]
                }
                
                # Отправляем сообщение о недостающих параметрах
                missing = []
                if not params["duration"]:
                    missing.append("длительность")
                if not params["resolution"]:
                    missing.append("разрешение")
                if not params["format"]:
                    missing.append("формат")
                if not params["prompt"]:
                    missing.append("сцену")
                
                msg = f"📝 Чтобы создать видео, уточните: {', '.join(missing)}.\n\n"
                if not params["duration"]:
                    msg += "⏱ Длительность (4, 6, 8 или 10 секунд):\n"
                if not params["resolution"]:
                    msg += "📐 Разрешение (480p, 720p или 1080p):\n"
                if not params["format"]:
                    msg += "🔄 Формат (горизонтальный, вертикальный или квадратный):\n"
                if not params["prompt"]:
                    msg += "📝 Опишите сцену:"
                
                vk.messages.send(user_id=uid, message=msg, random_id=0)
                continue

            # === ФОТО БЕЗ КОМАНДЫ ===
            if photo_url and not text:
                vk.messages.send(
                    user_id=uid,
                    message="📸 Фото получено! Если хотите создать видео с ним, напишите 'видео [описание]'.",                    random_id=0
                )
                continue

            # === ОБРАБОТКА ЭТАПОВ ОПРОСА ===
            if uid in video_requests:
                state = video_requests[uid]
                
                # Если пришло фото - сохраняем
                if photo_url and not text:
                    state["photo_url"] = photo_url
                    vk.messages.send(
                        user_id=uid,
                        message="📸 Фото сохранено! Продолжим...",
                        random_id=0
                    )
                    continue

                # Парсим ответ пользователя
                if state["stage"] == "awaiting_prompt":
                    state["prompt"] = text
                    # Проверяем, есть ли ещё параметры в тексте
                    params = extract_all_params(text)
                    if params["duration"]:
                        state["duration"] = params["duration"]
                    if params["resolution"]:
                        state["size"] = params["resolution"]
                    if params["format"]:
                        state["format"] = params["format"]
                    
                    state["stage"] = "awaiting_duration" if not state["duration"] else \
                                    "awaiting_resolution" if not state["size"] else \
                                    "awaiting_format" if not state["format"] else \
                                    "ready"
                    
                    if state["stage"] == "ready":
                        # Все параметры есть - генерируем
                        vk.messages.send(user_id=uid, message="🎬 Все параметры получены! Начинаю генерацию...", random_id=0)
                        try:
                            final_prompt = f"{state['prompt']}, {state['format']} format"
                            video_file = generate_video(
                                final_prompt,
                                image_url=state["photo_url"],
                                duration=state["duration"],
                                size=state["size"]
                            )
                            video_data = upload.video(
                                video_file=video_file,
                                name="Сгенерированное видео",
                                description=f"{final_prompt}"
                            )
                            attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
                            vk.messages.send(
                                user_id=uid,
                                message="🎬 Видео готово!",
                                attachment=attachment,
                                random_id=0
                            )
                            os.remove(video_file)
                        except Exception as e:
                            vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                        del video_requests[uid]
                        continue
                    else:
                        # Отправляем запрос следующего параметра
                        msg = "Отлично! Теперь уточните:\n"
                        if not state["duration"]:
                            msg += "⏱ Длительность (4, 6, 8 или 10 секунд):\n"
                        elif not state["size"]:
                            msg += "📐 Разрешение (480p, 720p или 1080p):\n"
                        elif not state["format"]:
                            msg += "🔄 Формат (горизонтальный, вертикальный или квадратный):\n"
                        vk.messages.send(user_id=uid, message=msg, random_id=0)
                        continue

                if state["stage"] == "awaiting_duration":
                    duration = parse_duration(text)
                    if duration:
                        state["duration"] = duration
                        # Проверяем, не указано ли ещё что-то в тексте
                        params = extract_all_params(text)
                        if params["resolution"] and not state["size"]:
                            state["size"] = params["resolution"]
                        if params["format"] and not state["format"]:
                            state["format"] = params["format"]
                        
                        state["stage"] = "awaiting_resolution" if not state["size"] else \
                                        "awaiting_format" if not state["format"] else \
                                        "ready"
                        
                        if state["stage"] == "ready":
                            vk.messages.send(user_id=uid, message="🎬 Все параметры получены! Начинаю генерацию...", random_id=0)
                            try:
                                final_prompt = f"{state['prompt']}, {state['format']} format"
                                video_file = generate_video(
                                    final_prompt,
                                    image_url=state["photo_url"],
                                    duration=state["duration"],
                                    size=state["size"]
                                )
                                video_data = upload.video(
                                    video_file=video_file,
                                    name="Сгенерированное видео",
                                    description=f"{final_prompt}"
                                )
                                attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
                                vk.messages.send(
                                    user_id=uid,
                                    message="🎬 Видео готово!",
                                    attachment=attachment,
                                    random_id=0
                                )
                                os.remove(video_file)
                            except Exception as e:
                                vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                            del video_requests[uid]
                            continue
                        else:
                            msg = "Отлично! Теперь уточните:\n"
                            if not state["size"]:
                                msg += "📐 Разрешение (480p, 720p или 1080p):\n"
                            elif not state["format"]:
                                msg += "🔄 Формат (горизонтальный, вертикальный или квадратный):\n"
                            vk.messages.send(user_id=uid, message=msg, random_id=0)
                            continue
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="⏱ Пожалуйста, укажите длительность: 4, 6, 8 или 10 секунд.\n"
                                    "Примеры: '4 сек', '6', 'восемь'",
                            random_id=0
                        )
                        continue

                if state["stage"] == "awaiting_resolution":
                    resolution = parse_resolution(text)
                    if resolution:
                        state["size"] = resolution
                        params = extract_all_params(text)
                        if params["format"] and not state["format"]:
                            state["format"] = params["format"]
                        
                        state["stage"] = "awaiting_format" if not state["format"] else "ready"
                        
                        if state["stage"] == "ready":
                            vk.messages.send(user_id=uid, message="🎬 Все параметры получены! Начинаю генерацию...", random_id=0)
                            try:
                                final_prompt = f"{state['prompt']}, {state['format']} format"
                                video_file = generate_video(
                                    final_prompt,
                                    image_url=state["photo_url"],
                                    duration=state["duration"],
                                    size=state["size"]
                                )
                                video_data = upload.video(
                                    video_file=video_file,
                                    name="Сгенерированное видео",
                                    description=f"{final_prompt}"
                                )
                                attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
                                vk.messages.send(
                                    user_id=uid,
                                    message="🎬 Видео готово!",
                                    attachment=attachment,
                                    random_id=0
                                )
                                os.remove(video_file)
                            except Exception as e:
                                vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                            del video_requests[uid]
                            continue
                        else:
                            vk.messages.send(
                                user_id=uid,
                                message="🔄 Теперь укажите формат:\n"
                                        "горизонтальный, вертикальный или квадратный",
                                random_id=0
                            )
                            continue
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="📐 Пожалуйста, укажите разрешение: 480p, 720p или 1080p.\n"
                                    "Примеры: '480', '720p', '1080'",
                            random_id=0
                        )
                        continue

                if state["stage"] == "awaiting_format":
                    format_type = parse_format(text)
                    if format_type:
                        state["format"] = format_type
                        state["stage"] = "ready"
                        
                        vk.messages.send(user_id=uid, message="🎬 Все параметры получены! Начинаю генерацию...", random_id=0)
                        try:
                            final_prompt = f"{state['prompt']}, {state['format']} format"
                            video_file = generate_video(
                                final_prompt,
                                image_url=state["photo_url"],
                                duration=state["duration"],
                                size=state["size"]
                            )
                            video_data = upload.video(
                                video_file=video_file,
                                name="Сгенерированное видео",
                                description=f"{final_prompt}"
                            )
                            attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
                            vk.messages.send(
                                user_id=uid,
                                message="🎬 Видео готово!",
                                attachment=attachment,
                                random_id=0
                            )
                            os.remove(video_file)
                        except Exception as e:
                            vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                        del video_requests[uid]
                        continue
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="🔄 Пожалуйста, укажите формат:\n"
                                    "горизонтальный, вертикальный или квадратный\n"
                                    "Примеры: 'горизонт', 'вертикаль', 'квадрат'",
                            random_id=0
                        )
                        continue

            # === ОБЫЧНЫЙ ДИАЛОГ ===
            if uid not in dialogs:
                dialogs[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
            answer, new_history = ask_aitunnel(text, dialogs[uid])
            dialogs[uid] = new_history
            vk.messages.send(user_id=uid, message=answer, random_id=0)

if __name__ == "__main__":
    main()
