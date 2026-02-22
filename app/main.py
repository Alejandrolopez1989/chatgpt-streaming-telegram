from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en variables de entorno")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_BASE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

app = FastAPI(title="Telegram Streaming Proxy")


def extract_file_id(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    if "/stream/" in value:
        return value.rsplit("/stream/", 1)[-1].split("?", 1)[0].strip("/")

    if "/watch/" in value:
        return value.rsplit("/watch/", 1)[-1].split("?", 1)[0].strip("/")

    return value


async def resolve_file_path(file_id: str) -> tuple[str, int | None]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/getFile", params={"file_id": file_id})

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Error consultando Telegram")

    data = r.json()
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail="file_id no válido o inaccesible")

    result = data["result"]
    return result["file_path"], result.get("file_size")


async def stream_telegram_file(file_url: str, range_header: str | None) -> tuple[AsyncIterator[bytes], int, dict]:
    headers = {}
    if range_header:
        headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=None)
    upstream = await client.stream("GET", file_url, headers=headers)

    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=upstream.status_code, detail="No se pudo leer archivo en Telegram")

    passthrough_headers = {
        "Accept-Ranges": upstream.headers.get("accept-ranges", "bytes"),
    }

    for h in ("content-range", "content-length", "content-type", "cache-control", "etag", "last-modified"):
        if h in upstream.headers:
            passthrough_headers[h.title()] = upstream.headers[h]

    async def iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return iterator(), upstream.status_code, passthrough_headers


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home(file_id: str = "") -> Response:
    cleaned_file_id = extract_file_id(file_id)
    iframe_src = f"/watch/{cleaned_file_id}" if cleaned_file_id else ""
    stream_src = f"/stream/{cleaned_file_id}" if cleaned_file_id else ""

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
    <h1>Reproductor desde Telegram</h1>
    <p>
      Pega aquí el <code>file_id</code> de Telegram o un enlace como
      <code>/stream/&lt;file_id&gt;</code> para cargar la película en el iframe.
    </p>

    <form method="get" action="/" style="display: flex; gap: .5rem; margin-bottom: 1rem;">
      <input
        type="text"
        name="file_id"
        placeholder="Ej: BAACAgQAAxkBAA..."
        value="{cleaned_file_id}"
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


@app.get("/stream/{file_id}")
async def stream(file_id: str, range: str | None = Header(default=None)) -> StreamingResponse:
    file_path, _ = await resolve_file_path(file_id)
    file_url = f"{FILE_BASE}/{file_path}"

    body, status_code, headers = await stream_telegram_file(file_url, range)
    return StreamingResponse(body, status_code=status_code, headers=headers)


@app.get("/watch/{file_id}", response_class=HTMLResponse)
async def watch(file_id: str) -> Response:
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
    <p>File ID: <code>{file_id}</code></p>
    <video controls style="width: 100%; border-radius: 12px;" src="/stream/{file_id}"></video>
  </body>
</html>
        """
    )
