# Telegram Streaming Proxy (Pyrogram)

Este proyecto expone una API/web para usar Telegram como origen de video y reproducirlo por HTTP con soporte de `Range` (seek en navegador), usando **Pyrogram** y streaming por chunks.

## ¿Cómo funciona?

1. El bot tiene acceso al chat/canal donde está el video.
2. Tomas la referencia del mensaje: `chat_id/message_id`.
3. Esta app expone:
   - `GET /stream/{chat_id}/{message_id}`: streaming por chunks con `Range`.
   - `GET /watch/{chat_id}/{message_id}`: página HTML con `<video>`.

## Requisitos

- Python 3.11+
- Credenciales de API de Telegram (my.telegram.org):
  - `TELEGRAM_API_ID`
  - `TELEGRAM_API_HASH`
- Token de bot:
  - `TELEGRAM_BOT_TOKEN`

## Configuración

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env`:

```env
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
TELEGRAM_BOT_TOKEN=123456:ABC...
PYROGRAM_SESSION=telegram-streaming-proxy
HOST=0.0.0.0
PORT=8000
```

## Ejecutar

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Obtener `chat_id/message_id`

- En grupos/canales, puedes tomar el `message_id` del post.
- El `chat_id` suele tener forma `-100...`.
- También puedes usar `getUpdates` para ver `message.chat.id` y `message.message_id`.

## Uso

- Streaming directo:

```text
http://localhost:8000/stream/<chat_id>/<message_id>
```

- Página web con reproductor:

```text
http://localhost:8000/watch/<chat_id>/<message_id>
```

- Home para pegar referencia:

```text
http://localhost:8000/?ref=-1001234567890/42
```

## Consideraciones

- Soporta cabecera `Range` para saltos de reproducción.
- El streaming se realiza por chunks de 1MB desde Telegram (no descarga todo en memoria).
- Asegúrate de que el bot tenga permisos para leer el mensaje en el chat/canal.
