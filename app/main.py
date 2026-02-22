from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pyrogram import Client
from pyrogram.types import Message

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SESSION_NAME = os.getenv("PYROGRAM_SESSION", "telegram-streaming-proxy").strip()
CHUNK_SIZE = 1024 * 1024

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Faltan TELEGRAM_API_ID, TELEGRAM_API_HASH o TELEGRAM_BOT_TOKEN")

app = FastAPI(title="Telegram Streaming Proxy (Pyrogram)")


@dataclass
class MediaInfo:
    size: int
    mime_type: str


def extract_message_ref(value: str) -> tuple[int, int] | None:
    value = value.strip()
    if not value:
        return None

    if "/watch/" in value:
        value = value.rsplit("/watch/", 1)[-1]
    elif "/stream/" in value:
        value = value.rsplit("/stream/", 1)[-1]

    value = value.split("?", 1)[0].strip("/")

    if ":" in value:
        chat_id, message_id = value.split(":", 1)
    elif "/" in value:
        chat_id, message_id = value.split("/", 1)
    else:
        return None

    try:
        return int(chat_id), int(message_id)
    except ValueError:
        return None


def parse_range_header(range_header: str | None, size: int) -> tuple[int, int, bool]:
    if not range_header:
        return 0, size - 1, False

    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="Range inválido")

    raw = range_header.replace("bytes=", "", 1).strip()
    if "," in raw:
        raise HTTPException(status_code=416, detail="Range múltiple no soportado")

    start_str, end_str = raw.split("-", 1)

    if start_str == "":
        suffix = int(end_str)
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="Range inválido")
        start = max(size - suffix, 0)
        end = size - 1
    else:
        start = int(start_str)
        end = size - 1 if end_str == "" else int(end_str)

    if start < 0 or end < start or start >= size:
        raise HTTPException(status_code=416, detail="Range fuera de tamaño")

    end = min(end, size - 1)
    return start, end, True


def message_media_info(message: Message) -> MediaInfo:
    if message.video:
        return MediaInfo(size=message.video.file_size or 0, mime_type=message.video.mime_type or "video/mp4")
    if message.document:
        return MediaInfo(size=message.document.file_size or 0, mime_type=message.document.mime_type or "application/octet-stream")
    raise HTTPException(status_code=404, detail="El mensaje no contiene video/documento")


async def chunked_stream(message: Message, start: int, end: int) -> AsyncIterator[bytes]:
    first_chunk = start // CHUNK_SIZE
    last_chunk = end // CHUNK_SIZE
    limit = (last_chunk - first_chunk) + 1

    offset_in_first = start % CHUNK_SIZE
    bytes_left = (end - start) + 1

    chunk_index = 0
    async for chunk in app.state.tg.stream_media(message, offset=first_chunk, limit=limit):
        data = bytes(chunk)

        if chunk_index == 0 and offset_in_first:
            data = data[offset_in_first:]

        if len(data) > bytes_left:
            data = data[:bytes_left]

        if data:
            yield data
            bytes_left -= len(data)

        if bytes_left <= 0:
            break

        chunk_index += 1


@app.on_event("startup")
async def startup_event() -> None:
    app.state.tg = Client(
        name=SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        no_updates=True,
    )
    await app.state.tg.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await app.state.tg.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home(ref: str = "") -> Response:
    parsed = extract_message_ref(ref)
    slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""
    iframe_src = f"/watch/{slug}" if parsed else ""
    stream_src = f"/stream/{slug}" if parsed else ""

    return HTMLResponse(
        f"""
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Telegram Streaming</title>
  </head>
  <body style="font-family: sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem;">
    <h1>Reproductor desde Telegram (Pyrogram)</h1>
    <p>
      Pega una referencia de mensaje en formato <code>chat_id/message_id</code>
      (también acepta <code>chat_id:message_id</code>) para cargar el video.
    </p>

    <form method="get" action="/" style="display: flex; gap: .5rem; margin-bottom: 1rem;">
      <input
        type="text"
        name="ref"
        placeholder="Ej: -1001234567890/42"
        value="{ref}"
        style="flex: 1; padding: .6rem; border-radius: .5rem; border: 1px solid #ccc;"
      />
      <button type="submit" style="padding: .6rem 1rem; border-radius: .5rem; border: 0; cursor: pointer;">
        Reproducir
      </button>
    </form>

    <p style="margin: .5rem 0;">
      Enlace de streaming:
      <a href="{stream_src}">{stream_src}</a>
    </p>

    <iframe
      title="Reproductor de película"
      src="{iframe_src}"
      style="width: 100%; min-height: 70vh; border: 1px solid #ddd; border-radius: 12px;"
      loading="lazy"
      allow="autoplay; fullscreen; picture-in-picture"
    ></iframe>
  </body>
</html>
        """
    )


@app.get("/stream/{chat_id}/{message_id}")
async def stream(chat_id: int, message_id: int, range: str | None = Header(default=None)) -> StreamingResponse:
    message = await app.state.tg.get_messages(chat_id=chat_id, message_ids=message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")

    info = message_media_info(message)
    if info.size <= 0:
        raise HTTPException(status_code=500, detail="No se pudo determinar el tamaño del archivo")

    start, end, partial = parse_range_header(range, info.size)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": info.mime_type,
        "Content-Length": str((end - start) + 1),
    }

    status_code = 206 if partial else 200
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{info.size}"

    return StreamingResponse(
        chunked_stream(message, start, end),
        status_code=status_code,
        headers=headers,
    )


@app.get("/watch/{chat_id}/{message_id}", response_class=HTMLResponse)
async def watch(chat_id: int, message_id: int) -> Response:
    return HTMLResponse(
        f"""
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Telegram Streaming</title>
  </head>
  <body style="font-family: sans-serif; max-width: 900px; margin: 2rem auto;">
    <h1>Reproductor de Telegram (Pyrogram)</h1>
    <p>Referencia: <code>{chat_id}/{message_id}</code></p>
    <video controls style="width: 100%; border-radius: 12px;" src="/stream/{chat_id}/{message_id}"></video>
  </body>
</html>
        """
    )
