from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    TIMESTAMP,
    Boolean,
    text,
    ForeignKey,
)
from os import getenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

APP_MODE = getenv("APP_MODE", "dev")
DATABASE_URL = getenv("DATABASE_URL") if APP_MODE == "production" else getenv("DATABASE_PUBLIC_URL")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class User(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True, nullable=False, server_default=text("(uuid_generate_v4())::text"))
    username = Column(String)
    name = Column(String)
    email = Column(String)
    password = Column(String)
    email_confirmed = Column(Boolean, server_default=text("false"))
    start_time_utc = Column(TIMESTAMP(timezone=True))
    bot_language = Column(String, server_default=text("'en'"))
    user_font_size = Column(String, server_default=text("'default'"))
    user_font = Column(String, server_default=text("'default'"))
    user_border_style = Column(String, server_default=text("'default'"))
    default_language = Column(String, server_default=text("'default'"))
    default_resolution = Column(String, server_default=text("'default'"))
    transcribe = Column(String, server_default=text("'default'"))
    subtitle_choice = Column(String, server_default=text("'default'"))
    available_minutes = Column(Integer, server_default=text("90"))

    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")
    tokens = relationship("ResetConfirmToken", back_populates="user", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    username = Column(String)
    name = Column(String)
    result_link = Column(Text, nullable=False)
    original_video_link = Column(Text)
    sent_time_utc = Column(TIMESTAMP(timezone=True), nullable=False)
    duration_min = Column(Integer)
    resolution = Column(String)
    selected_language = Column(String)
    is_transcription = Column(Boolean)
    thumbnail_url = Column(Text)
    user = relationship("User", back_populates="videos")


class ResetConfirmToken(Base):
    __tablename__ = "reset_confirm_tokens"
    token = Column(String(36), primary_key=True, nullable=False)
    user_id = Column(String, ForeignKey("users.user_id"))
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    user = relationship("User", back_populates="tokens")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
