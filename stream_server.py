#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_server.py — خادم MTProto للبث المباشر من Telegram
يدعم Range Requests و الملفات الكبيرة (حتى 2GB)
"""

import os
import re
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pyrogram import Client
from pyrogram.file_id import FileId
from pyrogram.raw.functions.upload import GetFile
from pyrogram.raw.types import InputDocumentFileLocation, InputPhotoFileLocation

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")

if not all([API_ID, API_HASH, STRING_SESSION]):
    raise RuntimeError("❌ يجب ضبط API_ID و API_HASH و STRING_SESSION")

app = FastAPI(title="Telegram Stream Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["Range"],
    expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"],
)

client = Client(
    "stream_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    in_memory=True,
    workers=4,
)


@app.on_event("startup")
async def startup():
    await client.start()
    print("✅ MTProto client started")


@app.on_event("shutdown")
async def shutdown():
    await client.stop()


@app.get("/")
async def root():
    return {"service": "Telegram Stream Server", "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.head("/stream")
@app.get("/stream")
async def stream(request: Request, fid: str):
    """بث ملف عبر MTProto مع دعم Range"""
    if not fid:
        raise HTTPException(400, "missing fid")

    try:
        file_id = FileId.decode(fid)
    except Exception as e:
        raise HTTPException(400, f"invalid file_id: {e}")

    file_size = file_id.file_size
    if not file_size:
        raise HTTPException(400, "unknown file size")

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

    CHUNK = 1024 * 1024

    async def gen():
        offset = start
        remaining = length
        while remaining > 0:
            chunk_size = min(CHUNK, remaining)
            try:
                result = await client.invoke(
                    GetFile(location=location, offset=offset, limit=chunk_size)
                )
            except Exception as e:
                print(f"⚠️ chunk error at {offset}: {e}")
                break
            data = result.bytes
            if not data:
                break
            yield data
            offset += len(data)
            remaining -= len(data)

    headers = {
        "Content-Type": file_id.mime_type or "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "public, max-age=86400",
    }
    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(gen(), status_code=206, headers=headers)

    return StreamingResponse(gen(), headers=headers)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
