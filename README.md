# Telegram Streaming Proxy

Este proyecto crea una pequeña API/web para usar Telegram como almacenamiento de videos y reproducirlos desde una página web usando enlaces de streaming.

## ¿Cómo funciona?

1. Subes o reenvías tus videos a un bot de Telegram.
2. El bot obtiene el `file_id` de cada video.
3. Esta app expone:
   - `GET /stream/{file_id}`: proxy de streaming (oculta tu token del bot).
   - `GET /watch/{file_id}`: página HTML con reproductor `<video>`.

> Nota: para contenido personal de tu cuenta (no bot), necesitarías MTProto (Telethon/Pyrogram). Esta versión usa la Bot API porque es más estable para publicar streaming web.

## Requisitos

- Python 3.11+
- Un bot de Telegram (`@BotFather`) y su token

## Configuración

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...
HOST=0.0.0.0
PORT=8000
```

## Ejecutar

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Obtener `file_id`

Envía un video al bot y llama:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
```

Busca `message.video.file_id` (o `message.document.file_id`).

## Uso

- Streaming directo:

```text
http://localhost:8000/stream/<file_id>
```

- Página web con reproductor:

```text
http://localhost:8000/watch/<file_id>
```

## Consideraciones

- Este proxy pasa cabeceras `Range` para reproducción por salto (`seek`) en navegador.
- No sube archivos automáticamente: solo reproduce los ya subidos a Telegram.
- Para producción, agrega autenticación o URLs firmadas para evitar acceso público a tus archivos.
