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

PRODUCTS = [
    {"name": "Ведро пластиковое пищевое 20 л с крышкой", "desc": "🪣 Универсальное пищевое ведро 20 л — идеально для хранения продуктов, заготовок, воды. Толстый пластик (1 кг), герметичная крышка, удобная ручка. Б/у из-под сиропа, состояние идеальное.", "price": 300.0},
    # Можно добавить другие товары, если нужно
]

SYSTEM_PROMPT = (
    "Ты — продавец-консультант интернет-магазина EVA.store.\n"
    "Ты помогаешь клиентам с выбором и оформлением заказов.\n\n"
    "У нас есть следующие товары:\n"
    + "\n".join([f"- {p['name']}: {p['price']} ₽, {p['desc']}" for p in PRODUCTS]) +
    "\n\nОтвечай кратко, дружелюбно, используй техники продаж.\n"
    "Если клиент спрашивает о товаре — дай информацию из списка.\n"
    "Если клиент хочет купить — спроси город и номер телефона.\n"
    "Если клиент пишет 'видео' — он хочет сгенерировать видео, это обработает специальная функция."
)

def ask_aitunnel(user_msg, history=None):
    """Отправляет запрос к DeepSeek через AITunnel и возвращает ответ."""
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
        return f"❌ Ошибка: {str(e)}", history

def generate_video(prompt_text: str, image_url: str = None) -> str:
    """Генерирует видео через AITunnel, возвращает путь к файлу."""
    url = "https://api.aitunnel.ru/v1/videos"
    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "seedance-2.0-mini",
        "prompt": prompt_text,
        "size": "480x480",
        "duration": 4,
    }
    if image_url:
        data["input_references"] = [
            {
                "type": "image_url",
                "image_url": {"url": image_url}
            }
        ]

    response = requests.post(url, headers=headers, json=data, timeout=30)
    response.raise_for_status()
    job = response.json()

    for _ in range(24):  # максимум 2 минуты
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
    """Извлекает URL первого фото из вложения."""
    if hasattr(event, 'attachments') and event.attachments:
        for att in event.attachments:
            if att['type'] == 'photo':
                sizes = att['photo']['sizes']
                largest = max(sizes, key=lambda x: x['width'] * x['height'])
                return largest['url']
    return None

def is_video_command(text: str) -> bool:
    """Проверяет, является ли сообщение командой на генерацию видео."""
    text_lower = text.lower().strip()
    return text_lower.startswith("видео") or text_lower.startswith("сделай видео") or "видео" in text_lower.split()[:2]

def extract_video_prompt(text: str) -> str:
    """Извлекает описание из команды видео."""
    # Удаляем ключевые слова в начале
    for prefix in ["видео", "сделай видео"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break
    # Если после удаления остался текст, используем его, иначе стандартный промпт
    return text if text else "Красивый закат в горах, кинематографичный стиль"

def main():
    print("🔄 Подключаюсь к ВК...")
    vk_session = VkApi(token=VK_TOKEN)
    longpoll = VkLongPoll(vk_session, wait=90)
    vk = vk_session.get_api()
    upload = VkUpload(vk)
    print("✅ Бот запущен (DeepSeek + видео-генератор)")

    dialogs = {}  # история для каждого пользователя

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            uid = event.user_id
            text = event.text.strip() if event.text else ""
            photo_url = get_photo_url_from_event(event)

            # Если команда на видео
            if text and is_video_command(text):
                prompt = extract_video_prompt(text)
                # Если есть фото, используем его как референс
                vk.messages.send(user_id=uid, message="⏳ Генерирую видео, подождите...", random_id=0)
                try:
                    video_file = generate_video(prompt, image_url=photo_url)
                    video_data = upload.video(
                        video_file=video_file,
                        name="Сгенерированное видео",
                        description=f"По запросу: {prompt}"
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
                    vk.messages.send(user_id=uid, message=f"❌ Ошибка при генерации видео: {str(e)}", random_id=0)
                continue

            # Если есть фото, но нет команды видео — предлагаем создать видео
            if photo_url and not text:
                vk.messages.send(
                    user_id=uid,
                    message="📸 Фото получено. Напишите 'видео [описание]' чтобы создать видео с этим товаром.",
                    random_id=0
                )
                continue

            # Иначе — обычный диалог через DeepSeek
            if uid not in dialogs:
                dialogs[uid] = [{"role": "system", "content": SYSTEM_PROMPT}]
            answer, new_history = ask_aitunnel(text, dialogs[uid])
            dialogs[uid] = new_history
            vk.messages.send(user_id=uid, message=answer, random_id=0)

if __name__ == "__main__":
    main()
