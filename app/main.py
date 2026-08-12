from contextlib import asynccontextmanager
import asyncio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from app.config import settings
from app.database import connect, close
from app.temp_storage import cleanup_expired, read_temp_file

telegram_app = None
_uptime_task = None

async def _uptime_loop():
    while settings.uptime_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(settings.uptime_url)
        except Exception:
            pass
        await asyncio.sleep(settings.uptime_interval)

@asynccontextmanager
async def lifespan(app):
    global telegram_app, _uptime_task
    cleanup_expired()
    if settings.mongodb_uri:
        await connect()
    if settings.telegram_bot_token and settings.mongodb_uri:
        from app.telegram import build_application
        telegram_app = build_application()
        await telegram_app.initialize()
        await telegram_app.start()
        if settings.public_base_url:
            await telegram_app.bot.set_webhook(
                url=settings.public_base_url + "/telegram/webhook",
                secret_token=settings.webhook_secret or None,
                drop_pending_updates=False,
            )
    if settings.uptime_url:
        _uptime_task = asyncio.create_task(_uptime_loop())
    yield
    if _uptime_task:
        _uptime_task.cancel()
        try:
            await _uptime_task
        except asyncio.CancelledError:
            pass
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()
    await close()

app = FastAPI(title="Image AI Telegram Bot", version="7.1.0", lifespan=lifespan)

@app.get("/")
async def root():
    return {"service": "Image AI Telegram Bot", "status": "ok", "telegram": telegram_app is not None}

@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/api/status")
async def status():
    return {"status": "ok", "telegram": telegram_app is not None}

@app.get("/media/{file_id}")
async def media(file_id: str):
    raw = await read_temp_file(file_id)
    if not raw:
        return JSONResponse({"error": "not found"}, status_code=404)
    meta, data = raw
    return Response(
        data,
        media_type=meta["content_type"],
        headers={"Cache-Control": "no-store, no-cache", "X-Robots-Tag": "noindex, nofollow"},
    )

@app.post("/telegram/webhook")
async def webhook(request: Request):
    if settings.webhook_secret:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != settings.webhook_secret:
            return JSONResponse({"ok": False}, status_code=401)
    if telegram_app is None:
        return JSONResponse({"ok": False, "error": "bot unavailable"}, status_code=503)
    from telegram import Update
    update = Update.de_json(await request.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
