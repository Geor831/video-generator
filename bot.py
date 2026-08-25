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
    # Маппинг размера
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
    return text_lower.startswith("видео") or text_lower.startswith("сделай видео") or "видео" in text_lower.split()[:2]

def extract_video_prompt(text: str) -> str:
    for prefix in ["видео", "сделай видео"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text if text else ""

def main():
    print("🔄 Подключаюсь к ВК...")
    vk_session = VkApi(token=VK_TOKEN)
    longpoll = VkLongPoll(vk_session, wait=90)
    vk = vk_session.get_api()
    upload = VkUpload(vk)
    print("✅ Бот запущен (видео-помощник с опросом параметров)")

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
                if prompt:
                    # Если сразу есть описание, начинаем опрос параметров
                    video_requests[uid] = {
                        "stage": "awaiting_duration",
                        "prompt": prompt,
                        "photo_url": photo_url,
                        "duration": None,
                        "size": None,
                        "format": None
                    }
                    vk.messages.send(
                        user_id=uid,
                        message=f"Отлично! Сцена: «{prompt}».\n"
                                "Теперь выберите длительность:\n"
                                "1 — 4 секунды\n"
                                "2 — 6 секунд\n"
                                "3 — 8 секунд\n"
                                "4 — 10 секунд\n"
                                "Введите номер (1–4).",
                        random_id=0
                    )
                    continue
                else:
                    # Нет описания → сначала спросим сцену
                    video_requests[uid] = {
                        "stage": "awaiting_prompt",
                        "photo_url": photo_url,
                        "duration": None,
                        "size": None,
                        "format": None,
                        "prompt": None
                    }
                    vk.messages.send(
                        user_id=uid,
                        message="🎬 Что вы хотите показать в видео? Опишите сцену, объекты, настроение.",
                        random_id=0
                    )
                    continue

            # === ФОТО БЕЗ КОМАНДЫ ===
            if photo_url and not text:
                vk.messages.send(
                    user_id=uid,
                    message="📸 Фото получено. Если хотите создать видео с ним, напишите 'видео [описание]'.",
                    random_id=0
                )
                continue

            # === ОБРАБОТКА ЭТАПОВ ОПРОСА ===
            if uid in video_requests:
                state = video_requests[uid]

                if state["stage"] == "awaiting_prompt":
                    # Сохраняем описание
                    state["prompt"] = text
                    state["stage"] = "awaiting_duration"
                    vk.messages.send(
                        user_id=uid,
                        message=f"Сцена: «{text}».\n"
                                "Теперь выберите длительность:\n"
                                "1 — 4 секунды\n"
                                "2 — 6 секунд\n"
                                "3 — 8 секунд\n"
                                "4 — 10 секунд\n"
                                "Введите номер (1–4).",
                        random_id=0
                    )
                    continue

                if state["stage"] == "awaiting_duration":
                    # Проверяем выбор длительности
                    dur_map = {"1": 4, "2": 6, "3": 8, "4": 10}
                    if text.strip() in dur_map:
                        state["duration"] = dur_map[text.strip()]
                        state["stage"] = "awaiting_resolution"
                        vk.messages.send(
                            user_id=uid,
                            message="Выберите разрешение:\n"
                                    "1 — 480p (базовое)\n"
                                    "2 — 720p (стандартное)\n"
                                    "3 — 1080p (HD)\n"
                                    "Введите номер (1–3).",
                            random_id=0
                        )
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="Пожалуйста, введите номер от 1 до 4.",
                            random_id=0
                        )
                    continue

                if state["stage"] == "awaiting_resolution":
                    res_map = {"1": "480p", "2": "720p", "3": "1080p"}
                    if text.strip() in res_map:
                        state["size"] = res_map[text.strip()]
                        state["stage"] = "awaiting_format"
                        vk.messages.send(
                            user_id=uid,
                            message="Выберите формат:\n"
                                    "1 — Горизонтальный (16:9)\n"
                                    "2 — Вертикальный (9:16, для Reels/TikTok)\n"
                                    "3 — Квадратный (1:1)\n"
                                    "Введите номер (1–3).",
                            random_id=0
                        )
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="Пожалуйста, введите номер от 1 до 3.",
                            random_id=0
                        )
                    continue

                if state["stage"] == "awaiting_format":
                    fmt_map = {"1": "horizontal", "2": "vertical", "3": "square"}
                    if text.strip() in fmt_map:
                        state["format"] = fmt_map[text.strip()]
                        # Формат влияет на разрешение: для вертикального используем 480x854 и т.п.
                        # Но для простоты оставим квадратное разрешение, а формат учтём в промпте
                        # Можно добавить в промпт указание ориентации
                        state["stage"] = "awaiting_photo"
                        vk.messages.send(
                            user_id=uid,
                            message=f"Параметры: {state['duration']} сек, {state['size']}, {state['format']}.\n"
                                    "Есть фото для референса? Отправьте фото или напишите «нет».",
                            random_id=0
                        )
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="Пожалуйста, введите номер от 1 до 3.",
                            random_id=0
                        )
                    continue

                if state["stage"] == "awaiting_photo":
                    # Проверяем, не прислал ли пользователь фото
                    if photo_url:
                        state["photo_url"] = photo_url
                        # Генерируем с фото
                        vk.messages.send(user_id=uid, message="📸 Фото получено! Генерирую видео...", random_id=0)
                        try:
                            final_prompt = f"{state['prompt']}, {state['format']} format"
                            video_file = generate_video(
                                final_prompt,
                                image_url=photo_url,
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
                        except PermissionError as e:
                            vk.messages.send(
                                user_id=uid,
                                message=f"❌ {str(e)}\nПроверьте API-ключ AITunnel.",
                                random_id=0
                            )
                        except Exception as e:
                            vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                        del video_requests[uid]
                        continue

                    if text.lower() in ["нет", "без фото", "не"]:
                        # Генерируем без фото
                        vk.messages.send(user_id=uid, message="⏳ Генерирую видео без фото...", random_id=0)
                        try:
                            final_prompt = f"{state['prompt']}, {state['format']} format"
                            video_file = generate_video(
                                final_prompt,
                                image_url=None,
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
                        except PermissionError as e:
                            vk.messages.send(
                                user_id=uid,
                                message=f"❌ {str(e)}\nПроверьте ключ AITunnel.",
                                random_id=0
                            )
                        except Exception as e:
                            vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                        del video_requests[uid]
                    else:
                        vk.messages.send(
                            user_id=uid,
                            message="Отправьте фото или напишите «нет», чтобы продолжить.",
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
