from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiosqlite
import uuid
import os

app = FastAPI()

# Serve static files
app.mount("/public", StaticFiles(directory="public"), name="public")

DB_NAME = "viral_video.db"
ADMIN_IDS = [6040791692] # Your Telegram User ID

# --- Database Initialization ---
@app.on_event("startup")
async def startup():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                unique_id TEXT UNIQUE,
                title TEXT,
                image_url TEXT,
                video_url TEXT,
                ads_required INTEGER
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT,
                image_url TEXT,
                redirect_url TEXT
            );
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER
            );
        """)
        # Initialize stats if not present
        async with db.execute("SELECT * FROM stats WHERE key='total_ad_views'") as cursor:
            row = await cursor.fetchone()
            if not row:
                await db.execute("INSERT INTO stats (key, value) VALUES ('total_ad_views', 0)")
        await db.commit()

# --- Models ---
class VideoSchema(BaseModel):
    title: str
    image_url: str
    video_url: str
    ads_required: int

class TaskSchema(BaseModel):
    title: str
    image_url: str
    redirect_url: str

# --- Routes ---
@app.get("/")
async def read_root():
    return FileResponse('public/index.html')

@app.get("/api/admin/check/{user_id}")
async def check_admin(user_id: int):
    return {"is_admin": user_id in ADMIN_IDS}

@app.get("/api/stats")
async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT value FROM stats WHERE key='total_ad_views'") as cursor:
            stat_row = await cursor.fetchone()
            total_ads = stat_row["value"] if stat_row else 0
            
        async with db.execute("SELECT COUNT(*) as count FROM videos") as cursor:
            vid_row = await cursor.fetchone()
            total_videos = vid_row["count"]
            
        async with db.execute("SELECT COUNT(*) as count FROM tasks") as cursor:
            task_row = await cursor.fetchone()
            total_tasks = task_row["count"]
            
    return {
        "total_videos": total_videos,
        "total_tasks": total_tasks,
        "total_ad_views": total_ads
    }

@app.post("/api/stats/ad-view")
async def increment_ad_view():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE stats SET value = value + 1 WHERE key='total_ad_views'")
        await db.commit()
    return {"status": "success"}

@app.get("/api/videos")
async def get_videos():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM videos") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

@app.post("/api/videos")
async def add_video(video: VideoSchema):
    vid_id = str(uuid.uuid4())
    unique_id = f"vid-{uuid.uuid4().hex[:8]}"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO videos (id, unique_id, title, image_url, video_url, ads_required) VALUES (?, ?, ?, ?, ?, ?)",
            (vid_id, unique_id, video.title, video.image_url, video.video_url, video.ads_required)
        )
        await db.commit()
    return {**video.dict(), "id": vid_id, "unique_id": unique_id}

@app.put("/api/videos/{video_id}")
async def update_video(video_id: str, video: VideoSchema):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE videos SET title=?, image_url=?, video_url=?, ads_required=? WHERE id=?",
            (video.title, video.image_url, video.video_url, video.ads_required, video_id)
        )
        await db.commit()
    return {"status": "success"}

@app.delete("/api/videos/{video_id}")
async def delete_video(video_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM videos WHERE id=?", (video_id,))
        await db.commit()
    return {"status": "success"}

@app.get("/api/tasks")
async def get_tasks():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

@app.post("/api/tasks")
async def add_task(task: TaskSchema):
    task_id = str(uuid.uuid4())
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO tasks (id, title, image_url, redirect_url) VALUES (?, ?, ?, ?)",
            (task_id, task.title, task.image_url, task.redirect_url)
        )
        await db.commit()
    return {**task.dict(), "id": task_id}

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, task: TaskSchema):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE tasks SET title=?, image_url=?, redirect_url=? WHERE id=?",
            (task.title, task.image_url, task.redirect_url, task_id)
        )
        await db.commit()
    return {"status": "success"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.commit()
    return {"status": "success"}

@app.get("/api/video/{unique_id}")
async def get_video_by_uid(unique_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM videos WHERE unique_id=?", (unique_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
    raise HTTPException(status_code=404, detail="Video not found")
