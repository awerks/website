import hashlib
import hmac
from os import getenv
from fastapi import HTTPException, Request

FASTAPI_API_TOKEN = getenv("FASTAPI_API_TOKEN", "dev)")


def verify_telegram_auth(data: dict, bot_token: str) -> bool:
    """Verifies the integrity of Telegram login data."""
    # Remove and capture the provided hash
    received_hash = data.pop("hash")
    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return computed_hash == received_hash


def require_token_dependency(request: Request):
    """Dependency to require a valid API token in the Authorization header."""
    token = request.headers.get("Authorization")
    if token != FASTAPI_API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


def require_auth_dependency(request: Request):
    """Dependency to ensure the user is authenticated (via session)."""
    if "user_id" not in request.session:

        raise HTTPException(status_code=401, detail="Not logged in")
    return request.session
