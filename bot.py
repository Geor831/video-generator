import time
import requests
import os
from vk_api import VkApi
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.upload import VkUpload

# ===== НАСТРОЙКИ =====
VK_TOKEN = "vk1.a.4SIU_KDg8HIuhb9n3WEvaxgwuTeaDtBAI2trsPn95mIj2D9oBCu21dbekBxpiBZOoDKArfgo1RNb4PROaeLZzdhhONaNOTTwSsRXJ2kSNnq2EQZLe8wRqJzF7ssGqw-jGyCR0SqmRCQ89Fj-7cEdtu7P6De7QPSnNOzy7uLObtPdvDuNVOS7tJK334piDviPw6CTIkqrNiGAtSnDpmjbmg"
AITUNNEL_API_KEY = "sk-aitunnel-EJz97YJpiOwnaObmGNjf6mU8cT2OdP8L"
# ===============================================

def generate_video(prompt_text: str) -> str:
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

def main():
    print("🔄 Подключаюсь к ВК...")
    vk_session = VkApi(token=VK_TOKEN)
    longpoll = VkLongPoll(vk_session, wait=90)
    vk = vk_session.get_api()
    upload = VkUpload(vk)
    print("✅ Бот запущен (для закрытого сообщества)")

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            uid = event.user_id
            text = event.text.strip()
            if not text:
                continue

            if text.lower().startswith("видео"):
                prompt = text[5:].strip()
                if not prompt:
                    prompt = "Красивый закат в горах, кинематографичный стиль"
                vk.messages.send(user_id=uid, message="⏳ Генерирую видео, подождите...", random_id=0)
                try:
                    video_file = generate_video(prompt)
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

            # Если не команда — даём подсказку
            vk.messages.send(user_id=uid, message="Привет! Напиши 'видео ...' — и я сгенерирую видео по твоему запросу.", random_id=0)

if __name__ == "__main__":
    main()
