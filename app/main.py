from __future__ import annotations

import io
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError

from . import database as db
from .config import settings, validate_production_settings
from .rate_limit import login_limiter
from .realtime import manager
from .security import SESSION_MAX_AGE, create_session, read_session, verify_password


SESSION_COOKIE = "chat_session"
ALLOWED_IMAGE_FORMATS = {"JPEG": (".jpg", "image/jpeg"), "PNG": (".png", "image/png"), "WEBP": (".webp", "image/webp")}


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_production_settings()
    db.init_db()
    yield


app = FastAPI(title="私语间", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=settings.base_dir / "app" / "static"), name="static")
templates = Jinja2Templates(directory=settings.base_dir / "app" / "templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def current_user_from_request(request: Request) -> dict | None:
    session = read_session(request.cookies.get(SESSION_COOKIE))
    if not session:
        return None
    return db.get_user(session["user_id"], session["room_id"])


def require_user(request: Request) -> dict:
    user = current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    user = current_user_from_request(request)
    if user:
        return RedirectResponse("/chat", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, room: str = Form(...), username: str = Form(...), password: str = Form(...)):
    room = room.strip().lower()
    username = username.strip()
    client_key = request.client.host if request.client else "unknown"
    if not login_limiter.allowed(client_key):
        return templates.TemplateResponse(
            request, "login.html", {"error": "尝试次数过多，请 5 分钟后再试", "room": room, "username": username}, status_code=429
        )
    user = db.authenticate(room, username)
    if not user or not verify_password(user["password_hash"], password):
        login_limiter.failed(client_key)
        return templates.TemplateResponse(
            request, "login.html", {"error": "房间、账号或密码不正确", "room": room, "username": username}, status_code=401
        )
    login_limiter.succeeded(client_key)
    response = RedirectResponse("/chat", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session(user["id"], user["room_id"]),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    user = current_user_from_request(request)
    if not user:
        return RedirectResponse("/", status_code=303)
    safe_user = {k: user[k] for k in ("id", "username", "display_name", "room_id", "room_slug", "room_name")}
    return templates.TemplateResponse(request, "chat.html", {"user": safe_user, "settings": settings})


@app.get("/api/messages")
def messages(request: Request, before: int | None = None):
    user = require_user(request)
    return {
        "items": db.list_messages(user["room_id"], before, settings.history_page_size),
        "page_size": settings.history_page_size,
    }


@app.post("/api/images")
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
    caption: str = Form(""),
    reply_to_id: int | None = Form(None),
):
    user = require_user(request)
    caption = caption.strip()[:1000]
    limit = settings.max_image_mb * 1024 * 1024
    raw = await image.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, f"图片不能超过 {settings.max_image_mb} MB")
    try:
        source = Image.open(io.BytesIO(raw))
        source.load()
        if source.format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(415, "仅支持 JPG、PNG 和 WebP 图片")
        if source.width * source.height > 40_000_000:
            raise HTTPException(413, "图片像素尺寸过大")
        extension, _ = ALLOWED_IMAGE_FORMATS[source.format]
        original_format = source.format
        source = ImageOps.exif_transpose(source)
        filename = f"{secrets.token_urlsafe(20)}{extension}"
        target = settings.upload_dir / filename
        # Re-encode to verify the file and remove metadata.
        if original_format == "JPEG":
            source.convert("RGB").save(target, "JPEG", quality=88, optimize=True)
        elif original_format == "PNG":
            source.save(target, "PNG", optimize=True)
        else:
            source.save(target, "WEBP", quality=88, method=4)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise HTTPException(415, "无法识别这张图片") from None
    message = db.create_message(
        user["room_id"], user["id"], "image", caption, filename, source.width, source.height, reply_to_id
    )
    await manager.broadcast(user["room_id"], {"type": "message", "message": message})
    return message


@app.get("/media/{filename}")
def media(request: Request, filename: str):
    user = require_user(request)
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,40}\.(jpg|png|webp)", filename):
        raise HTTPException(404)
    if not db.image_belongs_to_room(filename, user["room_id"]):
        raise HTTPException(404)
    path = settings.upload_dir / filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@app.delete("/api/messages/{message_id}")
async def delete_message(message_id: int, request: Request):
    user = require_user(request)
    deleted = db.mark_message_deleted(message_id, user["room_id"], user["id"])
    if not deleted:
        raise HTTPException(404, "消息不存在或不能删除")
    if deleted.get("image_name"):
        Path(settings.upload_dir / deleted["image_name"]).unlink(missing_ok=True)
    await manager.broadcast(user["room_id"], {"type": "deleted", "message_id": message_id})
    return JSONResponse({"ok": True})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session = read_session(websocket.cookies.get(SESSION_COOKIE))
    if not session:
        await websocket.close(code=4401)
        return
    user = db.get_user(session["user_id"], session["room_id"])
    if not user:
        await websocket.close(code=4401)
        return
    room_id, user_id = user["room_id"], user["id"]
    await manager.connect(room_id, user_id, websocket)
    await manager.broadcast(room_id, {"type": "presence", "user_ids": await manager.presence(room_id)})
    try:
        while True:
            payload = await websocket.receive_json()
            event_type = payload.get("type")
            if event_type == "message":
                content = str(payload.get("content", "")).strip()
                if not content or len(content) > 4000:
                    await websocket.send_json({"type": "error", "message": "消息应为 1–4000 个字符"})
                    continue
                reply_to = payload.get("reply_to_id")
                message = db.create_message(room_id, user_id, "text", content, reply_to_id=reply_to)
                await manager.broadcast(room_id, {"type": "message", "message": message})
            elif event_type == "typing":
                await manager.broadcast(
                    room_id,
                    {"type": "typing", "user_id": user_id, "display_name": user["display_name"], "active": bool(payload.get("active"))},
                )
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        await manager.disconnect(room_id, user_id, websocket)
        await manager.broadcast(room_id, {"type": "presence", "user_ids": await manager.presence(room_id)})
