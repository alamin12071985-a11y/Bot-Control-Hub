from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
import uuid

app = FastAPI()

# Serve static files
app.mount("/public", StaticFiles(directory="public"), name="public")

# Vercel allows writing only in /tmp directory
DB_FILE = "/tmp/database.json"
ADMIN_IDS = [6040791692] # Your Telegram User ID

# --- Database Helpers ---
def load_db():
    if not os.path.exists(DB_FILE):
        initial_data = {
            "videos": [
                {
                    "id": "1",
                    "unique_id": "viral-vid-001",
                    "title": "Cinematic Ocean Waves",
                    "image_url": "https://images.unsplash.com/photo-1505118380757-91f5f5632de0?w=600&q=80",
                    "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                    "ads_required": 5
                }
            ],
            "tasks": [
                {
                    "id": "1",
                    "title": "Join Our Channel",
                    "image_url": "https://images.unsplash.com/photo-1611602660688-2d1480f9a7bb?w=600&q=80",
                    "redirect_url": "https://t.me/viralvideobot"
                }
            ],
            "stats": {
                "total_ad_views": 0
            }
        }
        with open(DB_FILE, 'w') as f:
            json.dump(initial_data, f, indent=4)
        return initial_data
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

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
    db = load_db()
    return {
        "total_videos": len(db.get("videos", [])),
        "total_tasks": len(db.get("tasks", [])),
        "total_ad_views": db.get("stats", {}).get("total_ad_views", 0)
    }

@app.post("/api/stats/ad-view")
async def increment_ad_view():
    db = load_db()
    if "stats" not in db: db["stats"] = {"total_ad_views": 0}
    db["stats"]["total_ad_views"] += 1
    save_db(db)
    return {"status": "success"}

@app.get("/api/videos")
async def get_videos():
    return load_db().get("videos", [])

@app.post("/api/videos")
async def add_video(video: VideoSchema):
    db = load_db()
    new_vid = {
        "id": str(uuid.uuid4()),
        "unique_id": f"vid-{uuid.uuid4().hex[:8]}",
        **video.dict()
    }
    db["videos"].append(new_vid)
    save_db(db)
    return new_vid

@app.put("/api/videos/{video_id}")
async def update_video(video_id: str, video: VideoSchema):
    db = load_db()
    for i, v in enumerate(db["videos"]):
        if v["id"] == video_id:
            db["videos"][i] = {**v, **video.dict()}
            save_db(db)
            return db["videos"][i]
    raise HTTPException(status_code=404, detail="Video not found")

@app.delete("/api/videos/{video_id}")
async def delete_video(video_id: str):
    db = load_db()
    db["videos"] = [v for v in db["videos"] if v["id"] != video_id]
    save_db(db)
    return {"status": "success"}

@app.get("/api/tasks")
async def get_tasks():
    return load_db().get("tasks", [])

@app.post("/api/tasks")
async def add_task(task: TaskSchema):
    db = load_db()
    new_task = {"id": str(uuid.uuid4()), **task.dict()}
    db["tasks"].append(new_task)
    save_db(db)
    return new_task

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, task: TaskSchema):
    db = load_db()
    for i, t in enumerate(db["tasks"]):
        if t["id"] == task_id:
            db["tasks"][i] = {**t, **task.dict()}
            save_db(db)
            return db["tasks"][i]
    raise HTTPException(status_code=404, detail="Task not found")

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    db = load_db()
    db["tasks"] = [t for t in db["tasks"] if t["id"] != task_id]
    save_db(db)
    return {"status": "success"}

@app.get("/api/video/{unique_id}")
async def get_video_by_uid(unique_id: str):
    db = load_db()
    for v in db["videos"]:
        if v["unique_id"] == unique_id:
            return v
    raise HTTPException(status_code=404, detail="Video not found")
