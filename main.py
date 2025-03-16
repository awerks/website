import os

from fastapi import FastAPI, Request, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from database import User, Video, get_db
from slowapi.errors import RateLimitExceeded
from rate_limiter import get_real_ip, limiter
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from utils import require_token_dependency, require_auth_dependency


FASTAPI_SECRET_KEY = os.getenv("FASTAPI_SECRET_KEY", "dev")
FASTAPI_API_TOKEN = os.getenv("FASTAPI_API_TOKEN", "dev")
MOUNT_DIRECTORY = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
production_mode = os.getenv("APP_MODE", "dev") == "production"

docs_url, redoc_url, openapi_url = (None, None, None) if production_mode else ("/docs", "/redoc", "/openapi.json")
allowed_origins = (
    ["https://captionyx.com", "https://www.captionyx.com", "https://videos.captionyx.com"] if production_mode else ["*"]
)

app = FastAPI(docs_url=docs_url, redoc_url=redoc_url, openapi_url=openapi_url, debug=not production_mode)
app.state.limiter = limiter

app.add_middleware(ProxyHeadersMiddleware)
app.add_middleware(SessionMiddleware, secret_key=FASTAPI_SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth_router)

templates = Jinja2Templates(directory="templates")


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):

    if exc.status_code == 401:
        return RedirectResponse(request.url_for("login"), status_code=302)

    error_data = {
        404: (
            "Oops! This page does not exist.",
            ["The page you're looking for might have been removed or is temporarily unavailable."],
            "error.html",
        ),
        500: (
            "Oops! Something went wrong.",
            ["The server encountered an internal error and was unable to complete your request."],
            "error.html",
        ),
        429: (
            "Rate Limit Exceeded",
            ["You are being rate limited. Please try again later."],
            "error.html",
        ),
    }
    header_message, paragraphs, template = error_data.get(
        exc.status_code, ("Error", ["An error occurred while processing your request."], "error.html")
    )
    if exc.detail:
        paragraphs.append(f"Details: {exc.detail}")
    return templates.TemplateResponse(
        template,
        {"request": request, "header_message": header_message, "paragraphs": paragraphs},
        status_code=exc.status_code,
    )


class RequestIPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = get_real_ip(request)

        print(f"[{ip}]: {request.method} {request.url}")
        response = await call_next(request)
        print(f"[{ip}]: {request.method} {request.url} - [{response.status_code}]")
        return response


app.add_middleware(RequestIPMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "header_message": "Rate Limit Exceeded",
            "paragraphs": ["You are being rate limited. Slow down your requests."],
        },
        status_code=429,
    )


@app.get("/dashboard", response_class=HTMLResponse)
@limiter.limit("20/minute")
async def dashboard(
    request: Request,
    sort_by: str = "date",
    auth: dict = Depends(require_auth_dependency),
    db: AsyncSession = Depends(get_db),
):

    user_id = request.session.get("user_id")
    first_name = request.session.get("first_name")
    username = request.session.get("username")
    photo_url = request.session.get("photo_url")    

    if app.debug:
        user_id = "631745148"
        first_name = "John"
        username = "john_doe"

    if sort_by == "duration":
        order_clause = Video.duration_min.desc()
    else:
        order_clause = Video.sent_time_utc.desc()

    query = await db.execute(select(Video).where(Video.user_id == str(user_id)).order_by(order_clause))
    videos = query.scalars().all()

    context = {
        "request": request,
        "first_name": first_name,
        "id": user_id,
        "username": username,
        "photo_url": photo_url,
        "videos": videos,
        "sort_by": sort_by,
    }
    print(f"User ID: {user_id}; First Name: {first_name}; Username: {username}; Photo URL: {photo_url}")
    return templates.TemplateResponse("dashboard.html", context)


@app.post("/add_video_page", response_class=JSONResponse)
async def add_video_page(request: Request, token: str = Depends(require_token_dependency)):
    """
    Renders a video page template with provided parameters and writes it to disk.
    Expects a JSON payload.
    """
    try:
        data = await request.json()
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
    print("Adding video page:", file_name)
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


@app.get("/about")
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
    print("Starting server")
    uvicorn.run(app, host=["::", "0.0.0.0"], port=int(os.getenv("PORT")), log_level="error")
