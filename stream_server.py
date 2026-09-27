#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_server.py — خادم MTProto للبث المباشر من Telegram
مع معالجة تلقائية لانتهاء صلاحية file_reference
"""

import os
import re
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pyrogram import Client
from pyrogram.file_id import FileId
from pyrogram.raw.functions.upload import GetFile
from pyrogram.raw.types import InputDocumentFileLocation, InputPhotoFileLocation
from pyrogram.errors import FileReferenceExpired

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "").strip()
STRING_SESSION = os.environ.get("STRING_SESSION", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL", "").strip()  # ★ قناة المصدر للتحديث

if not all([API_ID, API_HASH, STRING_SESSION]):
    print("❌ متغيرات ناقصة: API_ID, API_HASH, STRING_SESSION")
    raise SystemExit(1)

# ═══════════════════════════════════════════════════════════════
# MTProto Client
# ═══════════════════════════════════════════════════════════════
client = Client(
    "stream_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    in_memory=True,
    workers=4,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting MTProto client...")
    await client.start()
    me = await client.get_me()
    print(f"✅ MTProto client started as @{me.username or me.id}")
    yield
    print("👋 Stopping MTProto client...")
    await client.stop()
    print("✅ Stopped")

app = FastAPI(title="Telegram Stream Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["Range", "Content-Type", "Accept", "Origin"],
    expose_headers=["Content-Length", "Content-Range", "Accept-Ranges", "Content-Type"],
    max_age=86400,
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception as e:
        print(f"❌ Unhandled error in middleware: {e}")
        traceback.print_exc()
        response = JSONResponse(
            {"error": "internal_error", "message": str(e)},
            status_code=500,
        )
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Range, Content-Type"
    response.headers["Access-Control-Expose-Headers"] = (
        "Content-Length, Content-Range, Accept-Ranges"
    )
    return response

@app.get("/")
async def root():
    return {"service": "Telegram Stream Server", "status": "ok"}

@app.get("/health")
async def health():
    return {"status": "ok"}

# ═══════════════════════════════════════════════════════════════
# ★ دالة تحديث file_reference ★
# ═══════════════════════════════════════════════════════════════
async def refresh_file_id(original_fid: str, message_id: int) -> str:
    """
    يجلب file_id جديد من Telegram عند انتهاء صلاحية المرجع.
    """
    if not CHANNEL_ID or not message_id:
        print("⚠️ Cannot refresh: CHANNEL or message_id missing")
        return original_fid

    try:
        print(f"🔄 Refreshing file_id for message {message_id}...")
        # جلب الرسالة من جديد
        messages = await client.get_messages(CHANNEL_ID, message_ids=message_id)
        if not messages or not messages.media:
            print("❌ Message or media not found")
            return original_fid

        # استخراج file_id الجديد
        new_fid = ""
        if messages.video:
            new_fid = messages.video.file_id
        elif messages.document:
            new_fid = messages.document.file_id
        elif messages.audio:
            new_fid = messages.audio.file_id
        elif messages.animation:
            new_fid = messages.animation.file_id

        if new_fid:
            print(f"✅ Refreshed: {new_fid[:30]}...")
            return new_fid
        else:
            print("❌ No media found in message")
            return original_fid

    except Exception as e:
        print(f"❌ Refresh failed: {e}")
        return original_fid

# ═══════════════════════════════════════════════════════════════
# ★ دالة بناء Location ★
# ═══════════════════════════════════════════════════════════════
def build_location(file_id):
    ft = file_id.file_type
    ft_str = str(ft).lower()

    DOC_TYPES = {
        "video", "document", "audio", "animation", "gif",
        "voice", "sticker", "secure",
        "3", "4", "5", "6", "7", "8", "9",
    }
    PHOTO_TYPES = {"photo", "profile_photo", "thumbnail", "0", "1", "2"}

    if ft_str in DOC_TYPES:
        return InputDocumentFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size="",
        )
    elif ft_str in PHOTO_TYPES:
        return InputPhotoFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size="",
        )
    else:
        print(f"⚠️ Unknown file_type: {ft} — defaulting to document")
        return InputDocumentFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size="",
        )

# ═══════════════════════════════════════════════════════════════
# ★ Endpoint البث ★
# ═══════════════════════════════════════════════════════════════
@app.head("/stream")
@app.get("/stream")
async def stream(request: Request, fid: str, size: int = 0, mid: int = 0):
    """
    بث ملف عبر MTProto مع دعم Range Requests.
    """
    if not fid:
        raise HTTPException(400, "missing fid parameter")

    # ─── 1) فك تشفير file_id ───
    try:
        file_id = FileId.decode(fid)
    except Exception as e:
        print(f"❌ FileId.decode failed: {e}")
        raise HTTPException(400, f"invalid file_id: {e}")

    # ─── 2) الحجم ───
    file_size = size
    if not file_size or file_size <= 0:
        raise HTTPException(400, "missing or invalid 'size' parameter")

    print(f"📥 Stream: type={file_id.file_type}, size={file_size / 1024 / 1024:.1f}MB, mid={mid}")

    # ─── 3) Range ───
    range_header = request.headers.get("range")
    start, end = 0, file_size - 1

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            if start > end or end >= file_size:
                raise HTTPException(416, "range not satisfiable")

    length = end - start + 1

    # ─── 4) بناء Location ───
    location = build_location(file_id)

    # ─── 5) مولّد البث مع معالجة الأخطاء ★ ───
    CHUNK_SIZE = 1024 * 1024

    async def generate():
        nonlocal file_id, location
        offset = start
        remaining = length
        chunk_count = 0

        while remaining > 0:
            chunk = min(CHUNK_SIZE, remaining)

            try:
                result = await client.invoke(
                    GetFile(location=location, offset=offset, limit=chunk)
                )
            except FileReferenceExpired:
                print(f"🔄 FileReferenceExpired at offset {offset}, refreshing...")
                # ★ تحديث file_id وإعادة المحاولة ★
                if mid > 0:
                    new_fid = await refresh_file_id(fid, mid)
                    if new_fid != fid:
                        file_id = FileId.decode(new_fid)
                        location = build_location(file_id)
                        # إعادة المحاولة
                        continue
                print("❌ Refresh failed, aborting")
                break
            except Exception as e:
                print(f"⚠️ Chunk error at offset {offset}: {e}")
                traceback.print_exc()
                break

            data = result.bytes
            if not data:
                break

            yield data
            offset += len(data)
            remaining -= len(data)
            chunk_count += 1
            if chunk_count % 10 == 0:
                print(f"   ... sent {offset / 1024 / 1024:.1f}MB")

    # ─── 6) الترويسات ───
    mime_type = getattr(file_id, "mime_type", None) or "video/mp4"

    headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "public, max-age=86400",
    }

    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(generate(), status_code=206, headers=headers)

    return StreamingResponse(generate(), headers=headers)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"❌ Unhandled exception: {exc}")
    traceback.print_exc()
    return JSONResponse(
        {"error": "internal_error", "message": str(exc)},
        status_code=500,
        headers={"Access-Control-Allow-Origin": "*"},
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Starting Telegram Stream Server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info", access_log=True)
