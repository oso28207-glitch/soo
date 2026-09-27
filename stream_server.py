#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_server.py — خادم MTProto للبث المباشر من Telegram
★ نسخة نهائية: offset/limit alignment إجباري ★
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

# ★★★ ثوابت Telegram ★★★
BLOCK_SIZE = 4096                          # وحدة الذرّ الأساسية
CHUNK_SIZE = 512 * 1024                    # 512 KB (آمن لجميع الأحجام)
MAX_CHUNK_SIZE = 1024 * 1024               # 1 MB (الحد الأقصى)

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
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════
def align_down(x: int, alignment: int) -> int:
    """تصفير للأسفل إلى مضاعف alignment"""
    return (x // alignment) * alignment


def align_up(x: int, alignment: int) -> int:
    """تصفير للأعلى إلى مضاعف alignment"""
    return ((x + alignment - 1) // alignment) * alignment


def extract_file_id(msg) -> str:
    for attr in ("video", "document", "audio", "animation", "voice"):
        media = getattr(msg, attr, None)
        if media and hasattr(media, "file_id"):
            return media.file_id
    return ""


async def refresh_file_id(message_id: int) -> str:
    if not CHANNEL_ID or not message_id:
        print("⚠️ Cannot refresh: CHANNEL or message_id missing")
        return ""

    try:
        print(f"🔄 Refreshing file_id for message {message_id}...")

        try:
            msg = await client.get_messages(CHANNEL_ID, message_ids=message_id)
            if msg and msg.media:
                new_fid = extract_file_id(msg)
                if new_fid:
                    print(f"✅ Refreshed: {new_fid[:40]}...")
                    return new_fid
        except Exception as e1:
            print(f"⚠️ get_messages failed: {e1}")

        try:
            async for msg in client.get_chat_history(CHANNEL_ID, limit=500):
                if msg.id == message_id and msg.media:
                    new_fid = extract_file_id(msg)
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


# ═══════════════════════════════════════════════════════════════
# ★ دالة البث المُصفّاة ★
# ═══════════════════════════════════════════════════════════════
async def read_chunk(location, offset: int, limit: int):
    """يقرأ chunk واحد من Telegram مع تصفير إجباري"""
    # تصفير الإزاحة والحجم إلى BLOCK_SIZE
    offset = align_down(offset, BLOCK_SIZE)
    limit = align_down(limit, BLOCK_SIZE)
    if limit == 0:
        limit = BLOCK_SIZE
    if limit > MAX_CHUNK_SIZE:
        limit = MAX_CHUNK_SIZE
    return await client.invoke(
        GetFile(location=location, offset=offset, limit=limit)
    )


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

    # ─── تحليل Range ───
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
          f"range={start}-{end} ({length / 1024 / 1024:.1f}MB), mid={mid}")

    location = build_location(file_id)

    # ═══════════════════════════════════════════════════════════
    # ★ مولّد البث — مع تصفير الإزاحة والحجم ★
    # ═══════════════════════════════════════════════════════════
    async def generate():
        nonlocal file_id, location

        # ★ الإزاحة الحالية لقراءة Telegram (مُصفّاة للأسفل) ★
        read_offset = align_down(start, BLOCK_SIZE)
        # ★ كم بايت يجب تخطّيها في البداية (قبل start) ★
        skip = start - read_offset
        # ★ كم بايت يجب إرسالها في النهاية ★
        remaining = length

        refresh_attempts = 0
        total_sent = 0
        MAX_REFRESH = 3

        # ★ قراءة الكتلة الأولى (تشمل البايتات المُتخطّاة) ★
        first_chunk_size = align_up(
            min(CHUNK_SIZE, remaining + skip),
            BLOCK_SIZE,
        )

        while remaining > 0:
            # حجم القراءة: بين BLOCK_SIZE و MAX_CHUNK_SIZE
            if total_sent == 0:
                # الكتلة الأولى: تحتوي على الإزاحة الكلية + البيانات المطلوبة
                read_size = first_chunk_size
            else:
                # الكتل التالية: مُصفّاة تماماً
                read_size = align_up(min(CHUNK_SIZE, remaining), BLOCK_SIZE)

            # تأكد أن القراءة لا تتجاوز حجم الملف
            if read_offset + read_size > file_size:
                read_size = file_size - read_offset
                # تصفير للأعلى (قد نقرأ بايتات إضافية قليلة)
                read_size = align_up(read_size, BLOCK_SIZE)
                if read_offset + read_size > file_size:
                    read_size = file_size - read_offset
                # إذا لم يعد قابلاً للتصفير، نقرأ المتبقي فقط (سيُقبل لأنه آخر كتلة)
                if read_size % BLOCK_SIZE != 0:
                    read_size = read_size  # آخر كتلة قد لا تكون مُصفّاة

            try:
                result = await read_chunk(location, read_offset, read_size)
            except FileReferenceExpired:
                print(f"🔄 FileReferenceExpired at offset {read_offset}")
                if refresh_attempts >= MAX_REFRESH or not mid:
                    print("❌ Cannot refresh")
                    break
                refresh_attempts += 1
                new_fid = await refresh_file_id(mid)
                if not new_fid:
                    break
                try:
                    file_id = FileId.decode(new_fid)
                    location = build_location(file_id)
                    print(f"✅ Refreshed (attempt {refresh_attempts})")
                    continue
                except Exception as e:
                    print(f"❌ Failed to decode: {e}")
                    break

            except Exception as e:
                print(f"⚠️ Chunk error at offset {read_offset} "
                      f"(size={read_size}): {e}")
                traceback.print_exc()
                break

            data = result.bytes
            if not data:
                print(f"⚠️ Empty response at offset {read_offset}")
                break

            # ─── تخطّي البايتات الإضافية في الكتلة الأولى ───
            if skip > 0:
                data = data[skip:]
                skip = 0

            # ─── قصّ البيانات إلى المتبقي ───
            if len(data) > remaining:
                data = data[:remaining]

            yield data
            total_sent += len(data)
            read_offset += read_size
            remaining -= len(data)

            if total_sent % (10 * CHUNK_SIZE) == 0:
                print(f"   ... sent {total_sent / 1024 / 1024:.1f}MB")

        if remaining > 0:
            print(f"⚠️ Stream ended early: {remaining / 1024 / 1024:.1f}MB remaining")
        else:
            print(f"✅ Stream complete: {total_sent / 1024 / 1024:.1f}MB sent")

    # ─── الترويسات ───
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
