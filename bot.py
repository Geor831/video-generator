import time
import requests
import os
import re
from vk_api import VkApi
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.upload import VkUpload

# ===== НАСТРОЙКИ =====
VK_TOKEN = "vk1.a.4SIU_KDg8HIuhb9n3WEvaxgwuTeaDtBAI2trsPn95mIj2D9oBCu21dbekBxpiBZOoDKArfgo1RNb4PROaeLZzdhhONaNOTTwSsRXJ2kSNnq2EQZLe8wRqJzF7ssGqw-jGyCR0SqmRCQ89Fj-7cEdtu7P6De7QPSnNOzy7uLObtPdvDuNVOS7tJK334piDviPw6CTIkqrNiGAtSnDpmjbmg"
AITUNNEL_API_KEY = "sk-aitunnel-EJz97YJpiOwnaObmGNjf6mU8cT2OdP8L"
# ===============================================

def generate_video(prompt_text: str, image_url: str = None) -> str:
    """Генерирует видео по тексту и опциональному фото-референсу."""
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
    """Извлекает URL первого фото из вложения сообщения."""
    if hasattr(event, 'attachments') and event.attachments:
        for att in event.attachments:
            if att['type'] == 'photo':
                # Берём самое большое изображение
                sizes = att['photo']['sizes']
                # Сортируем по размеру и берём последний (обычно самый большой)
                largest = max(sizes, key=lambda x: x['width'] * x['height'])
                return largest['url']
    return None

def main():
    print("🔄 Подключаюсь к ВК...")
    vk_session = VkApi(token=VK_TOKEN)
    longpoll = VkLongPoll(vk_session, wait=90)
    vk = vk_session.get_api()
    upload = VkUpload(vk)
    print("✅ Бот запущен (закрытое сообщество)")

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            uid = event.user_id
            text = event.text.strip() if event.text else ""
            photo_url = get_photo_url_from_event(event)

            # Если есть фото и текст начинается с "видео"
            if photo_url and text.lower().startswith("видео"):
                prompt = text[5:].strip()
                if not prompt:
                    prompt = "Покажи этот товар в красивой обстановке, кинематографично"
                vk.messages.send(user_id=uid, message="⏳ Генерирую видео с вашим фото, подождите...", random_id=0)
                try:
                    video_file = generate_video(prompt, image_url=photo_url)
                    video_data = upload.video(
                        video_file=video_file,
                        name="Видео с товаром",
                        description=f"По запросу: {prompt}"
                    )
                    attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
                    vk.messages.send(
                        user_id=uid,
                        message="🎬 Видео с вашим товаром готово!",
                        attachment=attachment,
                        random_id=0
                    )
                    os.remove(video_file)
                except Exception as e:
                    vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                continue

            # Если только фото (без команды "видео")
            if photo_url and not text:
                vk.messages.send(
                    user_id=uid,
                    message="📸 Фото получено. Напишите 'видео [описание]' чтобы создать видео с этим товаром.",
                    random_id=0
                )
                continue

            # Если нет фото, но есть команда "видео" с текстом
            if text.lower().startswith("видео"):
                prompt = text[5:].strip()
                if not prompt:
                    prompt = "Красивый закат в горах, кинематографичный стиль"
                vk.messages.send(user_id=uid, message="⏳ Генерирую видео (без фото), подождите...", random_id=0)
                try:
                    video_file = generate_video(prompt, image_url=None)
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
                    vk.messages.send(user_id=uid, message=f"❌ Ошибка: {str(e)}", random_id=0)
                continue

            # На любое другое сообщение
            vk.messages.send(
                user_id=uid,
                message="Привет! Отправь фото товара и напиши 'видео описание' — создам видео с ним.",
                random_id=0
            )

if __name__ == "__main__":
    main()
