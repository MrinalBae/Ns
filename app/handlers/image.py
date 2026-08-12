# app/handlers/image.py

from datetime import datetime, timedelta, timezone
import logging
import math
from io import BytesIO

from telegram import Update, InputFile
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from app.config import settings
from app.database import get_bot_settings, get_user_settings
from app.temp_storage import (
    new_file_id,
    save_temp_file,
    get_temp_file,
    read_temp_file,
    delete_temp_file,
)
from app.image_utils import (
    validate_image,
    image_info,
    convert_output,
    make_thumbnail,
    normalize_filename,
)
from app.keyboards import operations, scales, ratios, sides
from app.services.upscale import upscale
from app.services.remove_bg import remove_background
from app.services.expand import expand


logger = logging.getLogger(__name__)


RATIOS = {
    "1:1": (1, 1),
    "4:3": (4, 3),
    "4:5": (4, 5),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "2.39:1": (2.39, 1),
    "a4": (210, 297),
    "letter": (8.5, 11),
}


# ============================================================
# RECEIVE IMAGE
# ============================================================

async def receive(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    try:
        bot = await get_bot_settings()

        processing = bot.get("processing") or {}

        configured_limit = int(
            processing.get(
                "max_upload_mb",
                settings.default_max_upload_mb,
            )
        )

        limit_mb = min(
            configured_limit,
            settings.default_max_upload_mb,
            20,
        )

        limit = limit_mb * 1024 * 1024

        doc = update.message.document

        photo = (
            update.message.photo[-1]
            if update.message.photo
            else None
        )

        # ----------------------------------------------------
        # DOCUMENT
        # ----------------------------------------------------

        if doc:
            mime_type = (
                (doc.mime_type or "")
                .strip()
                .lower()
            )

            if mime_type not in (
                "image/jpeg",
                "image/png",
            ):
                raise ValueError(
                    "Only JPG/JPEG/PNG images are supported."
                )

            if doc.file_size and doc.file_size > limit:
                raise ValueError(
                    f"Image exceeds the {limit_mb} MB upload limit."
                )

            tg_file = await doc.get_file()

            data = bytes(
                await tg_file.download_as_bytearray()
            )

            name = doc.file_name or "image.jpg"

        # ----------------------------------------------------
        # TELEGRAM PHOTO
        # ----------------------------------------------------

        elif photo:
            tg_file = await photo.get_file()

            data = bytes(
                await tg_file.download_as_bytearray()
            )

            name = "image.jpg"

        else:
            return

        # ----------------------------------------------------
        # VALIDATE ACTUAL IMAGE DATA
        # ----------------------------------------------------

        validate_image(
            data,
            limit,
        )

        width, height, image_format = image_info(
            data
        )

        if image_format == "PNG":
            ctype = "image/png"
            extension = ".png"

        elif image_format == "JPEG":
            ctype = "image/jpeg"
            extension = ".jpg"

        else:
            raise ValueError(
                "Only JPG/JPEG/PNG images are supported."
            )

        # ----------------------------------------------------
        # SAVE TEMP FILE
        # ----------------------------------------------------

        file_id = new_file_id(extension)

        await save_temp_file(
            file_id,
            data,
            ctype,
            name,
            datetime.now(timezone.utc)
            + timedelta(minutes=15),
        )

        # ----------------------------------------------------
        # RESET USER STATE
        # ----------------------------------------------------

        context.user_data.clear()

        context.user_data["file_id"] = file_id
        context.user_data["name"] = name

        context.user_data["width"] = width
        context.user_data["height"] = height

        await update.message.reply_text(
            "Choose an operation:",
            reply_markup=operations(),
        )

    except Exception as exc:
        logger.exception(
            "Image receive failed"
        )

        try:
            await update.message.reply_text(
                f"❌ {exc}"
            )
        except Exception:
            logger.exception(
                "Failed to send receive error message"
            )


# ============================================================
# RATIO HELPERS
# ============================================================

def _target_dimensions(
    width: int,
    height: int,
    ratio: str,
):
    if ratio not in RATIOS:
        raise ValueError(
            "Invalid target ratio."
        )

    rw, rh = RATIOS[ratio]

    target_ratio = rw / rh

    if width <= 0 or height <= 0:
        raise ValueError(
            "Invalid image dimensions."
        )

    if width / height > target_ratio:
        tw = width
        th = math.ceil(
            width / target_ratio
        )

    else:
        th = height
        tw = math.ceil(
            height * target_ratio
        )

    return int(tw), int(th)


def _parse_custom(text: str):
    if not text:
        raise ValueError(
            "Invalid dimensions."
        )

    raw = (
        text
        .strip()
        .lower()
        .replace("×", "x")
        .replace(" ", "")
    )

    if "x" not in raw:
        raise ValueError(
            "Use WIDTH x HEIGHT."
        )

    parts = raw.split("x")

    if len(parts) != 2:
        raise ValueError(
            "Use WIDTH x HEIGHT."
        )

    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError:
        raise ValueError(
            "Width and height must be numbers."
        )

    if not (
        128 <= width <= 6000
        and 128 <= height <= 6000
    ):
        raise ValueError(
            "Width and height must be between 128 and 6000 pixels."
        )

    return width, height


# ============================================================
# SAFE TELEGRAM CALLBACK ANSWER
# ============================================================

async def _safe_answer_callback(q):
    """
    Telegram callback queries expire quickly.

    If Telegram returns:
        Query is too old
        response timeout expired
        query id is invalid

    the actual operation must still continue.
    """

    if not q:
        return

    try:
        await q.answer()

    except BadRequest as exc:
        message = str(exc).lower()

        expired_messages = (
            "query is too old",
            "response timeout expired",
            "query id is invalid",
        )

        if any(
            item in message
            for item in expired_messages
        ):
            logger.warning(
                "Ignoring expired Telegram callback: %s",
                exc,
            )
            return

        raise

    except TelegramError:
        # Other Telegram errors should not silently
        # disappear.
        logger.exception(
            "Telegram callback answer failed"
        )
        raise


# ============================================================
# SAFE MESSAGE EDIT
# ============================================================

async def _safe_edit(
    q,
    text,
    reply_markup=None,
):
    """
    Editing an old/already-edited Telegram message can fail.
    Do not let that kill the whole callback handler.
    """

    if not q:
        return False

    try:
        await q.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )

        return True

    except BadRequest as exc:
        message = str(exc).lower()

        if (
            "message is not modified" in message
            or "message to edit not found" in message
            or "query is too old" in message
        ):
            logger.warning(
                "Ignoring Telegram edit error: %s",
                exc,
            )
            return False

        raise


# ============================================================
# CALLBACK
# ============================================================

async def callback(
    update,
    context,
):
    q = update.callback_query

    if not q:
        return

    # IMPORTANT:
    # This must NEVER prevent the actual image operation.
    try:
        await _safe_answer_callback(q)
    except Exception:
        # Log it, but continue processing the callback.
        logger.exception(
            "Callback answer failed; continuing operation"
        )

    d = q.data or ""

    try:

        # ----------------------------------------------------
        # REMOVE BG
        # ----------------------------------------------------

        if d == "op:remove":

            context.user_data["operation"] = "remove"

            await _safe_edit(
                q,
                "Remove BG — choose result scale.",
                scales("remove"),
            )

        # ----------------------------------------------------
        # UPSCALE
        # ----------------------------------------------------

        elif d == "op:upscale":

            context.user_data["operation"] = "upscale"

            await _safe_edit(
                q,
                "Upscale — choose scale.",
                scales("upscale"),
            )

        # ----------------------------------------------------
        # EXPAND
        # ----------------------------------------------------

        elif d == "op:expand":

            context.user_data["operation"] = "expand"

            await _safe_edit(
                q,
                "Expand — choose target ratio.",
                ratios(),
            )

        # ----------------------------------------------------
        # UPSCALE SCALE
        # ----------------------------------------------------

        elif d.startswith("upscale:"):

            raw_scale = d.split(
                ":",
                1,
            )[1]

            try:
                scale = int(raw_scale)
            except (ValueError, TypeError):
                await q.message.reply_text(
                    "❌ Invalid upscale scale."
                )
                return

            if scale not in (2, 4):
                await q.message.reply_text(
                    "❌ Upscale supports only 2× and 4×."
                )
                return

            await run_operation(
                update,
                context,
                scale,
                "upscale",
            )

        # ----------------------------------------------------
        # REMOVE SCALE
        # ----------------------------------------------------

        elif d.startswith("remove:"):

            raw_scale = d.split(
                ":",
                1,
            )[1]

            try:
                scale = int(raw_scale)
            except (ValueError, TypeError):
                await q.message.reply_text(
                    "❌ Invalid remove scale."
                )
                return

            if scale not in (2, 4):
                await q.message.reply_text(
                    "❌ Result scale must be 2× or 4×."
                )
                return

            await run_operation(
                update,
                context,
                scale,
                "remove",
            )

        # ----------------------------------------------------
        # RATIO
        # ----------------------------------------------------

        elif d.startswith("ratio:"):

            ratio = d.split(
                ":",
                1,
            )[1]

            if ratio == "custom":

                context.user_data[
                    "expand_wait"
                ] = "custom"

                await q.message.reply_text(
                    "Send custom target width × height.\n"
                    "Example: 1920 x 1080"
                )

            else:

                if ratio not in RATIOS:
                    await q.message.reply_text(
                        "❌ Invalid ratio."
                    )
                    return

                context.user_data[
                    "ratio"
                ] = ratio

                await _safe_edit(
                    q,
                    "Choose which side to expand.",
                    sides(),
                )

        # ----------------------------------------------------
        # SIDE
        # ----------------------------------------------------

        elif d.startswith("side:"):

            side = d.split(
                ":",
                1,
            )[1]

            valid_sides = {
                "left",
                "right",
                "top",
                "bottom",
                "all",
            }

            if side not in valid_sides:
                await q.message.reply_text(
                    "❌ Invalid expansion side."
                )
                return

            context.user_data[
                "side"
            ] = side

            if context.user_data.get("ratio"):

                await prepare_ratio_expand(
                    update,
                    context,
                )

            else:

                context.user_data[
                    "expand_wait"
                ] = "amount"

                await _safe_edit(
                    q,
                    "Send expansion amount in pixels.\n"
                    "Example: 500",
                )

        # ----------------------------------------------------
        # EXPAND SCALE
        # ----------------------------------------------------

        elif d.startswith("expandscale:"):

            raw_scale = d.split(
                ":",
                1,
            )[1]

            try:
                scale = int(raw_scale)
            except (ValueError, TypeError):
                await q.message.reply_text(
                    "❌ Invalid expand scale."
                )
                return

            if scale not in (2, 4):
                await q.message.reply_text(
                    "❌ Result scale must be 2× or 4×."
                )
                return

            await run_operation(
                update,
                context,
                scale,
                "expand",
            )

        # ----------------------------------------------------
        # CANCEL
        # ----------------------------------------------------

        elif d == "cancel":

            file_id = context.user_data.get(
                "file_id"
            )

            if file_id:
                try:
                    await delete_temp_file(
                        file_id
                    )
                except Exception:
                    logger.exception(
                        "Failed to delete cancelled temp file"
                    )

            context.user_data.clear()

            await _safe_edit(
                q,
                "Cancelled. Send another image.",
            )

    except Exception as exc:
        logger.exception(
            "Image callback failed: %s",
            exc,
        )

        try:
            await q.message.reply_text(
                f"❌ {exc}"
            )
        except Exception:
            logger.exception(
                "Failed to send callback error"
            )


# ============================================================
# PREPARE RATIO EXPAND
# ============================================================

async def prepare_ratio_expand(
    update,
    context,
):
    q = update.callback_query

    file_id = context.user_data.get(
        "file_id",
        "",
    )

    if not file_id:
        await q.message.reply_text(
            "❌ Image session not found. Send the image again."
        )
        return

    try:

        record = await get_temp_file(
            file_id
        )

        if not record:
            await q.message.reply_text(
                "❌ Image expired. Send it again."
            )
            return

        raw = await read_temp_file(
            file_id
        )

        if not raw:
            await q.message.reply_text(
                "❌ Image expired. Send it again."
            )
            return

        _, image_bytes = raw

        width, height, _ = image_info(
            image_bytes
        )

        ratio = context.user_data.get(
            "ratio"
        )

        if not ratio:
            raise ValueError(
                "Expand ratio is missing."
            )

        if ratio in RATIOS:

            target_w, target_h = (
                _target_dimensions(
                    width,
                    height,
                    ratio,
                )
            )

        else:

            custom_size = context.user_data.get(
                "custom_size"
            )

            if not custom_size:
                raise ValueError(
                    "Custom target size is missing."
                )

            target_w, target_h = custom_size

        side = context.user_data.get(
            "side"
        )

        if not side:
            raise ValueError(
                "Expand side is missing."
            )

        # ----------------------------------------------------
        # Validate expansion before running API
        # ----------------------------------------------------

        from app.services.expand import build_expansion

        build_expansion(
            width,
            height,
            target_w,
            target_h,
            side,
        )

        context.user_data[
            "target_size"
        ] = (
            target_w,
            target_h,
        )

        await q.message.reply_text(
            "Choose result scale.",
            reply_markup=scales(
                "expandscale"
            ),
        )

    except ValueError as exc:

        await q.message.reply_text(
            f"❌ {exc}\n"
            "Choose another side or ratio."
        )

    except Exception as exc:

        logger.exception(
            "Preparing ratio expansion failed"
        )

        await q.message.reply_text(
            f"❌ {exc}"
        )


# ============================================================
# TEXT HANDLER
# ============================================================

async def text(
    update,
    context,
):
    if not update.message:
        return False

    wait = context.user_data.get(
        "expand_wait"
    )

    if not wait:
        return False

    try:

        # ----------------------------------------------------
        # CUSTOM SIZE
        # ----------------------------------------------------

        if wait == "custom":

            custom_size = _parse_custom(
                update.message.text
            )

            context.user_data[
                "custom_size"
            ] = custom_size

            context.user_data[
                "ratio"
            ] = "custom"

            context.user_data.pop(
                "expand_wait",
                None,
            )

            await update.message.reply_text(
                "Choose which side to expand.",
                reply_markup=sides(),
            )

            return True

        # ----------------------------------------------------
        # EXPANSION AMOUNT
        # ----------------------------------------------------

        if wait == "amount":

            raw_amount = (
                update.message.text
                .strip()
            )

            try:
                amount = int(
                    raw_amount
                )
            except ValueError:
                raise ValueError(
                    "Expansion amount must be a number."
                )

            if not 1 <= amount <= 2000:
                raise ValueError(
                    "Expansion amount must be between 1 and 2000 pixels."
                )

            context.user_data[
                "expand_amount"
            ] = amount

            context.user_data.pop(
                "expand_wait",
                None,
            )

            await update.message.reply_text(
                "Choose result scale.",
                reply_markup=scales(
                    "expandscale"
                ),
            )

            return True

        return False

    except Exception as exc:

        await update.message.reply_text(
            f"❌ {exc}"
        )

        return True


# ============================================================
# RUN IMAGE OPERATION
# ============================================================

async def run_operation(
    update,
    context,
    scale,
    operation,
):
    q = update.callback_query

    file_id = context.user_data.get(
        "file_id",
        "",
    )

    if not file_id:
        await q.message.reply_text(
            "❌ Image session not found. Send the image again."
        )
        return

    intermediate_id = None

    try:

        # ----------------------------------------------------
        # VALIDATE OPERATION
        # ----------------------------------------------------

        valid_operations = {
            "upscale",
            "remove",
            "expand",
        }

        if operation not in valid_operations:
            raise ValueError(
                "Unknown image operation."
            )

        # ----------------------------------------------------
        # VALIDATE SCALE
        # ----------------------------------------------------

        if scale not in (2, 4):
            raise ValueError(
                "Scale must be 2 or 4."
            )

        # ----------------------------------------------------
        # CHECK TEMP FILE
        # ----------------------------------------------------

        record = await get_temp_file(
            file_id
        )

        if not record:
            raise RuntimeError(
                "Image expired. Send it again."
            )

        # ----------------------------------------------------
        # PUBLIC URL
        # ----------------------------------------------------

        public_base_url = (
            settings.public_base_url
            or ""
        ).strip().rstrip("/")

        if not public_base_url:
            raise RuntimeError(
                "PUBLIC_BASE_URL is not configured."
            )

        image_url = (
            f"{public_base_url}"
            f"/media/{file_id}"
        )

        logger.info(
            "Starting image operation=%s scale=%s file_id=%s",
            operation,
            scale,
            file_id,
        )

        # ====================================================
        # DIRECT UPSCALE
        # ====================================================

        if operation == "upscale":

            await q.message.reply_text(
                f"⏳ Upscaling image {scale}×...\n"
                "Please wait."
            )

            logger.info(
                "Calling upscale service: %s",
                image_url,
            )

            result, ctype = await upscale(
                image_url,
                scale,
            )

            logger.info(
                "Upscale completed: scale=%s bytes=%s type=%s",
                scale,
                len(result) if result else 0,
                ctype,
            )

        # ====================================================
        # REMOVE BACKGROUND
        # ====================================================

        elif operation == "remove":

            await q.message.reply_text(
                "⏳ Removing background..."
            )

            result, ctype = (
                await remove_background(
                    image_url
                )
            )

            if not result:
                raise RuntimeError(
                    "Remove background returned an empty result."
                )

            # ------------------------------------------------
            # REMOVE BG -> UPSCALE
            # ------------------------------------------------

            if scale in (2, 4):

                await q.message.reply_text(
                    f"⏳ Upscaling result {scale}×..."
                )

                intermediate_ext = (
                    ".png"
                    if ctype == "image/png"
                    else ".jpg"
                )

                intermediate_id = new_file_id(
                    intermediate_ext
                )

                await save_temp_file(
                    intermediate_id,
                    result,
                    ctype,
                    (
                        "result.png"
                        if ctype == "image/png"
                        else "result.jpg"
                    ),
                    datetime.now(timezone.utc)
                    + timedelta(minutes=10),
                )

                intermediate_url = (
                    f"{public_base_url}"
                    f"/media/{intermediate_id}"
                )

                logger.info(
                    "Remove BG complete; starting upscale "
                    "scale=%s url=%s",
                    scale,
                    intermediate_url,
                )

                result, ctype = await upscale(
                    intermediate_url,
                    scale,
                )

                logger.info(
                    "Remove BG upscale completed: "
                    "bytes=%s type=%s",
                    len(result) if result else 0,
                    ctype,
                )

        # ====================================================
        # EXPAND
        # ====================================================

        elif operation == "expand":

            await q.message.reply_text(
                "⏳ Expanding image..."
            )

            raw = await read_temp_file(
                file_id
            )

            if not raw:
                raise RuntimeError(
                    "Image expired. Send it again."
                )

            _, original_bytes = raw

            width, height, _ = image_info(
                original_bytes
            )

            # ------------------------------------------------
            # TARGET SIZE
            # ------------------------------------------------

            if "target_size" in context.user_data:

                target_w, target_h = (
                    context.user_data[
                        "target_size"
                    ]
                )

            elif "expand_amount" in context.user_data:

                amount = context.user_data[
                    "expand_amount"
                ]

                side = context.user_data.get(
                    "side"
                )

                if not side:
                    raise RuntimeError(
                        "Expand side is missing."
                    )

                target_w = width
                target_h = height

                if side in (
                    "left",
                    "right",
                ):
                    target_w += amount

                elif side in (
                    "top",
                    "bottom",
                ):
                    target_h += amount

                elif side == "all":
                    target_w += amount * 2
                    target_h += amount * 2

                else:
                    raise RuntimeError(
                        "Invalid expand side."
                    )

            else:
                raise RuntimeError(
                    "Expand settings are incomplete."
                )

            side = context.user_data.get(
                "side"
            )

            if not side:
                raise RuntimeError(
                    "Expand side is missing."
                )

            logger.info(
                "Expand: %sx%s -> %sx%s side=%s",
                width,
                height,
                target_w,
                target_h,
                side,
            )

            result, ctype = await expand(
                image_url,
                width,
                height,
                target_w,
                target_h,
                side,
            )

            if not result:
                raise RuntimeError(
                    "Expand returned an empty result."
                )

            # ------------------------------------------------
            # EXPAND -> UPSCALE
            # ------------------------------------------------

            if scale in (2, 4):

                await q.message.reply_text(
                    f"⏳ Upscaling expanded image "
                    f"{scale}×..."
                )

                intermediate_ext = (
                    ".png"
                    if ctype == "image/png"
                    else ".jpg"
                )

                intermediate_id = new_file_id(
                    intermediate_ext
                )

                await save_temp_file(
                    intermediate_id,
                    result,
                    ctype,
                    (
                        "expanded.png"
                        if ctype == "image/png"
                        else "expanded.jpg"
                    ),
                    datetime.now(timezone.utc)
                    + timedelta(minutes=10),
                )

                intermediate_url = (
                    f"{public_base_url}"
                    f"/media/{intermediate_id}"
                )

                logger.info(
                    "Expand complete; starting upscale "
                    "scale=%s url=%s",
                    scale,
                    intermediate_url,
                )

                result, ctype = await upscale(
                    intermediate_url,
                    scale,
                )

                logger.info(
                    "Expand upscale completed: "
                    "bytes=%s type=%s",
                    len(result) if result else 0,
                    ctype,
                )

        # ----------------------------------------------------
        # CHECK RESULT
        # ----------------------------------------------------

        if not result:
            raise RuntimeError(
                "Image processing returned an empty result."
            )

        if not isinstance(
            result,
            (bytes, bytearray),
        ):
            raise RuntimeError(
                "Image processing returned invalid result data."
            )

        result = bytes(result)

        # ====================================================
        # SETTINGS
        # ====================================================

        user = await get_user_settings(
            update.effective_user.id
        )

        bot = await get_bot_settings()

        output_settings = (
            bot.get("output") or {}
        )

        fmt = user.get(
            "format",
            "jpg",
        )

        try:
            user_quality = int(
                user.get(
                    "jpeg_quality",
                    95,
                )
            )
        except Exception:
            user_quality = 95

        try:
            bot_quality = int(
                output_settings.get(
                    "jpeg_quality",
                    95,
                )
            )
        except Exception:
            bot_quality = 95

        quality = min(
            user_quality,
            bot_quality,
        )

        quality = max(
            1,
            min(
                quality,
                100,
            ),
        )

        # ====================================================
        # CONVERT OUTPUT
        # ====================================================

        result, out_ctype, ext = (
            convert_output(
                result,
                fmt,
                quality,
            )
        )

        if not result:
            raise RuntimeError(
                "Output conversion produced an empty result."
            )

        # ====================================================
        # FILENAME
        # ====================================================

        filename = normalize_filename(
            context.user_data.get(
                "name",
                "image",
            ),
            user.get(
                "prefix",
                "",
            ),
            user.get(
                "suffix",
                "",
            ),
            scale,
            ext,
            bool(
                user.get(
                    "scale_in_filename",
                    True,
                )
            ),
        )

        # ====================================================
        # THUMBNAIL
        # ====================================================

        thumbnail_enabled = bool(
            user.get(
                "thumbnail",
                True,
            )
            and output_settings.get(
                "thumbnail",
                True,
            )
        )

        thumb_bytes = None

        if thumbnail_enabled:

            try:
                thumb_bytes = make_thumbnail(
                    result
                )
            except Exception:
                logger.exception(
                    "Thumbnail creation failed; "
                    "sending result without thumbnail"
                )
                thumb_bytes = None

        # ====================================================
        # SEND RESULT
        # ====================================================

        result_size_mb = (
            len(result)
            / (
                1024 * 1024
            )
        )

        logger.info(
            "Sending Telegram result: "
            "operation=%s scale=%s size=%.2f MB "
            "filename=%s type=%s",
            operation,
            scale,
            result_size_mb,
            filename,
            out_ctype,
        )

        try:

            await q.message.reply_document(
                document=BytesIO(result),
                filename=filename,
                thumbnail=(
                    InputFile(
                        BytesIO(thumb_bytes),
                        filename="thumb.jpg",
                    )
                    if thumb_bytes
                    else None
                ),
                caption=(
                    "✅ "
                    f"{operation.replace('_', ' ').title()} "
                    f"{scale}× complete."
                ),
            )

        except TelegramError as send_exc:

            logger.exception(
                "Telegram failed to send processed result"
            )

            # Give user the actual Telegram error instead
            # of hiding it behind "Processing failed."
            raise RuntimeError(
                f"Telegram could not send the result: "
                f"{send_exc}"
            ) from send_exc

        logger.info(
            "Image operation completed successfully: "
            "operation=%s scale=%s",
            operation,
            scale,
        )

    except Exception as exc:

        logger.exception(
            "Image operation failed: "
            "operation=%s scale=%s file_id=%s",
            operation,
            scale,
            file_id,
        )

        # ----------------------------------------------------
        # USER-FRIENDLY ERROR
        # ----------------------------------------------------

        if isinstance(
            exc,
            (ValueError, RuntimeError),
        ):
            message = str(exc)

        elif isinstance(
            exc,
            TelegramError,
        ):
            message = (
                f"Telegram error: {exc}"
            )

        else:
            message = (
                f"{type(exc).__name__}: {exc}"
            )

        if not message:
            message = (
                "Unknown processing error."
            )

        try:
            await q.message.reply_text(
                f"❌ {message}"
            )
        except Exception:
            logger.exception(
                "Failed to send operation error"
            )

    finally:

        # ----------------------------------------------------
        # DELETE ORIGINAL TEMP FILE
        # ----------------------------------------------------

        try:
            await delete_temp_file(
                file_id
            )
        except Exception:
            logger.exception(
                "Failed to delete original temp file: %s",
                file_id,
            )

        # ----------------------------------------------------
        # DELETE INTERMEDIATE TEMP FILE
        # ----------------------------------------------------

        if intermediate_id:

            try:
                await delete_temp_file(
                    intermediate_id
                )
            except Exception:
                logger.exception(
                    "Failed to delete intermediate temp file: %s",
                    intermediate_id,
                )

        # ----------------------------------------------------
        # CLEAR USER STATE
        # ----------------------------------------------------

        context.user_data.clear()
