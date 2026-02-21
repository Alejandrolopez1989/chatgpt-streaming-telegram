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
