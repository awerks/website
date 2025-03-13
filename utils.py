from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import uuid
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, Request
from database import ResetConfirmToken, User

FASTAPI_API_TOKEN = os.getenv("FASTAPI_API", "dev")
auth_templates = Jinja2Templates(directory="templates/auth")
auth_templates.env.loader = ChoiceLoader([FileSystemLoader("templates"), FileSystemLoader("templates/auth")])
email_templates = Jinja2Templates(directory="templates/email")


async def send_email(to_address, subject, html_body):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_address = smtp_username

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address

    text_part = MIMEText("Please view this email in an HTML compatible client.", "plain")
    html_part = MIMEText(html_body, "html")
    message.attach(text_part)
    message.attach(html_part)

    await aiosmtplib.send(
        message,
        hostname=smtp_server,
        port=smtp_port,
        username=smtp_username,
        password=smtp_password,
        use_tls=True,
        timeout=5,
    )


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
            status_code=401, detail="Unauthorized", headers={"Location": request.app.url_path_for("login")}
        )
    return request.session


async def process_token_email(
    request: Request,
    db: AsyncSession,
    user_id: str,
    email: str,
    token_route: str,
    email_template: str,
    link_param: str,
    subject: str,
    log_prefix: str,
    success_template: str,
    success_message: str = None,
):
    """Common helper for sending emails that include a token link."""
    print(f"{log_prefix} requested for {email})")
    reset_token = await create_reset_token(db, user_id)
    # link = str(request.url_for(token_route, token=reset_token.token)).replace("http://", "https://")
    link = request.url_for(token_route, token=reset_token.token)
    html_body = email_templates.get_template(email_template).render(request=request, **{link_param: link})
    await send_email(to_address=email, subject=subject, html_body=html_body)
    print(f"Sending {log_prefix} email to: {email}")
    return auth_templates.TemplateResponse(
        success_template, {"request": request, "message": success_message, "email": email}
    )


async def get_user_by_email(db: AsyncSession, email: str):
    """Fetch a user by email from the database."""

    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def create_reset_token(db: AsyncSession, user_id: int, hours: int = 1):
    """Create a reset token for the user."""
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    reset_token = ResetConfirmToken(token=token, user_id=user_id, expires_at=expires_at)
    db.add(reset_token)
    await db.commit()
    return reset_token


async def validate_token(db: AsyncSession, token: str):
    """Validate the token and check its expiration."""
    result = await db.execute(select(ResetConfirmToken).where(ResetConfirmToken.token == token))
    token_record = result.scalar_one_or_none()
    if not token_record or token_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None, None
    result = await db.execute(select(User).where(User.user_id == token_record.user_id))
    user = result.scalar_one_or_none()
    return token_record, user
