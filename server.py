from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import re
import time
import os
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с любого сайта

AITUNNEL_API_KEY = "sk-aitunnel-EJz97YJpiOwnaObmGNjf6mU8cT2OdP8L"
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ===== ПАРСЕР =====

def parse_duration(text):
    text = text.lower()
    numbers = re.findall(r'\d+', text)
    for num in numbers:
        num = int(num)
        if num in [4, 6, 8, 10]:
            return num
    if "четыре" in text or "4" in text: return 4
    if "шесть" in text or "6" in text: return 6
    if "восемь" in text or "8" in text: return 8
    if "десять" in text or "10" in text: return 10
    return None

def parse_resolution(text):
    text = text.lower()
    if "480" in text: return "480p"
    if "720" in text: return "720p"
    if "1080" in text: return "1080p"
    return None

def parse_format(text):
    text = text.lower()
    if "горизонт" in text or "16:9" in text: return "horizontal"
    if "вертикаль" in text or "9:16" in text: return "vertical"
    if "квадрат" in text or "1:1" in text: return "square"
    return None

def extract_prompt(text):
    clean = text
    for word in ["секунд", "сек", "с", "формат", "разрешение", "480", "720", "1080", 
                 "480p", "720p", "1080p", "16:9", "9:16", "1:1", "горизонтальный", 
                 "вертикальный", "квадратный", "горизонт", "вертикаль", "квадрат"]:
        clean = clean.replace(word, "")
    clean = re.sub(r'\d+', '', clean)
    clean = re.sub(r'[^\w\s.,!?-]', ' ', clean)
    clean = ' '.join(clean.split()).strip()
    return clean if len(clean) > 3 else None

# ===== ГЕНЕРАЦИЯ ВИДЕО =====

def generate_video(prompt, image_url=None, duration=6, size="720p"):
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
    
    response = requests.post(url, headers=headers, json=data, timeout=30)
    
    if response.status_code == 401:
        raise Exception("Неверный API-ключ AITunnel")
    if response.status_code == 402:
        raise Exception("Недостаточно средств на балансе AITunnel")
    
    response.raise_for_status()
    job = response.json()
    
    if "polling_url" not in job:
        raise Exception("API не вернул polling_url")
    
    for i in range(30):
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
    video_response = requests.get(video_url, timeout=60)
    video_response.raise_for_status()
    
    filename = os.path.join(OUTPUT_FOLDER, f"video_{job['id']}.mp4")
    with open(filename, "wb") as f:
        f.write(video_response.content)
    
    return filename

# ===== ЭНДПОИНТЫ =====

@app.route('/generate', methods=['POST'])
def generate():
    try:
        text = request.form.get('prompt', '')
        duration = int(request.form.get('duration', 6))
        resolution = request.form.get('resolution', '720p')
        format_type = request.form.get('format', 'horizontal')
        
        # Парсим параметры из текста
        parsed_duration = parse_duration(text)
        parsed_resolution = parse_resolution(text)
        parsed_format = parse_format(text)
        parsed_prompt = extract_prompt(text)
        
        # Берём из текста или из формы
        final_duration = parsed_duration if parsed_duration else duration
        final_resolution = parsed_resolution if parsed_resolution else resolution
        final_format = parsed_format if parsed_format else format_type
        final_prompt = parsed_prompt if parsed_prompt else text
        
        if not final_prompt or len(final_prompt) < 3:
            return jsonify({"success": False, "error": "Не удалось извлечь описание сцены"})
        
        # Фото
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename:
                filename = secure_filename(file.filename)
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                # Для теста используем локальный путь
                # В реальности нужно загружать на сервер или использовать base64
                image_url = f"http://localhost:5000/uploads/{filename}"
        
        prompt_text = f"{final_prompt}, {final_format} format"
        
        video_path = generate_video(
            prompt_text,
            image_url=image_url,
            duration=final_duration,
            size=final_resolution
        )
        
        video_url = f"/download/{os.path.basename(video_path)}"
        
        return jsonify({
            "success": True,
            "video_url": video_url
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/download/<filename>')
def download(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

@app.route('/uploads/<filename>')
def uploads(filename):
    return send_file(os.path.join(UPLOAD_FOLDER, filename))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)