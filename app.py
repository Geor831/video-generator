import os
import time
import uuid
import requests
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='')

# ===== НАСТРОЙКИ =====
AITUNNEL_API_KEY = os.getenv("AITUNNEL_API_KEY", "sk-aitunnel-EJz97YJpiOwnaObmGNjf6mU8cT2OdP8L")
AITUNNEL_BASE = "https://api.aitunnel.ru/v1"
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 МБ

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/upload", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "Нет файла"}), 400
    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "Пустое имя файла"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Недопустимый формат"}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    public_url = f"{request.host_url.rstrip('/')}/uploads/{filename}"
    return jsonify({"url": public_url, "filename": filename})


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    duration = int(data.get("duration", 5))
    size = data.get("size", "720x1280")
    image_urls = data.get("image_urls", [])

    if not prompt:
        return jsonify({"error": "Пустой промпт"}), 400
    if duration < 2 or duration > 10:
        return jsonify({"error": "Длительность должна быть от 2 до 10 секунд"}), 400

    payload = {
        "model": "seedance-2.0-mini",
        "prompt": prompt,
        "size": size,
        "duration": duration,
        "generate_audio": False,
    }
    if image_urls:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": url}} for url in image_urls
        ]

    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(f"{AITUNNEL_BASE}/videos", headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        job = r.json()
        return jsonify({
            "id": job.get("id"),
            "status": job.get("status", "pending"),
            "polling_url": job.get("polling_url"),
        })
    except requests.HTTPError as e:
        return jsonify({"error": f"Ошибка AITunnel: {e.response.status_code} {e.response.text[:300]}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def status():
    polling_url = request.args.get("polling_url")
    if not polling_url:
        return jsonify({"error": "Нет polling_url"}), 400

    headers = {"Authorization": f"Bearer {AITUNNEL_API_KEY}"}
    try:
        r = requests.get(polling_url, headers=headers, timeout=30)
        r.raise_for_status()
        return jsonify(r.json())
    except requests.HTTPError as e:
        return jsonify({"error": f"Ошибка AITunnel: {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["GET"])
def download():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "Нет URL"}), 400

    headers = {"Authorization": f"Bearer {AITUNNEL_API_KEY}"}
    try:
        r = requests.get(url, headers=headers, stream=True, timeout=120)
        r.raise_for_status()
        return app.response_class(
            r.iter_content(chunk_size=8192),
            content_type=r.headers.get("Content-Type", "video/mp4"),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test", methods=["GET"])
def test_api():
    headers = {"Authorization": f"Bearer {AITUNNEL_API_KEY}"}
    try:
        r = requests.get(f"{AITUNNEL_BASE}/models", headers=headers, timeout=10)
        return jsonify({"status": r.status_code, "ok": r.ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)