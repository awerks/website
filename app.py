import os
from flask import Flask, jsonify, request, send_from_directory, render_template, redirect, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from auth import require_token, require_auth, verify_telegram_auth
import google.auth.transport.requests
import google.oauth2.id_token

app = Flask(__name__, static_folder="static", template_folder="templates")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")

FLASK_API_TOKEN = os.getenv("FLASK_API_TOKEN", "dev")
MOUNT_DIRECTORY = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
BOT_TOKEN = os.getenv("TOKEN")


@app.route("/telegram-login", methods=["POST"])
def telegram_login():

    user = request.get_json()
    print(user)
    print(type(user))
    if not user:
        return jsonify(error="No data received"), 400

    verification_data = user.copy()

    if verify_telegram_auth(verification_data, BOT_TOKEN):
        session.update(
            {
                "user_id": user.get("id"),
                "first_name": user.get("first_name"),
                "username": user.get("username"),  # not always present
                "photo_url": user.get("photo_url"),
            }
        )
        return redirect(url_for("dashboard"))
    else:
        return jsonify(error="Invalid Telegram data"), 403


@app.route("/google_login", methods=["POST"])
def google_login():

    token = request.form.to_dict()["credential"]
    try:
        request_adapter = google.auth.transport.requests.Request()
        user = google.oauth2.id_token.verify_oauth2_token(token, request_adapter)
        session.update(
            {
                "user_id": user.get("sub"),
                "first_name": user.get("given_name"),
                "username": user.get("email"),
                "photo_url": user.get("picture"),
            }
        )
    except Exception as e:
        print("Error decoding token:", e)
        return "Error decoding token", 400

    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/login", methods=["GET"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/dashboard", methods=["GET"])
@require_auth
def dashboard():

    user_id = session.get("user_id")
    first_name = session.get("first_name")
    username = session.get("username")
    photo_url = session.get("photo_url")
    return render_template("dashboard.html", first_name=first_name, id=user_id, username=username, photo_url=photo_url)


@app.route("/add_video_page", methods=["POST"])
@require_token
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


@app.route("/about", methods=["GET"])
def about():
    return render_template("about.html")


@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=os.getenv("PORT", default=5000))
