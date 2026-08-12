from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from app.config import settings
from app.handlers.start import start
from app.handlers.settings import (
    show as user_settings,
    callback as user_settings_callback,
    text as user_settings_text,
)
from app.handlers.admin import (
    show as admin_settings,
    callback as admin_callback,
    text as admin_text,
)
from app.handlers.image import (
    receive,
    callback as image_callback,
    text as image_text,
)


def build_application():
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured."
        )

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("us", user_settings)
    )

    app.add_handler(
        CommandHandler("bs", admin_settings)
    )

    # User settings callbacks
    app.add_handler(
        CallbackQueryHandler(
            user_settings_callback,
            pattern=r"^us:",
        )
    )

    # Admin callbacks
    app.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^(bs:|api:|privacy:)",
        )
    )

    # Image operation callbacks
    #
    # block=False is useful because upscale/remove-bg/expand
    # can take some time to finish.
    app.add_handler(
        CallbackQueryHandler(
            image_callback,
            pattern=r"^(op:|upscale:|remove:|ratio:|side:|expandscale:|cancel$)",
            block=False,
        )
    )

    # Text handlers
    # Priority order is important.
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            image_text,
            group=0,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            user_settings_text,
            group=1,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_text,
            group=2,
        )
    )

    # Image receiver
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.IMAGE,
            receive,
            group=3,
        )
    )

    return app
