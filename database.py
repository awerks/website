# Define the base for declarative models
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    TIMESTAMP,
    Boolean,
    ForeignKey,
)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True, nullable=False)
    username = Column(String)
    name = Column(String)
    start_time_utc = Column(TIMESTAMP)
    bot_language = Column(String)
    user_font_size = Column(String)
    user_font = Column(String)
    user_border_style = Column(String)
    default_language = Column(String)
    default_resolution = Column(String)
    transcribe = Column(String)
    subtitle_choice = Column(String)
    available_minutes = Column(Integer)

    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    username = Column(String)
    name = Column(String)
    result_link = Column(Text, nullable=False)
    original_video_link = Column(Text)
    sent_time_utc = Column(TIMESTAMP, nullable=False)
    duration_min = Column(Integer)
    resolution = Column(String)
    selected_language = Column(String)
    is_transcription = Column(Boolean)
    thumbnail_url = Column(Text)
    user = relationship("User", back_populates="videos")
