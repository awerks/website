import hashlib
import hmac
from os import getenv
from flask import abort, redirect, request, session, url_for
from functools import wraps
from flask_dance.contrib.google import make_google_blueprint

FLASK_API_TOKEN = getenv("FLASK_API_TOKEN", "dev)")
# GOOGLE_CLIENT_ID = getenv("GOOGLE_CLIENT_ID")
# GOOGLE_CLIENT_SECRET = getenv("GOOGLE_CLIENT_SECRET")

# google_bp = make_google_blueprint(
#     client_id=GOOGLE_CLIENT_ID,
#     client_secret=GOOGLE_CLIENT_SECRET,
#     scope=["profile", "email"],
#     redirect_url="/google_login",
# )


def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if token != FLASK_API_TOKEN:
            abort(401)
        return f(*args, **kwargs)

    return decorated


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def verify_telegram_auth(data, bot_token):
    received_hash = data.pop("hash")

    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))

    secret_key = hashlib.sha256(bot_token.encode()).digest()

    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    return computed_hash == received_hash
