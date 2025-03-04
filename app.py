import os
from flask import Flask, jsonify, request, send_from_directory, render_template, abort
from functools import wraps

app = Flask(__name__, static_folder="static", template_folder="templates")

FLASK_API_TOKEN = os.getenv("FLASK_API_TOKEN", "dev")


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
        language = data.get("language", "en")
        original_video_url = data.get("original_video_url")

        html_content = render_template(
            "video_template.html",
            video_url=video_url,
            captions_url=captions_url,
            original_video_url=original_video_url,
            language=language,
        )

        output_dir = "pages"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{file_name}.html")
        with open(output_path, "w") as f:
            f.write(html_content)
    except Exception as e:
        return jsonify({"status": 500, "error": str(e)})

    return jsonify({"status": 200})


@app.route("/result/<path:name>", methods=["GET"])
def serve_rendered_page(name):
    return send_from_directory("pages", f"{name}.html")


@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=os.getenv("PORT", default=5000))
