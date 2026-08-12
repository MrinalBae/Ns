from datetime import datetime, timedelta, timezone
import math
from io import BytesIO
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from PIL import Image
from app.config import settings
from app.database import get_bot_settings, get_user_settings
from app.temp_storage import new_file_id, save_temp_file, get_temp_file, read_temp_file, delete_temp_file
from app.image_utils import validate_image, image_info, convert_output, make_thumbnail, normalize_filename
from app.keyboards import operations, scales, ratios, sides
from app.services.upscale import upscale
from app.services.remove_bg import remove_background
from app.services.expand import expand

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

async def receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await get_bot_settings()
    limit = min(int(bot["processing"].get("max_upload_mb", 20)), 20) * 1024 * 1024
    doc = update.message.document
    photo = update.message.photo[-1] if update.message.photo else None
    try:
        if doc:
            if doc.mime_type not in ("image/jpeg", "image/png"):
                raise ValueError("Only JPG/JPEG/PNG images are supported.")
            if doc.file_size and doc.file_size > limit:
                raise ValueError("Image exceeds the 20 MB Telegram cloud download limit.")
            tg_file = await doc.get_file()
            data = bytes(await tg_file.download_as_bytearray())
            name = doc.file_name or "image.png"
        elif photo:
            tg_file = await photo.get_file()
            data = bytes(await tg_file.download_as_bytearray())
            name = "image.jpg"
        else:
            return
        validate_image(data, limit)
        file_id = new_file_id()
        ctype = "image/png" if name.lower().endswith(".png") else "image/jpeg"
        file_id = file_id + (".png" if ctype == "image/png" else ".jpg")
        await save_temp_file(file_id, data, ctype, name, datetime.now(timezone.utc) + timedelta(minutes=15))
        context.user_data.clear()
        context.user_data["file_id"] = file_id
        context.user_data["name"] = name
        await update.message.reply_text("Choose an operation:", reply_markup=operations())
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")

def _target_dimensions(width, height, ratio):
    rw, rh = RATIOS[ratio]
    target_ratio = rw / rh
    # Expand-only: choose the smallest canvas with the requested ratio.
    if width / height > target_ratio:
        tw = width
        th = math.ceil(width / target_ratio)
    else:
        th = height
        tw = math.ceil(height * target_ratio)
    return int(tw), int(th)

def _parse_custom(text):
    raw = text.lower().replace("×", "x").replace(" ", "")
    if "x" not in raw:
        raise ValueError
    w, h = raw.split("x", 1)
    w, h = int(w), int(h)
    if not (128 <= w <= 6000 and 128 <= h <= 6000):
        raise ValueError
    return w, h

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "op:remove":
        context.user_data["operation"] = "remove"
        await q.edit_message_text("Remove BG — choose result scale.", reply_markup=scales("remove"))
    elif d == "op:upscale":
        context.user_data["operation"] = "upscale"
        await q.edit_message_text("Upscale — choose scale.", reply_markup=scales("upscale"))
    elif d == "op:expand":
        context.user_data["operation"] = "expand"
        await q.edit_message_text("Expand — choose target ratio.", reply_markup=ratios())
    elif d.startswith("upscale:"):
        await run_operation(update, context, int(d.split(":")[1]), "upscale")
    elif d.startswith("remove:"):
        await run_operation(update, context, int(d.split(":")[1]), "remove")
    elif d.startswith("ratio:"):
        r = d.split(":", 1)[1]
        if r == "custom":
            context.user_data["expand_wait"] = "custom"
            await q.message.reply_text("Send custom target width × height, e.g. 1920 x 1080.")
        else:
            context.user_data["ratio"] = r
            await q.edit_message_text("Choose which side to expand.", reply_markup=sides())
    elif d.startswith("side:"):
        context.user_data["side"] = d.split(":", 1)[1]
        if context.user_data.get("ratio"):
            await prepare_ratio_expand(update, context)
        else:
            context.user_data["expand_wait"] = "amount"
            await q.edit_message_text("Send expansion amount in pixels.\nExample: 500")
    elif d.startswith("expandscale:"):
        await run_operation(update, context, int(d.split(":")[1]), "expand")
    elif d == "cancel":
        context.user_data.clear()
        await q.edit_message_text("Cancelled. Send another image.")

async def prepare_ratio_expand(update, context):
    record = await get_temp_file(context.user_data.get("file_id", ""))
    if not record:
        await update.callback_query.message.reply_text("Image expired. Send it again.")
        return
    raw = await read_temp_file(context.user_data.get("file_id", ""))
    if not raw:
        await update.callback_query.message.reply_text("Image expired. Send it again.")
        return
    _, image_bytes = raw
    width, height = image_info(image_bytes)
    ratio = context.user_data["ratio"]
    if ratio in RATIOS:
        target_w, target_h = _target_dimensions(width, height, ratio)
    else:
        target_w, target_h = context.user_data["custom_size"]
    side = context.user_data["side"]
    try:
        from app.services.expand import build_expansion
        build_expansion(width, height, target_w, target_h, side)
    except ValueError as exc:
        await update.callback_query.message.reply_text(f"❌ {exc}\nChoose another side or ratio.")
        return
    context.user_data["target_size"] = (target_w, target_h)
    await update.callback_query.message.reply_text("Choose result scale.", reply_markup=scales("expandscale"))

async def text(update, context):
    wait = context.user_data.get("expand_wait")
    if not wait:
        return False
    try:
        if wait == "custom":
            context.user_data["custom_size"] = _parse_custom(update.message.text)
            context.user_data.pop("expand_wait", None)
            await update.message.reply_text("Choose which side to expand.", reply_markup=sides())
        elif wait == "amount":
            amount = int(update.message.text.strip())
            if not 1 <= amount <= 2000:
                raise ValueError
            context.user_data["expand_amount"] = amount
            context.user_data.pop("expand_wait", None)
            await update.message.reply_text("Choose result scale.", reply_markup=scales("expandscale"))
    except Exception:
        await update.message.reply_text("Invalid value.")
    return True

async def run_operation(update, context, scale, operation):
    q = update.callback_query
    record = await get_temp_file(context.user_data.get("file_id", ""))
    if not record:
        await q.message.reply_text("Image expired. Send it again.")
        return
    intermediate_id = None
    try:
        if not settings.public_base_url:
            raise RuntimeError("PUBLIC_BASE_URL is not configured.")
        image_url = f"{settings.public_base_url}/media/{record['file_id']}"

        if operation == "upscale":
            result, ctype = await upscale(image_url, scale)
        elif operation == "remove":
            result, ctype = await remove_background(image_url)
            if scale in (2, 4):
                intermediate_id = new_file_id() + (".png" if ctype == "image/png" else ".jpg")
                await save_temp_file(intermediate_id, result, ctype, "result.png",
                                      datetime.now(timezone.utc) + timedelta(minutes=10))
                result, ctype = await upscale(f"{settings.public_base_url}/media/{intermediate_id}", scale)
        else:
            raw = await read_temp_file(record["file_id"])
            if not raw:
                raise RuntimeError("Image expired. Send it again.")
            _, original_bytes = raw
            width, height = image_info(original_bytes)
            if "target_size" in context.user_data:
                target_w, target_h = context.user_data["target_size"]
            elif "expand_amount" in context.user_data:
                amount = context.user_data["expand_amount"]
                side = context.user_data["side"]
                target_w, target_h = width, height
                if side in ("left", "right"):
                    target_w += amount
                elif side in ("top", "bottom"):
                    target_h += amount
                else:
                    target_w += amount * 2
                    target_h += amount * 2
            else:
                raise RuntimeError("Expand settings are incomplete.")
            result, ctype = await expand(image_url, width, height, target_w, target_h, context.user_data["side"])
            if scale in (2, 4):
                intermediate_id = new_file_id() + (".png" if ctype == "image/png" else ".jpg")
                await save_temp_file(intermediate_id, result, ctype, "expanded.jpg",
                                      datetime.now(timezone.utc) + timedelta(minutes=10))
                result, ctype = await upscale(f"{settings.public_base_url}/media/{intermediate_id}", scale)

        user = await get_user_settings(update.effective_user.id)
        bot = await get_bot_settings()
        fmt = user["format"]
        quality = min(int(user["jpeg_quality"]), int(bot["output"].get("jpeg_quality", 95)))
        result, out_ctype, ext = convert_output(result, fmt, quality)
        filename = normalize_filename(
            context.user_data.get("name", "image"),
            user["prefix"], user["suffix"], scale, ext, bool(user["scale_in_filename"])
        )
        thumb_bytes = make_thumbnail(result) if user["thumbnail"] and bot["output"]["thumbnail"] else None

        await q.message.reply_document(
            document=BytesIO(result),
            filename=filename,
            thumbnail=InputFile(BytesIO(thumb_bytes), filename="thumb.jpg") if thumb_bytes else None,
            caption=f"✅ {operation.replace('_', ' ').title()} complete.",
        )
    except Exception as exc:
        await q.message.reply_text(f"❌ {str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Processing failed.'}")
    finally:
        await delete_temp_file(record["file_id"])
        if intermediate_id:
            await delete_temp_file(intermediate_id)
        context.user_data.clear()
