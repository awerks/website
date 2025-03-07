import os
from flask import Flask, jsonify, request, send_from_directory, render_template, abort
from functools import wraps

app = Flask(__name__, static_folder="static", template_folder="templates")

FLASK_API_TOKEN = os.getenv("FLASK_API_TOKEN", "dev")
MOUNT_DIRECTORY = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if token != FLASK_API_TOKEN:
            abort(401)
        return f(*args, **kwargs)

    return decorated


@app.route("/add_video_page", methods=["POST"])
@require_auth
def add_video_page():
    try:
        data = request.get_json()
        video_url = data.get("video_url")
        captions_url = data.get("captions_url")
        file_name = data.get("file_name")
        language_code = data.get("language_code", "en")
        language_label = data.get("language_label", "English")
        original_video_url = data.get("original_video_url")

        html_content = render_template(
            "video_template.html",
            video_url=video_url,
            captions_url=captions_url,
            original_video_url=original_video_url,
            language_code=language_code,
            language_label=language_label,
        )

        output_path = os.path.join(MOUNT_DIRECTORY, f"{file_name}.html")
        with open(output_path, "w") as f:
            f.write(html_content)
    except Exception as e:
        return jsonify({"status": 500, "error": str(e)})

    return jsonify({"status": 200})


@app.route("/result/<path:name>", methods=["GET"])
def serve_rendered_page(name):
    return send_from_directory(MOUNT_DIRECTORY, f"{name}.html")


@app.route("/", methods=["GET"])
def serve_index():
    return render_template("index.html")


@app.route("/video", methods=["GET"])
def video():
    return render_template("video_template.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=os.getenv("PORT", default=5000))
