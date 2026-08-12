# app/main.py

from contextlib import asynccontextmanager
import asyncio
import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse

from app.config import settings
from app.database import connect, close
from app.temp_storage import cleanup_expired, read_temp_file


logger = logging.getLogger(__name__)


# ============================================================
# GLOBAL STATE
# ============================================================

telegram_app = None

_uptime_task = None
_startup_task = None

_services_ready = False
_startup_error = None


# ============================================================
# UPTIME LOOP
# ============================================================

async def _uptime_loop():
    """
    Optional uptime/self-ping loop.

    This runs independently from application startup so it
    cannot block FastAPI from becoming healthy.
    """

    while settings.uptime_url:

        try:

            async with httpx.AsyncClient(
                timeout=10
            ) as client:

                await client.get(
                    settings.uptime_url
                )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Uptime request failed"
            )

        try:
            await asyncio.sleep(
                settings.uptime_interval
            )

        except asyncio.CancelledError:
            raise


# ============================================================
# BACKGROUND SERVICE INITIALIZATION
# ============================================================

async def _initialize_services():
    """
    Initialize MongoDB + Telegram in the background.

    IMPORTANT:
    This function is intentionally NOT awaited directly by
    FastAPI lifespan before yield.

    Render can therefore reach /api/healthz immediately,
    even if MongoDB or Telegram takes several seconds to
    initialize.
    """

    global telegram_app
    global _services_ready
    global _startup_error

    try:

        logger.info(
            "Starting background service initialization..."
        )

        # ----------------------------------------------------
        # TEMP STORAGE CLEANUP
        # ----------------------------------------------------

        try:

            cleanup_expired()

            logger.info(
                "Expired temporary files cleaned."
            )

        except Exception:

            logger.exception(
                "Temporary file cleanup failed"
            )

        # ----------------------------------------------------
        # MONGODB
        # ----------------------------------------------------

        if settings.mongodb_uri:

            logger.info(
                "Connecting to MongoDB..."
            )

            await connect()

            logger.info(
                "MongoDB connection established."
            )

        else:

            logger.warning(
                "MONGODB_URI is not configured."
            )

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        if (
            settings.telegram_bot_token
            and settings.mongodb_uri
        ):

            logger.info(
                "Building Telegram application..."
            )

            from app.telegram import (
                build_application
            )

            telegram_app = (
                build_application()
            )

            logger.info(
                "Initializing Telegram application..."
            )

            await telegram_app.initialize()

            logger.info(
                "Starting Telegram application..."
            )

            await telegram_app.start()

            # ------------------------------------------------
            # WEBHOOK
            # ------------------------------------------------

            if settings.public_base_url:

                webhook_url = (
                    settings.public_base_url.rstrip("/")
                    + "/telegram/webhook"
                )

                logger.info(
                    "Setting Telegram webhook: %s",
                    webhook_url,
                )

                await telegram_app.bot.set_webhook(
                    url=webhook_url,
                    secret_token=(
                        settings.webhook_secret
                        or None
                    ),
                    drop_pending_updates=False,
                )

                logger.info(
                    "Telegram webhook configured successfully."
                )

            else:

                logger.warning(
                    "PUBLIC_BASE_URL is not configured; "
                    "Telegram webhook was not set."
                )

        else:

            if not settings.telegram_bot_token:
                logger.warning(
                    "TELEGRAM_BOT_TOKEN is not configured."
                )

            if not settings.mongodb_uri:
                logger.warning(
                    "MongoDB is not configured; "
                    "Telegram application was not started."
                )

        _services_ready = True
        _startup_error = None

        logger.info(
            "Background service initialization completed."
        )

    except asyncio.CancelledError:

        logger.info(
            "Background service initialization cancelled."
        )

        raise

    except Exception as exc:

        _startup_error = (
            f"{type(exc).__name__}: {exc}"
        )

        _services_ready = False

        logger.exception(
            "Background service initialization failed."
        )


# ============================================================
# FASTAPI LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    global _uptime_task
    global _startup_task

    logger.info(
        "FastAPI lifespan starting..."
    )

    # --------------------------------------------------------
    # START SERVICES IN BACKGROUND
    # --------------------------------------------------------

    _startup_task = asyncio.create_task(
        _initialize_services()
    )

    # --------------------------------------------------------
    # START UPTIME LOOP
    # --------------------------------------------------------

    if settings.uptime_url:

        _uptime_task = asyncio.create_task(
            _uptime_loop()
        )

        logger.info(
            "Uptime loop started."
        )

    # --------------------------------------------------------
    # IMPORTANT
    # --------------------------------------------------------
    #
    # Yield immediately.
    #
    # Do NOT wait for MongoDB / Telegram here.
    #
    # This allows Render's health check to receive:
    #
    # GET /api/healthz -> 200 OK
    #
    # within the 5 second health-check window.
    # --------------------------------------------------------

    logger.info(
        "FastAPI is ready to receive HTTP requests."
    )

    yield

    # ========================================================
    # SHUTDOWN
    # ========================================================

    logger.info(
        "FastAPI shutdown started..."
    )

    # --------------------------------------------------------
    # STOP UPTIME TASK
    # --------------------------------------------------------

    if _uptime_task:

        _uptime_task.cancel()

        try:
            await _uptime_task

        except asyncio.CancelledError:
            pass

        except Exception:
            logger.exception(
                "Error while stopping uptime task"
            )

        _uptime_task = None

    # --------------------------------------------------------
    # STOP STARTUP TASK
    # --------------------------------------------------------

    if _startup_task:

        if not _startup_task.done():

            _startup_task.cancel()

            try:
                await _startup_task

            except asyncio.CancelledError:
                pass

            except Exception:
                logger.exception(
                    "Error while stopping startup task"
                )

        _startup_task = None

    # --------------------------------------------------------
    # STOP TELEGRAM
    # --------------------------------------------------------

    global telegram_app

    if telegram_app:

        try:

            logger.info(
                "Stopping Telegram application..."
            )

            await telegram_app.stop()

        except Exception:

            logger.exception(
                "Telegram application stop failed"
            )

        try:

            logger.info(
                "Shutting down Telegram application..."
            )

            await telegram_app.shutdown()

        except Exception:

            logger.exception(
                "Telegram application shutdown failed"
            )

        telegram_app = None

    # --------------------------------------------------------
    # CLOSE DATABASE
    # --------------------------------------------------------

    try:

        await close()

        logger.info(
            "Database connection closed."
        )

    except Exception:

        logger.exception(
            "Database shutdown failed"
        )

    logger.info(
        "FastAPI shutdown completed."
    )


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Image AI Telegram Bot",
    version="7.1.0",
    lifespan=lifespan,
)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "service": "Image AI Telegram Bot",
        "status": "ok",
        "telegram": telegram_app is not None,
        "ready": _services_ready,
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/healthz")
async def healthz():

    """
    Extremely lightweight health endpoint.

    DO NOT add MongoDB/Telegram checks here.

    Render needs this endpoint to respond immediately.
    """

    return {
        "status": "ok",
    }


# ============================================================
# STATUS
# ============================================================

@app.get("/api/status")
async def status():

    response = {
        "status": "ok",
        "telegram": telegram_app is not None,
        "ready": _services_ready,
    }

    if _startup_error:

        response["startup_error"] = (
            _startup_error
        )

    return response


# ============================================================
# MEDIA
# ============================================================

@app.get("/media/{file_id}")
async def media(
    file_id: str,
):

    try:

        raw = await read_temp_file(
            file_id
        )

    except Exception as exc:

        logger.exception(
            "Failed to read media file: %s",
            file_id,
        )

        return JSONResponse(
            {
                "error": str(exc),
            },
            status_code=500,
        )

    if not raw:

        return JSONResponse(
            {
                "error": "not found",
            },
            status_code=404,
        )

    meta, data = raw

    return Response(
        data,
        media_type=meta[
            "content_type"
        ],
        headers={
            "Cache-Control": (
                "no-store, no-cache"
            ),
            "X-Robots-Tag": (
                "noindex, nofollow"
            ),
        },
    )


# ============================================================
# TELEGRAM WEBHOOK
# ============================================================

@app.post("/telegram/webhook")
async def webhook(
    request: Request,
):

    # --------------------------------------------------------
    # SECRET TOKEN
    # --------------------------------------------------------

    if settings.webhook_secret:

        supplied = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            "",
        )

        if (
            supplied
            != settings.webhook_secret
        ):

            logger.warning(
                "Rejected Telegram webhook: "
                "invalid secret token."
            )

            return JSONResponse(
                {
                    "ok": False,
                },
                status_code=401,
            )

    # --------------------------------------------------------
    # BOT NOT READY
    # --------------------------------------------------------

    if telegram_app is None:

        logger.warning(
            "Telegram webhook received before "
            "Telegram application was ready."
        )

        # 503 tells Telegram that it should retry.
        return JSONResponse(
            {
                "ok": False,
                "error": "bot unavailable",
            },
            status_code=503,
        )

    # --------------------------------------------------------
    # PARSE UPDATE
    # --------------------------------------------------------

    try:

        from telegram import Update

        payload = await request.json()

        update = Update.de_json(
            payload,
            telegram_app.bot,
        )

        # ----------------------------------------------------
        # PROCESS UPDATE
        # ----------------------------------------------------

        await telegram_app.process_update(
            update
        )

        return {
            "ok": True,
        }

    except Exception as exc:

        logger.exception(
            "Telegram webhook processing failed."
        )

        return JSONResponse(
            {
                "ok": False,
                "error": (
                    f"{type(exc).__name__}: {exc}"
                ),
            },
            status_code=500,
        )
