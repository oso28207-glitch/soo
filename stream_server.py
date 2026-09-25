#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_server.py — خادم MTProto للبث المباشر من Telegram
متوافق مع Railway / Render / Fly.io / VPS
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

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "").strip()
STRING_SESSION = os.environ.get("STRING_SESSION", "").strip()

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


# ═══════════════════════════════════════════════════════════════
# Lifespan (بديل on_event)
# ═══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting MTProto client...")
    await client.start()
    me = await client.get_me()
    print(f"✅ MTProto client started as @{me.username or me.id}")
    yield
    # Shutdown
    print("👋 Stopping MTProto client...")
    await client.stop()
    print("✅ Stopped")


# ═══════════════════════════════════════════════════════════════
# FastAPI App
# ═══════════════════════════════════════════════════════════════
app = FastAPI(title="Telegram Stream Server", lifespan=lifespan)

# ★★★ CORS — يسمح لـ GitHub Pages بالوصول ★★★
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # يمكنك تحديد النطاقات بدقة:
    # allow_origins=[
    #     "https://oso28207-glitch.github.io",
    #     "https://soo.pages.dev",
    # ],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["Range", "Content-Type", "Accept", "Origin"],
    expose_headers=[
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "Content-Type",
    ],
    max_age=86400,
)


# ═══════════════════════════════════════════════════════════════
# CORS — Middleware إضافي لضمان الترويسات على كل الردود
# ═══════════════════════════════════════════════════════════════
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

    # إضافة CORS headers دائماً
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Range, Content-Type"
    response.headers["Access-Control-Expose-Headers"] = (
        "Content-Length, Content-Range, Accept-Ranges"
    )
    return response


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════
@app.get("/")
async def root():
    return {
        "service": "Telegram Stream Server",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "stream": "/stream?fid=FILE_ID",
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.head("/stream")
@app.get("/stream")
async def stream(request: Request, fid: str):
    """بث ملف عبر MTProto مع دعم Range Requests"""
    if not fid:
        raise HTTPException(400, "missing fid parameter")

    # ─── 1) فك تشفير file_id ───
    try:
        file_id = FileId.decode(fid)
    except Exception as e:
        print(f"❌ FileId.decode failed: {e}")
        raise HTTPException(400, f"invalid file_id: {e}")

    file_size = file_id.file_size
    if not file_size:
        raise HTTPException(400, "unknown file size")

    print(f"📥 Stream request: type={file_id.file_type}, "
          f"size={file_size / 1024 / 1024:.1f}MB")

    # ─── 2) تحليل Range ───
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

    # ─── 3) تحديد موقع الملف ───
    try:
        if file_id.file_type in ("video", "document", "audio", "animation"):
            location = InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size="",
            )
        elif file_id.file_type == "photo":
            location = InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size="",
            )
        else:
            raise HTTPException(400, f"unsupported file type: {file_id.file_type}")
    except Exception as e:
        print(f"❌ Location build failed: {e}")
        raise HTTPException(400, f"cannot build location: {e}")

    # ─── 4) مولّد البث ───
    CHUNK_SIZE = 1024 * 1024  # 1 MB

    async def generate():
        offset = start
        remaining = length
        chunk_count = 0
        while remaining > 0:
            chunk = min(CHUNK_SIZE, remaining)
            try:
                result = await client.invoke(
                    GetFile(location=location, offset=offset, limit=chunk)
                )
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

            if chunk_count % 5 == 0:
                print(f"   ... sent {chunk_count} chunks ({offset / 1024 / 1024:.1f}MB)")

    # ─── 5) الترويسات ───
    headers = {
        "Content-Type": file_id.mime_type or "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "public, max-age=86400",
    }

    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(generate(), status_code=206, headers=headers)

    return StreamingResponse(generate(), headers=headers)


# ═══════════════════════════════════════════════════════════════
# Error Handler عام
# ═══════════════════════════════════════════════════════════════
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"❌ Unhandled exception: {exc}")
    traceback.print_exc()
    return JSONResponse(
        {"error": "internal_error", "message": str(exc)},
        status_code=500,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range",
        },
    )


# ═══════════════════════════════════════════════════════════════
# نقطة البداية
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"🚀 Starting Telegram Stream Server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )
