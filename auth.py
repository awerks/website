from datetime import datetime, timezone
import hashlib
import hmac
import google.oauth2.id_token
import google.auth.transport.requests

from os import getenv
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db, User, Video
from werkzeug.security import generate_password_hash, check_password_hash
from rate_limiter import limiter

FASTAPI_API_TOKEN = getenv("FASTAPI_API_TOKEN", "dev)")
BOT_TOKEN = getenv("BOT_TOKEN")
router = APIRouter(prefix="/auth", tags=["auth"])
auth_templates = Jinja2Templates(directory="templates/auth")
auth_templates.env.loader = ChoiceLoader([FileSystemLoader("templates"), FileSystemLoader("templates/auth")])


@router.post("/telegram-login")
@limiter.limit("5/minute")
async def telegram_login(request: Request, db: AsyncSession = Depends(get_db)):
    """Endpoint for Telegram login."""
    try:
        user = await request.json()
    except Exception:
        return JSONResponse({"error": "No data received"}, status_code=400)
    if not verify_telegram_auth(user.copy(), BOT_TOKEN):
        return JSONResponse({"error": "Invalid Telegram data"}, status_code=403)

    user_id = str(user.get("id"))
    username = user.get("username")
    name = user.get("first_name")
    photo_url = user.get("photo_url")

    request.session.update(
        {
            "user_id": user_id,
            "first_name": name,
            "username": username,
            "photo_url": photo_url,
        }
    )

    existing_user = await db.execute(select(User).where(User.user_id == user_id))
    if not existing_user.first():
        db.add(
            User(
                user_id=user_id,
                username=username,
                name=name,
            )
        )
        await db.commit()

    return RedirectResponse(url=request.app.url_path_for("dashboard"), status_code=302)


@router.post("/google_login")
@limiter.limit("5/minute")
async def google_login(request: Request, db: AsyncSession = Depends(get_db)):
    """Endpoint for Google login. Expects form data with a 'credential' field."""
    form_data = await request.form()
    token = form_data.get("credential")
    if not token:
        return JSONResponse({"error": "No token provided"}, status_code=400)
    try:
        request_adapter = google.auth.transport.requests.Request()
        user = google.oauth2.id_token.verify_oauth2_token(token, request_adapter)
    except Exception:
        return JSONResponse({"error": "Error decoding token"}, status_code=400)

    user_id = str(user.get("sub"))
    email = user.get("email")
    username = email.split("@")[0]
    name = user.get("given_name")
    photo_url = user.get("picture")

    # first email, if the user already registered with the same email
    existing_user = await db.execute(
        select(User.user_id).where(
            or_(
                User.email == email,
                User.user_id == user_id,
            )
        )
    )
    existing_user_id = existing_user.first()
    if not existing_user_id:
        db.add(User(user_id=user_id, username=username, name=name, email=email))
        await db.commit()

    request.session.update(
        {
            "user_id": existing_user_id or user_id,
            "first_name": name,
            "username": username,
            "photo_url": photo_url,
        }
    )

    return RedirectResponse(url=request.app.url_path_for("dashboard"), status_code=302)


@router.post("/google_register_callback", response_class=RedirectResponse)
async def google_register_callback(request: Request):
    form_data = await request.form()
    token = form_data.get("credential")
    if not token:
        return JSONResponse({"error": "No token provided"}, status_code=400)
    try:
        request_adapter = google.auth.transport.requests.Request()
        user_data = google.oauth2.id_token.verify_oauth2_token(token, request_adapter)
    except Exception as e:
        print("Error decoding token:", e)
        return JSONResponse({"error": "Error decoding token"}, status_code=400)

    request.session.update(
        {
            "google_user_id": str(user_data.get("sub")),
            "email": user_data.get("email"),
            "username": user_data.get("email").split("@")[0],
            "name": user_data.get("given_name"),
            "photo_url": user_data.get("picture"),
        }
    )

    return auth_templates.TemplateResponse("google_register.html", {"request": request})


@router.post("/google_register/complete", response_class=RedirectResponse)
@limiter.limit("5/minute")
async def finalize_google_register(request: Request, db: AsyncSession = Depends(get_db)):
    form_data = await request.form()
    password = form_data.get("password")

    google_user_id = request.session.get("google_user_id")
    if not google_user_id:
        return RedirectResponse(url=request.app.url_path_for("login"), status_code=302)

    username = request.session.get("username")
    email = request.session.get("email")
    name = request.session.get("name")

    existing_user = await db.execute(select(User).where(or_(User.username == username, User.email == email)))
    if existing_user.scalar_one_or_none():
        return auth_templates.TemplateResponse(
            "google_register.html",
            {
                "request": request,
                "error": "Username or email already exists",
                "username": username,
                "email": email,
                "name": name,
            },
        )

    new_user = User(
        user_id=google_user_id,
        username=username,
        name=name,
        email=email,
        password=generate_password_hash(password),
    )
    db.add(new_user)
    await db.commit()
    request.session.pop("google_user_id", None)
    request.session.update({"user_id": google_user_id})

    return RedirectResponse(url=request.app.url_path_for("login"), status_code=302)


@router.get("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    """Clears the session and redirects to the login page."""
    request.session.clear()
    print("Logging out user:", request.session.get("username") or request.session.get("name"))
    return RedirectResponse(url=request.app.url_path_for("login"), status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Renders the login page if the user is not authenticated."""
    if "user_id" in request.session:
        return RedirectResponse(url=request.app.url_path_for("dashboard"), status_code=302)

    return auth_templates.TemplateResponse("login.html", {"request": request})


@router.post("/login", response_class=RedirectResponse)
@limiter.limit("5/minute")
async def login_user(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles user login. Expects form data with username and password."""
    form_data = await request.form()
    username_or_email = form_data.get("username_or_email").lower()
    password = form_data.get("password")
    print("Login attempt with username or email:", username_or_email)
    print("Login attempt with password:", password)
    user = await db.execute(
        select(User).where(or_(User.username == username_or_email, User.email == username_or_email))
    )
    user = user.scalars().first()
    if not user or not check_password_hash(user.password, password):
        return auth_templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password", "username_or_email": username_or_email},
        )

    request.session.update(
        {
            "user_id": str(user.user_id),
            "first_name": user.name,
            "username": user.username,
            "email": user.email,
            # "photo_url": user.photo_url,
        }
    )
    print("Logging in", request.session.get("username") or request.session.get("name"))

    return RedirectResponse(url=request.app.url_path_for("dashboard"), status_code=302)


@router.get("/register", response_class=HTMLResponse)
async def register(request: Request):
    """Renders the registration page."""
    return auth_templates.TemplateResponse("register.html", {"request": request})


@router.post("/register", response_class=RedirectResponse)
@limiter.limit("5/minute")
async def register_user(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles user registration. Expects form data with user details."""
    form_data = await request.form()
    username = form_data.get("username").lower()
    password = form_data.get("password")
    name = form_data.get("name")
    email = form_data.get("email").lower()
    start_time_utc = datetime.now(timezone.utc)
    # check if username or email already exists
    existing_user = await db.execute(select(User).where(or_(User.username == username, User.email == email)))
    existing_user = existing_user.scalar_one_or_none()
    if existing_user:
        return auth_templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "Username or email already exists",
                "username": username,
                "email": email,
                "name": name,
            },
        )

    new_user = User(
        username=username,
        password=generate_password_hash(password),
        email=email,
        name=name,
        start_time_utc=start_time_utc,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    request.session.update(
        {
            "user_id": new_user.user_id,
            "first_name": new_user.name,
            "username": new_user.username,
            "email": new_user.email,
        }
    )
    print("Registering user:", request.session.get("username") or request.session.get("name"))
    return RedirectResponse(url=request.app.url_path_for("dashboard"), status_code=302)


@router.get("/check_username", response_class=JSONResponse)
@limiter.limit("10/minute")
async def check_username(request: Request, username: str, db: AsyncSession = Depends(get_db)):
    """Checks if a username is already taken."""
    print("Checking username:", username)
    if not username:
        return JSONResponse({"exists": False})
    user = await db.execute(select(User).where(User.username == username))
    return JSONResponse({"exists": bool(user.first())})


@router.get("/check_email", response_class=JSONResponse)
@limiter.limit("10/minute")
async def check_email(request: Request, email: str, db: AsyncSession = Depends(get_db)):
    """Checks if an email is already
    taken."""
    print("Checking email:", email)
    if not email:
        return JSONResponse({"exists": False})
    user = await db.execute(select(User).where(User.email == email))
    return JSONResponse({"exists": bool(user.first())})


def verify_telegram_auth(data: dict, bot_token: str) -> bool:
    """Verifies the integrity of Telegram login data."""
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
        raise HTTPException(
            status_code=302, detail="Not authenticated", headers={"Location": request.app.url_path_for("login")}
        )
    return request.session
