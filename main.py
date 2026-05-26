"""
Viral Video — Telegram Mini App Backend
FastAPI + SQLAlchemy | SQLite (dev) / PostgreSQL (prod)
"""

import os
import uuid
import asyncio
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean,
    DateTime, ForeignKey, Text, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship


# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./viral_video.db"
)

# Render gives postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class Video(Base):
    __tablename__ = "videos"

    id          = Column(Integer, primary_key=True, index=True)
    unique_id   = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    title       = Column(String(255), nullable=False)
    image_url   = Column(Text, nullable=False)
    video_url   = Column(Text, nullable=False)
    ads_required = Column(Integer, default=5)
    created_at  = Column(DateTime, default=datetime.utcnow)

    progress = relationship("UserProgress", back_populates="video", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id            = Column(Integer, primary_key=True, index=True)
    title         = Column(String(255), nullable=False)
    image_url     = Column(Text, nullable=False)
    redirect_link = Column(Text, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)


class UserProgress(Base):
    __tablename__ = "user_progress"

    id              = Column(Integer, primary_key=True, index=True)
    telegram_user_id = Column(String(50), nullable=False, index=True)
    video_id        = Column(Integer, ForeignKey("videos.id"), nullable=False)
    ads_watched     = Column(Integer, default=0)
    unlocked        = Column(Boolean, default=False)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    video = relationship("Video", back_populates="progress")


# ─────────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────────

class VideoCreate(BaseModel):
    title: str
    image_url: str
    video_url: str
    ads_required: int = 5

class VideoUpdate(BaseModel):
    title: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    ads_required: Optional[int] = None

class VideoOut(BaseModel):
    id: int
    unique_id: str
    title: str
    image_url: str
    video_url: str
    ads_required: int
    created_at: datetime

    class Config:
        from_attributes = True

class TaskCreate(BaseModel):
    title: str
    image_url: str
    redirect_link: str

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    image_url: Optional[str] = None
    redirect_link: Optional[str] = None

class TaskOut(BaseModel):
    id: int
    title: str
    image_url: str
    redirect_link: str
    created_at: datetime

    class Config:
        from_attributes = True

class ProgressUpdate(BaseModel):
    telegram_user_id: str
    video_id: int
    ads_watched: int

class ProgressOut(BaseModel):
    video_id: int
    ads_watched: int
    unlocked: bool

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# APP INIT
# ─────────────────────────────────────────────

app = FastAPI(title="Viral Video API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="public")


# ─────────────────────────────────────────────
# DB DEPENDENCY + INIT
# ─────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_demo_data(db: Session):
    """Insert demo videos and tasks if tables are empty."""
    if db.query(Video).count() == 0:
        demo_videos = [
            Video(
                unique_id=str(uuid.uuid4()),
                title="Top 10 Life Hacks You Wish You Knew Sooner",
                image_url="https://images.unsplash.com/photo-1611532736597-de2d4265fba3?w=600&q=80",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                ads_required=3,
            ),
            Video(
                unique_id=str(uuid.uuid4()),
                title="Insane Drone Footage: World's Most Beautiful Places",
                image_url="https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=600&q=80",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                ads_required=5,
            ),
            Video(
                unique_id=str(uuid.uuid4()),
                title="Street Food Tour: Bangkok's Hidden Gems",
                image_url="https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600&q=80",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                ads_required=4,
            ),
            Video(
                unique_id=str(uuid.uuid4()),
                title="Extreme Sports Compilation 2024 — Jaw Dropping Moments",
                image_url="https://images.unsplash.com/photo-1519003722824-194d4455a60c?w=600&q=80",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                ads_required=5,
            ),
        ]
        db.add_all(demo_videos)

    if db.query(Task).count() == 0:
        demo_tasks = [
            Task(
                title="Join Our Telegram Channel",
                image_url="https://images.unsplash.com/photo-1611746872915-64382b5c76da?w=600&q=80",
                redirect_link="https://t.me/klyntixelite",
            ),
            Task(
                title="Follow Us on Instagram",
                image_url="https://images.unsplash.com/photo-1611162617474-5b21e879e113?w=600&q=80",
                redirect_link="https://instagram.com",
            ),
            Task(
                title="Subscribe on YouTube",
                image_url="https://images.unsplash.com/photo-1611162616305-c69b3fa7fbe0?w=600&q=80",
                redirect_link="https://youtube.com",
            ),
        ]
        db.add_all(demo_tasks)

    db.commit()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()


# ─────────────────────────────────────────────
# FRONTEND ROUTE
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ─────────────────────────────────────────────
# VIDEO ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/api/videos", response_model=List[VideoOut])
def list_videos(db: Session = Depends(get_db)):
    return db.query(Video).order_by(Video.created_at.desc()).all()


@app.get("/api/video/{unique_id}", response_model=VideoOut)
def get_video_by_uid(unique_id: str, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.unique_id == unique_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@app.post("/api/videos", response_model=VideoOut, status_code=201)
def create_video(payload: VideoCreate, db: Session = Depends(get_db)):
    video = Video(
        unique_id=str(uuid.uuid4()),
        title=payload.title,
        image_url=payload.image_url,
        video_url=payload.video_url,
        ads_required=payload.ads_required,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@app.put("/api/videos/{video_id}", response_model=VideoOut)
def update_video(video_id: int, payload: VideoUpdate, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(video, field, value)
    db.commit()
    db.refresh(video)
    return video


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    db.delete(video)
    db.commit()
    return {"deleted": True, "id": video_id}


# ─────────────────────────────────────────────
# TASK ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/api/tasks", response_model=List[TaskOut])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(Task).order_by(Task.created_at.desc()).all()


@app.post("/api/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.put("/api/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"deleted": True, "id": task_id}


# ─────────────────────────────────────────────
# PROGRESS ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/api/progress", response_model=ProgressOut)
def update_progress(payload: ProgressUpdate, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == payload.video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    progress = db.query(UserProgress).filter(
        UserProgress.telegram_user_id == payload.telegram_user_id,
        UserProgress.video_id == payload.video_id,
    ).first()

    if not progress:
        progress = UserProgress(
            telegram_user_id=payload.telegram_user_id,
            video_id=payload.video_id,
            ads_watched=0,
            unlocked=False,
        )
        db.add(progress)

    # Only increment if not already unlocked
    if not progress.unlocked:
        progress.ads_watched = min(payload.ads_watched, video.ads_required)
        if progress.ads_watched >= video.ads_required:
            progress.unlocked = True

    progress.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(progress)
    return progress


@app.get("/api/progress/{user_id}", response_model=List[ProgressOut])
def get_user_progress(user_id: str, db: Session = Depends(get_db)):
    return db.query(UserProgress).filter(
        UserProgress.telegram_user_id == user_id
    ).all()


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "db": "sqlite" if IS_SQLITE else "postgresql"}
