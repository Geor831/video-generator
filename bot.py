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

# ===== ПАРСЕР СВОБОДНОЙ РЕЧИ =====

def parse_duration(text):
    """Находит длительность в тексте."""
    text = text.lower()
    numbers = re.findall(r'\d+', text)
    for num in numbers:
        num = int(num)
        if num in [4, 6, 8, 10]:
            return num
        elif 1 <= num <= 4:
            return {1: 4, 2: 6, 3: 8, 4: 10}[num]
    
    if "четыре" in text or "4" in text:
        return 4
    elif "шесть" in text or "6" in text:
        return 6
    elif "восемь" in text or "8" in text:
        return 8
    elif "десять" in text or "10" in text:
        return 10
    return None

def parse_resolution(text):
    """Находит разрешение."""
    text = text.lower()
    if "480" in text or "480p" in text:
        return "480p"
    elif "720" in text or "720p" in text:
        return "720p"
    elif "1080" in text or "1080p" in text:
        return "1080p"
    return None

def parse_format(text):
    """Находит формат."""
    text = text.lower()
    if any(w in text for w in ["горизонт", "16:9", "широк"]):
        return "horizontal"
    elif any(w in text for w in ["вертикаль", "9:16", "портрет"]):
        return "vertical"
    elif any(w in text for w in ["квадрат", "1:1"]):
        return "square"
    return None

def extract_prompt(text):
    """Извлекает описание сцены, убирая параметры."""
    clean = text
    for word in ["секунд", "сек", "с", "формат", "разрешение", "480", "720", "1080", 
                 "480p", "720p", "1080p", "16:9", "9:16", "1:1", "горизонтальный", 
                 "вертикальный", "квадратный", "горизонт", "вертикаль", "квадрат"]:
        clean = clean.replace(word, "")
    clean = re.sub(r'\d+', '', clean)
    clean = re.sub(r'[^\w\s.,!?-]', ' ', clean)
    clean = ' '.join(clean.split()).strip()
    return clean if len(clean) > 3 else None

# ===== ФУНКЦИЯ ПРОВЕРКИ БАЛАНСА =====

def check_balance():
    """Проверяет баланс на AITunnel."""
    url = "https://api.aitunnel.ru/v1/balance"
    headers = {"Authorization": f"Bearer {AITUNNEL_API_KEY}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("balance", 0)
    except:
        return None

# ===== ФУНКЦИЯ ГЕНЕРАЦИИ ВИДЕО =====

def generate_video(prompt, image_url=None, duration=6, size="720p"):
    """Генерирует видео."""
    url = "https://api.aitunnel.ru/v1/videos"
    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json"
    }
    
    size_map = {"480p": "480x480", "720p": "720x720", "1080p": "1080x1080"}
    size = size_map.get(size, "720x720")
    
    data = {
        "model": "seedance-2.0-mini",
        "prompt": prompt,
        "size": size,
        "duration": duration,
    }
    
    if image_url:
        data["input_references"] = [{"type": "image_url", "image_url": {"url": image_url}}]
    
    print(f"📤 Отправка запроса в AITunnel...")
    print(f"📝 Промпт: {prompt}")
    print(f"⏱ Длительность: {duration} сек")
    print(f"📐 Разрешение: {size}")
    
    response = requests.post(url, headers=headers, json=data, timeout=30)
    
    if response.status_code == 401:
        raise Exception("Неверный API-ключ AITunnel. Проверьте ключ.")
    if response.status_code == 402:
        raise Exception("Недостаточно средств на балансе AITunnel. Пополните баланс.")
    
    response.raise_for_status()
    job = response.json()
    
    if "polling_url" not in job:
        raise Exception("API не вернул polling_url")
    
    print(f"📋 ID задачи: {job.get('id')}")
    
    for i in range(30):
        print(f"⏳ Ожидание... ({i+1}/30)")
        status_response = requests.get(job["polling_url"], headers=headers, timeout=30)
        status_response.raise_for_status()
        job = status_response.json()
        
        if job["status"] == "completed":
            break
        elif job["status"] == "failed":
            raise Exception(job.get("error", "Генерация не удалась"))
        time.sleep(5)
    else:
        raise Exception("Видео не сгенерировалось за 2.5 минуты")
    
    if "unsigned_urls" not in job or not job["unsigned_urls"]:
        raise Exception("API не вернул ссылку на видео")
    
    video_url = job["unsigned_urls"][0]
    print(f"🔗 Ссылка получена, скачиваю...")
    
    video_response = requests.get(video_url, timeout=60)
    video_response.raise_for_status()
    
    filename = f"video_{job['id']}.mp4"
    with open(filename, "wb") as f:
        f.write(video_response.content)
    
    print(f"✅ Видео сохранено: {filename}")
    return filename

# ===== ФУНКЦИИ РАБОТЫ С ВК =====

def get_photo_url(event):
    """Получает URL фото из сообщения."""
    try:
        if not hasattr(event, 'attachments') or not event.attachments:
            return None
        
        for att in event.attachments:
            if isinstance(att, dict) and att.get('type') == 'photo':
                sizes = att.get('photo', {}).get('sizes', [])
                if sizes:
                    return max(sizes, key=lambda x: x.get('width', 0) * x.get('height', 0)).get('url')
            elif hasattr(att, 'type') and att.type == 'photo':
                if hasattr(att, 'photo') and hasattr(att.photo, 'sizes'):
                    sizes = att.photo.sizes
                    if sizes:
                        return max(sizes, key=lambda x: x.width * x.height).url
    except:
        pass
    return None

def send_video(vk, upload, user_id, video_file, prompt):
    """Отправляет видео в чат."""
    print(f"📤 Загрузка видео в ВК...")
    video_data = upload.video(
        video_file=video_file,
        name="Сгенерированное видео",
        description=prompt[:200]
    )
    
    attachment = f"video{video_data['owner_id']}_{video_data['video_id']}"
    
    vk.messages.send(
        user_id=user_id,
        message="🎬 Видео готово! Смотрите во вложении 👆",
        attachment=attachment,
        random_id=0
    )
    print(f"✅ Видео отправлено пользователю {user_id}")
    
    try:
        os.remove(video_file)
        print("🗑 Временный файл удалён")
    except:
        pass

# ===== ОСНОВНОЙ ЦИКЛ =====

def main():
    print("🔄 Подключаюсь к ВК...")
    
    try:
        vk_session = VkApi(token=VK_TOKEN)
        longpoll = VkLongPoll(vk_session, wait=90)
        vk = vk_session.get_api()
        upload = VkUpload(vk)
        print("✅ Бот запущен!")
        print("📝 Понимает свободную речь и отправляет видео в чат")
        print("📝 Примеры: 'ведро с овощами, 6 сек, 1080p, вертикальный'")
        print("=============================================")
    except Exception as e:
        print(f"❌ Ошибка подключения к ВК: {e}")
        return

    for event in longpoll.listen():
        try:
            if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                user_id = event.user_id
                text = event.text.strip() if event.text else ""
                photo_url = get_photo_url(event)
                
                print(f"\n📩 Сообщение от {user_id}: {text[:100] if text else '[фото]'}")
                
                # Если только фото без текста
                if photo_url and not text:
                    vk.messages.send(
                        user_id=user_id,
                        message="📸 Фото получено! Напишите описание сцены для видео.\n"
                                "Пример: 'ведро с овощами на столе, 6 секунд, 720p'",
                        random_id=0
                    )
                    continue
                
                # Если нет текста и нет фото
                if not text:
                    continue
                
                # Парсим параметры из текста
                duration = parse_duration(text)
                resolution = parse_resolution(text)
                format_type = parse_format(text)
                prompt = extract_prompt(text)
                
                # Устанавливаем значения по умолчанию
                if not duration:
                    duration = 6
                if not resolution:
                    resolution = "720p"
                if not format_type:
                    format_type = "horizontal"
                
                # Если нет описания - просим
                if not prompt:
                    vk.messages.send(
                        user_id=user_id,
                        message="📝 Я не нашёл описание сцены в тексте.\n"
                                "Напишите, что должно быть в видео:\n"
                                "Пример: 'красивый закат на море, 6 секунд, 720p'",
                        random_id=0
                    )
                    continue
                
                # Формируем финальный промпт
                final_prompt = f"{prompt}, {format_type} format"
                
                # Проверяем баланс
                balance = check_balance()
                balance_msg = ""
                if balance is not None:
                    balance_msg = f"\n💰 Баланс: {balance}"
                
                # Отправляем подтверждение
                vk.messages.send(
                    user_id=user_id,
                    message=f"✅ Распознано:\n"
                            f"📝 Сцена: {prompt[:100]}...\n"
                            f"⏱ Длительность: {duration} сек\n"
                            f"📐 Разрешение: {resolution}\n"
                            f"🔄 Формат: {format_type}{balance_msg}\n"
                            f"⏳ Начинаю генерацию видео...",
                    random_id=0
                )
                
                try:
                    video_file = generate_video(
                        final_prompt,
                        image_url=photo_url,
                        duration=duration,
                        size=resolution
                    )
                    send_video(vk, upload, user_id, video_file, final_prompt)
                except Exception as e:
                    error_msg = str(e)
                    print(f"❌ Ошибка: {error_msg}")
                    vk.messages.send(
                        user_id=user_id,
                        message=f"❌ Не удалось сгенерировать видео:\n\n"
                                f"{error_msg}\n\n"
                                f"Возможные причины:\n"
                                f"• Недостаточно средств на балансе AITunnel\n"
                                f"• Неверный API-ключ\n"
                                f"• Сервис временно недоступен\n\n"
                                f"Попробуйте позже.",
                        random_id=0
                    )
                    
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            try:
                vk.messages.send(
                    user_id=user_id if 'user_id' in locals() else 0,
                    message="❌ Произошла ошибка. Попробуйте ещё раз.",
                    random_id=0
                )
            except:
                pass

if __name__ == "__main__":
    main()
