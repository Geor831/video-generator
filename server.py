from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import time
import os
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

API_KEY = "sk-aitunnel-EJz97YJpiOwnaObmGNjf6mU8cT2OdP8L"
BASE = "https://api.aitunnel.ru/v1"

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ===== РАЗМЕРЫ =====
def get_size(resolution, format):
    sizes = {
        '480p': {
            'square': '480x480',
            'vertical': '480x854',
            'horizontal': '854x480'
        },
        '720p': {
            'square': '720x720',
            'vertical': '720x1280',
            'horizontal': '1280x720'
        }
    }
    return sizes.get(resolution, {}).get(format, '720x720')

# ===== ГЕНЕРАЦИЯ =====
def generate_video(prompt, duration, size, image_urls):
    data = {
        "model": "seedance-2.0-mini",
        "prompt": prompt,
        "size": size,
        "duration": duration,
        "generate_audio": False,
        "strength": 0.95,
        "guidance_scale": 10
    }

    if image_urls:
        data["input_references"] = [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(f"{BASE}/videos", headers=headers, json=data, timeout=30)
    r.raise_for_status()
    job = r.json()

    for i in range(120):
        time.sleep(5)
        job = requests.get(job["polling_url"], headers=headers).json()
        if job["status"] == "completed":
            break
        elif job["status"] == "failed":
            raise RuntimeError(job.get("error", "Generation failed"))

    if job["status"] != "completed":
        raise RuntimeError("Видео не сгенерировалось за 10 минут")

    video_url = job["unsigned_urls"][0]
    video = requests.get(video_url, headers=headers)
    filename = os.path.join(OUTPUT_FOLDER, f"video_{job['id']}.mp4")
    with open(filename, "wb") as f:
        f.write(video.content)
    return filename

# ===== ЗАГРУЗКА ФОТО =====
def upload_photos(files):
    urls = []
    for file in files:
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        urls.append(f"http://localhost:5000/uploads/{filename}")
    return urls

# ===== ЭНДПОИНТЫ =====
@app.route('/generate', methods=['POST'])
def generate():
    try:
        prompt = request.form.get('prompt', '')
        duration = int(request.form.get('duration', 6))
        resolution = request.form.get('resolution', '720p')
        format_type = request.form.get('format', 'vertical')

        size = get_size(resolution, format_type)

        # Загружаем фото
        files = request.files.getlist('images')
        image_urls = upload_photos(files) if files else []

        # Формируем промт
        final_prompt = prompt
        if format_type == 'square':
            final_prompt += ', квадратный формат 1:1'
        elif format_type == 'vertical':
            final_prompt += ', вертикальный формат 9:16'
        else:
            final_prompt += ', горизонтальный формат 16:9'

        # Генерируем
        video_path = generate_video(final_prompt, duration, size, image_urls)

        return jsonify({
            "success": True,
            "video_url": f"/download/{os.path.basename(video_path)}"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/download/<filename>')
def download(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_file(os.path.join(UPLOAD_FOLDER, filename))

@app.route('/')
def index():
    return send_file('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)