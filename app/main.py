from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pyrogram import Client
from pyrogram.errors import RPCError

load_dotenv()

API_ID_RAW = os.getenv("TELEGRAM_API_ID", "").strip()
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not API_ID_RAW or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Faltan TELEGRAM_API_ID, TELEGRAM_API_HASH o TELEGRAM_BOT_TOKEN")

API_ID = int(API_ID_RAW)
CHUNK_SIZE = 1024 * 1024  # Pyrogram stream_media trabaja en bloques de 1MB

client = Client(
    name="telegram-streaming-proxy",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp",
)


@dataclass
class RangeWindow:
    start: int
    end: int


@asynccontextmanager
async def lifespan(_: FastAPI):
    await client.start()
    try:
        yield
    finally:
        await client.stop()


app = FastAPI(title="Telegram Streaming Proxy (Pyrogram)", lifespan=lifespan)


def extract_media_ref(value: str) -> tuple[str, str]:
    """Acepta t.me/c/<id>/<msg_id> o chat_id:message_id."""
    value = value.strip()
    if not value:
        return "", ""

    match = re.search(r"t\.me/c/(\d+)/(\d+)", value)
    if match:
        internal_chat_id = f"-100{match.group(1)}"
        return internal_chat_id, match.group(2)

    if ":" in value:
        chat_id, message_id = value.split(":", 1)
        return chat_id.strip(), message_id.strip()

    return "", ""


def parse_range_header(range_header: str | None, file_size: int) -> RangeWindow:
    if not range_header:
        return RangeWindow(start=0, end=file_size - 1)

    match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match:
        raise HTTPException(status_code=416, detail="Header Range inválido")

    start_raw, end_raw = match.groups()

    if start_raw == "" and end_raw == "":
        raise HTTPException(status_code=416, detail="Header Range inválido")

    if start_raw == "":
        suffix_length = int(end_raw)
        if suffix_length <= 0:
            raise HTTPException(status_code=416, detail="Header Range inválido")
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        start = int(start_raw)
        end = int(end_raw) if end_raw else file_size - 1

    if start >= file_size or start < 0 or end < start:
        raise HTTPException(status_code=416, detail="Range fuera de límites")

    end = min(end, file_size - 1)
    return RangeWindow(start=start, end=end)


async def resolve_message_media(chat_id: int, message_id: int) -> tuple[object, int, str]:
    try:
        message = await client.get_messages(chat_id=chat_id, message_ids=message_id)
    except RPCError as exc:
        raise HTTPException(status_code=404, detail=f"No se pudo leer el mensaje: {exc}") from exc

    if not message:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")

    media = message.video or message.document
    if not media:
        raise HTTPException(status_code=400, detail="El mensaje no contiene video/documento")

    file_size = getattr(media, "file_size", None)
    if not file_size:
        raise HTTPException(status_code=400, detail="No se pudo resolver el tamaño del archivo")

    mime_type = getattr(media, "mime_type", None) or "application/octet-stream"
    return message, file_size, mime_type


async def stream_telegram_media(
    message: object,
    file_size: int,
    mime_type: str,
    range_header: str | None,
) -> tuple[AsyncIterator[bytes], int, dict[str, str]]:
    window = parse_range_header(range_header, file_size)
    start_chunk = window.start // CHUNK_SIZE
    end_chunk = window.end // CHUNK_SIZE
    offset_inside_first_chunk = window.start % CHUNK_SIZE
    bytes_to_emit = window.end - window.start + 1

    async def iterator() -> AsyncIterator[bytes]:
        nonlocal bytes_to_emit
        current_chunk_index = start_chunk
        async for chunk in client.stream_media(message, offset=start_chunk, limit=(end_chunk - start_chunk + 1)):
            if current_chunk_index == start_chunk and offset_inside_first_chunk:
                chunk = chunk[offset_inside_first_chunk:]

            if bytes_to_emit <= 0:
                break

            if len(chunk) > bytes_to_emit:
                chunk = chunk[:bytes_to_emit]

            bytes_to_emit -= len(chunk)
            current_chunk_index += 1
            yield chunk

    status_code = 206 if range_header else 200
    headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime_type,
        "Content-Length": str(window.end - window.start + 1),
    }

    if status_code == 206:
        headers["Content-Range"] = f"bytes {window.start}-{window.end}/{file_size}"

    return iterator(), status_code, headers


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home(media: str = "") -> Response:
    chat_id, message_id = extract_media_ref(media)
    iframe_src = f"/watch/{chat_id}/{message_id}" if chat_id and message_id else ""

    return HTMLResponse(
        f"""
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Telegram Streaming (Pyrogram)</title>
  </head>
  <body style="font-family: sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem;">
    <h1>Reproductor desde Telegram (archivos grandes)</h1>
    <p>Pega un enlace de canal privado tipo <code>https://t.me/c/123456/789</code> o <code>-100123456:789</code>.</p>

    <form method="get" action="/" style="display: flex; gap: .5rem; margin-bottom: 1rem;">
      <input
        type="text"
        name="media"
        placeholder="Ej: https://t.me/c/123456/789"
        value="{media}"
        style="flex: 1; padding: .6rem; border-radius: .5rem; border: 1px solid #ccc;"
      />
      <button type="submit" style="padding: .6rem 1rem; border-radius: .5rem; border: 0; cursor: pointer;">Reproducir</button>
    </form>

    <iframe
      title="Reproductor"
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
    message, file_size, mime_type = await resolve_message_media(chat_id, message_id)
    body, status_code, headers = await stream_telegram_media(message, file_size, mime_type, range)
    return StreamingResponse(body, status_code=status_code, headers=headers)


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
    <h1>Reproductor de Telegram</h1>
    <p>chat_id: <code>{chat_id}</code> | message_id: <code>{message_id}</code></p>
    <video controls style="width: 100%; border-radius: 12px;" src="/stream/{chat_id}/{message_id}"></video>
  </body>
</html>
        """
    )
