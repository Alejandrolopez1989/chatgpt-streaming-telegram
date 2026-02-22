# Telegram Streaming Proxy (Pyrogram)

Este proyecto expone una API/web para reproducir videos de Telegram (incluyendo archivos grandes) usando MTProto con **Pyrogram**.

## ¿Cómo funciona?

1. Tu bot está en el canal donde subes películas/capítulos.
2. Tomas el enlace del mensaje (ej: `https://t.me/c/123456/789`).
3. Esta app expone:
   - `GET /stream/{chat_id}/{message_id}`: proxy de streaming por chunks.
   - `GET /watch/{chat_id}/{message_id}`: reproductor HTML.
   - `GET /`: formulario que acepta el enlace `t.me/c/...` y carga el iframe.

## Requisitos

- Python 3.11+
- `TELEGRAM_API_ID` y `TELEGRAM_API_HASH` (de https://my.telegram.org)
- `TELEGRAM_BOT_TOKEN` (de `@BotFather`)
- El bot debe estar en el canal con permisos para leer mensajes.

## Configuración

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Variables de entorno:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
TELEGRAM_BOT_TOKEN=123456:ABC...
```

## Ejecutar

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Uso

### Opción A: Home con iframe

Abre:

```text
http://localhost:8000/
```

Pega una referencia de media:

- Enlace privado: `https://t.me/c/123456/789`
- O formato directo: `-100123456:789`

### Opción B: URLs directas

```text
http://localhost:8000/watch/-100123456/789
http://localhost:8000/stream/-100123456/789
```

## Cómo obtener `chat_id` y `message_id`

- Si tienes enlace `https://t.me/c/123456/789`:
  - `chat_id` = `-100123456`
  - `message_id` = `789`

## Consideraciones

- Este enfoque evita la limitación de Bot API con `file is too big`, porque usa MTProto con Pyrogram.
- Para producción, agrega autenticación o URLs firmadas para evitar acceso público a tus archivos.
