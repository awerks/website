import os

from fastapi import FastAPI, Request, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from starlette.middleware.sessions import SessionMiddleware
from auth import verify_telegram_auth, require_token_dependency, require_auth_dependency
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from database import User, Video
import google.auth.transport.requests
import google.oauth2.id_token
import logging


FASTAPI_SECRET_KEY = os.getenv("FASTAPI_SECRET_KEY", "dev")
FASTAPI_API_TOKEN = os.getenv("FASTAPI_API_TOKEN", "dev")
APP_MODE = os.getenv("APP_MODE", "dev")
MOUNT_DIRECTORY = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

from os import getenv

DATABASE_URL = getenv("DATABASE_URL") if APP_MODE == "production" else getenv("DATABASE_PUBLIC_URL")
# DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")
print("DATABASE_URL:", DATABASE_URL)


engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


docs_url = None if APP_MODE == "production" else "/docs"
redoc_url = None if APP_MODE == "production" else "/redoc"
openapi_url = None if APP_MODE == "production" else "/openapi.json"

app = FastAPI(docs_url=docs_url, redoc_url=redoc_url, openapi_url=openapi_url, debug=APP_MODE == "dev")

app.add_middleware(SessionMiddleware, secret_key=FASTAPI_SECRET_KEY)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


@app.post("/telegram-login")
async def telegram_login(request: Request):
    """Endpoint for Telegram login."""
    try:
        user = await request.json()
    except Exception:
        return JSONResponse({"error": "No data received"}, status_code=400)
    print("Received Telegram data:", user, type(user))
    verification_data = user.copy()
    if verify_telegram_auth(verification_data, BOT_TOKEN):
        request.session.update(
            {
                "user_id": str(user.get("id")),
                "first_name": user.get("first_name"),
                "username": user.get("username"),  # might be absent sometimes
                "photo_url": user.get("photo_url"),
            }
        )
        return RedirectResponse(url=app.url_path_for("dashboard"), status_code=302)
    else:
        return JSONResponse({"error": "Invalid Telegram data"}, status_code=403)


@app.post("/google_login")
async def google_login(request: Request):
    """Endpoint for Google login. Expects form data with a 'credential' field."""
    form_data = await request.form()
    token = form_data.get("credential")
    if not token:
        return JSONResponse({"error": "No token provided"}, status_code=400)
    try:
        request_adapter = google.auth.transport.requests.Request()
        user = google.oauth2.id_token.verify_oauth2_token(token, request_adapter)
        request.session.update(
            {
                "user_id": str(user.get("sub")),
                "first_name": user.get("given_name"),
                "username": user.get("email"),
                "photo_url": user.get("picture"),
            }
        )
    except Exception as e:
        print("Error decoding token:", e)
        return JSONResponse({"error": "Error decoding token"}, status_code=400)
    return RedirectResponse(url=app.url_path_for("dashboard"), status_code=302)


@app.get("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    """Clears the session and redirects to the login page."""
    request.session.clear()
    return RedirectResponse(url=app.url_path_for("login"), status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Renders the login page if the user is not authenticated."""
    if "user_id" in request.session:
        return RedirectResponse(url=app.url_path_for("dashboard"), status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    auth: str = Depends(require_auth_dependency),
    db: AsyncSession = Depends(get_db),
):

    user_id = request.session.get("user_id")
    first_name = request.session.get("first_name")
    username = request.session.get("username")
    photo_url = request.session.get("photo_url")

    if app.debug:
        print("HERE")
        user_id = "631745148"
        first_name = "John"
        username = "john_doe"
    import time

    print("User ID:", user_id)
    start_time = time.time()
    query = await db.execute(select(Video).where(Video.user_id == user_id))
    videos = query.scalars().all()
    end_time = time.time()
    print(f"Query executed in {end_time - start_time} seconds")

    context = {
        "request": request,
        "first_name": first_name,
        "id": user_id,
        "username": username,
        "photo_url": photo_url,
        "videos": videos,
    }
    return templates.TemplateResponse("dashboard.html", context)


@app.post("/add_video_page", response_class=JSONResponse)
async def add_video_page(request: Request, token: str = Depends(require_token_dependency)):
    """
    Renders a video page template with provided parameters and writes it to disk.
    Expects a JSON payload.
    """
    try:
        data = await request.json()
        print("Received data:", data)
        video_url = data.get("video_url")
        captions_url = data.get("captions_url")
        file_name = data.get("file_name")
        language_code = data.get("language_code", "en")
        language_label = data.get("language_label", "English")
        original_video_url = data.get("original_video_url")
        html_content = templates.get_template("video_template.html").render(
            request=request,
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
        print("Error writing file:", e)
        return JSONResponse({"status": 500, "error": str(e)}, status_code=500)
    return JSONResponse({"status": 200})


@app.get("/result/{name:path}", response_class=FileResponse)
async def serve_rendered_page(name: str):
    """Serves a rendered HTML page from the mounted directory."""
    file_path = os.path.join(MOUNT_DIRECTORY, f"{name}.html")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Renders the index page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/video", response_class=HTMLResponse)
async def video(request: Request):
    """Renders the video template page."""
    return templates.TemplateResponse("video_template.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    """Renders the about page."""
    return templates.TemplateResponse("about.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    """Renders the privacy policy page."""
    return templates.TemplateResponse("privacy.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    # dual stack
    uvicorn.run(app, host=["::", "0.0.0.0"], port=int(os.getenv("PORT")), log_level="error")
