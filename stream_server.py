#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_server.py — خادم MTProto للبث المباشر من Telegram
مع CORS كامل ومعالجة أخطاء شاملة
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
CHANNEL_ID = os.environ.get("CHANNEL", "").strip()

if not all([API_ID, API_HASH, STRING_SESSION]):
    print("❌ متغيرات ناقصة: API_ID, API_HASH, STRING_SESSION")
    raise SystemExit(1)

# ★★★ قواعد Telegram: offset يجب أن يكون مضاعف 4096، limit ≤ 1MB ★★★
BLOCK_SIZE = 4096
CHUNK_SIZE = 1024 * 1024  # 1 MB (مضاعف 4096)

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
    if CHANNEL_ID:
        print(f"📺 Channel for refresh: {CHANNEL_ID}")
    yield
    print("👋 Stopping MTProto client...")
    await client.stop()
    print("✅ Stopped")


app = FastAPI(title="Telegram Stream Server", lifespan=lifespan)

# ★★★ CORS كامل ★★★
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
    """يضمن إضافة CORS headers لكل الردود بما فيها الأخطاء"""
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
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════
def _extract_file_id(msg) -> str:
    for attr in ("video", "document", "audio", "animation", "voice"):
        media = getattr(msg, attr, None)
        if media and hasattr(media, "file_id"):
            return media.file_id
    return ""


async def refresh_file_id(message_id: int) -> str:
    """يجلب file_id جديد من Telegram عند انتهاء صلاحية المرجع"""
    if not CHANNEL_ID or not message_id:
        print("⚠️ Cannot refresh: CHANNEL or message_id missing")
        return ""

    try:
        print(f"🔄 Refreshing file_id for message {message_id}...")

        try:
            msg = await client.get_messages(CHANNEL_ID, message_ids=message_id)
            if msg and msg.media:
                new_fid = _extract_file_id(msg)
                if new_fid:
                    print(f"✅ Refreshed: {new_fid[:40]}...")
                    return new_fid
        except Exception as e1:
            print(f"⚠️ get_messages failed: {e1}")

        try:
            async for msg in client.get_chat_history(CHANNEL_ID, limit=500):
                if msg.id == message_id and msg.media:
                    new_fid = _extract_file_id(msg)
                    if new_fid:
                        print(f"✅ Refreshed (history): {new_fid[:40]}...")
                        return new_fid
        except Exception as e2:
            print(f"⚠️ get_chat_history failed: {e2}")

        print("❌ All refresh methods failed")
        return ""
    except Exception as e:
        print(f"❌ Refresh failed: {e}")
        traceback.print_exc()
        return ""


def build_location(file_id):
    """يبني كائن Location المناسب حسب نوع الملف"""
    ft_str = str(file_id.file_type).lower()

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
        return InputDocumentFileLocation(
            id=file_id.media_id,
            access_hash=file_id.access_hash,
            file_reference=file_id.file_reference,
            thumb_size="",
        )


def align_down(x, alignment):
    return (x // alignment) * alignment


def align_up(x, alignment):
    return ((x + alignment - 1) // alignment) * alignment


# ═══════════════════════════════════════════════════════════════
# Endpoint البث
# ═══════════════════════════════════════════════════════════════
@app.head("/stream")
@app.get("/stream")
async def stream(request: Request, fid: str, size: int = 0, mid: int = 0):
    """بث ملف عبر MTProto مع دعم Range Requests"""

    if not fid:
        raise HTTPException(400, "missing fid parameter")

    try:
        file_id = FileId.decode(fid)
    except Exception as e:
        print(f"❌ FileId.decode failed: {e}")
        raise HTTPException(400, f"invalid file_id: {e}")

    file_size = size
    if not file_size or file_size <= 0:
        raise HTTPException(400, "missing or invalid 'size' parameter")

    # تحليل Range
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

    print(f"📥 Stream: type={file_id.file_type}, size={file_size / 1024 / 1024:.1f}MB, "
          f"range={start}-{end} ({length / 1024 / 1024:.2f}MB), mid={mid}")

    location = build_location(file_id)

    # ★★★ مولّد البث — تصفير إجباري للإزاحة ★★★
    async def generate():
        nonlocal file_id, location

        # تصفير الإزاحة إلى CHUNK_SIZE (مضاعف 4096)
        aligned_start = align_down(start, CHUNK_SIZE)
        skip = start - aligned_start

        read_offset = aligned_start
        remaining = length
        total_sent = 0
        first_read = True
        refresh_attempts = 0
        MAX_REFRESH = 3

        print(f"   ↳ aligned_start={aligned_start}, skip={skip}")

        while remaining > 0:
            try:
                result = await client.invoke(
                    GetFile(
                        location=location,
                        offset=read_offset,
                        limit=CHUNK_SIZE,
                    )
                )
            except FileReferenceExpired:
                print(f"🔄 FileReferenceExpired at offset {read_offset}")
                if refresh_attempts >= MAX_REFRESH or not mid:
                    print("❌ Cannot refresh — aborting")
                    break
                refresh_attempts += 1
                new_fid = await refresh_file_id(mid)
                if not new_fid:
                    break
                try:
                    file_id = FileId.decode(new_fid)
                    location = build_location(file_id)
                    print(f"✅ Refreshed (attempt {refresh_attempts}), retrying...")
                    continue
                except Exception as e:
                    print(f"❌ Failed to decode refreshed file_id: {e}")
                    break
            except Exception as e:
                print(f"⚠️ Chunk error at offset {read_offset} (size={CHUNK_SIZE}): {e}")
                traceback.print_exc()
                break

            data = result.bytes
            if not data:
                print(f"⚠️ Empty response at offset {read_offset}")
                break

            # تخطّي البايتات الإضافية في الكتلة الأولى
            if first_read:
                if skip > 0:
                    data = data[skip:]
                first_read = False

            # قصّ البيانات إذا تجاوزت المتبقي
            if len(data) > remaining:
                data = data[:remaining]

            yield data
            total_sent += len(data)
            read_offset += CHUNK_SIZE
            remaining -= len(data)

            if total_sent % (10 * CHUNK_SIZE) == 0:
                print(f"   ... sent {total_sent / 1024 / 1024:.1f}MB")

        if remaining > 0:
            print(f"⚠️ Stream ended early: {remaining / 1024 / 1024:.2f}MB remaining")
        else:
            print(f"✅ Stream complete: {total_sent / 1024 / 1024:.2f}MB sent")

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
    }

    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(generate(), status_code=206, headers=headers)

    headers["Content-Length"] = str(length)
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