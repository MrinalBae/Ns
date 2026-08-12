from telegram import Update
from telegram.ext import ContextTypes
from app.config import settings
from app.database import get_bot_settings, list_apis, add_api, toggle_api, delete_api, set_bot
from app.security import encrypt_secret, decrypt_secret, mask_secret
from app.keyboards import bs, api_menu, api_list, privacy, processing, output, rotation

def is_admin(uid: int):
    return uid in settings.admin_ids

async def show(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin access only.")
        return
    await update.message.reply_text("<b>Admin Settings</b>", parse_mode="HTML", reply_markup=bs())

async def callback(update, context):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("Admin only.", show_alert=True)
        return
    await q.answer()
    parts = q.data.split(":")
    action = parts[1]

    if action == "apis":
        await q.edit_message_text("🔑 Pixelcut APIs", reply_markup=api_menu())
    elif action == "privacy":
        s = await get_bot_settings()
        await q.edit_message_text("🔐 Privacy", reply_markup=privacy(s["privacy"]["encryption"], s["privacy"]["show_api_keys"]))
    elif action == "processing":
        s = await get_bot_settings()
        await q.edit_message_text("⚙️ Processing", reply_markup=processing(s["processing"]["timeout"], s["processing"]["max_upload_mb"]))
    elif action == "output":
        s = await get_bot_settings()
        await q.edit_message_text("📁 Output", reply_markup=output(s["output"]["jpeg_quality"], s["output"]["thumbnail"]))
    elif action == "rotation":
        s = await get_bot_settings()
        await q.edit_message_text("🔄 API Rotation", reply_markup=rotation(s["rotation"]["enabled"]))
    elif action == "rotation_toggle":
        s = await get_bot_settings()
        await set_bot("rotation.enabled", not s["rotation"]["enabled"])
        s = await get_bot_settings()
        await q.edit_message_reply_markup(reply_markup=rotation(s["rotation"]["enabled"]))
    elif action == "back":
        await q.edit_message_text("<b>Admin Settings</b>", parse_mode="HTML", reply_markup=bs())
    elif action == "thumbnail":
        s = await get_bot_settings()
        await set_bot("output.thumbnail", not s["output"]["thumbnail"])
        s = await get_bot_settings()
        await q.edit_message_reply_markup(reply_markup=output(s["output"]["jpeg_quality"], s["output"]["thumbnail"]))
    elif action in ("timeout", "maxupload", "quality"):
        context.user_data["admin_wait"] = action
        await q.message.reply_text({
            "timeout": "Timeout seconds 10–600.",
            "maxupload": "Max upload MB 1–20. Telegram cloud Bot API downloads are limited to 20 MB.",
            "quality": "JPG quality 1–100.",
        }[action])
    elif action == "enc":
        s = await get_bot_settings()
        new = not s["privacy"]["encryption"]
        await set_bot("privacy.encryption", new)
        if new:
            await set_bot("privacy.show_api_keys", False)
        s = await get_bot_settings()
        await q.edit_message_reply_markup(reply_markup=privacy(s["privacy"]["encryption"], s["privacy"]["show_api_keys"]))
    elif action == "show":
        s = await get_bot_settings()
        if s["privacy"]["encryption"]:
            await q.answer("Turn Encryption display OFF before showing API keys.", show_alert=True)
            return
        await set_bot("privacy.show_api_keys", not s["privacy"]["show_api_keys"])
        s = await get_bot_settings()
        await q.edit_message_reply_markup(reply_markup=privacy(s["privacy"]["encryption"], s["privacy"]["show_api_keys"]))
    elif action == "add":
        context.user_data["admin_wait"] = "api"
        await q.message.reply_text("Send: Label | API_KEY\nThe message is processed only by the bot and the credential is stored encrypted.")
    elif action == "list":
        docs = await list_apis()
        s = await get_bot_settings()
        if not docs:
            await q.edit_message_text("No APIs configured.", reply_markup=api_menu())
            return
        rows = []
        for d in docs:
            key = decrypt_secret(d["key"], settings.settings_encryption_key)
            shown = key if (not s["privacy"]["encryption"] and s["privacy"]["show_api_keys"]) else mask_secret(key)
            rows.append(f"<b>{d['label']}</b> — {shown}")
        await q.edit_message_text("\n".join(rows), parse_mode="HTML", reply_markup=api_list([(str(d["_id"]), d["label"], d["enabled"]) for d in docs]))
    elif action == "toggle" and len(parts) == 3:
        ok = await toggle_api(parts[2])
        await q.answer("API status updated." if ok else "API not found.", show_alert=not ok)
        docs = await list_apis()
        await q.edit_message_reply_markup(reply_markup=api_list([(str(d["_id"]), d["label"], d["enabled"]) for d in docs]))
    elif action == "delete" and len(parts) == 3:
        ok = await delete_api(parts[2])
        await q.answer("API deleted." if ok else "API not found.", show_alert=not ok)
        docs = await list_apis()
        await q.edit_message_reply_markup(reply_markup=api_list([(str(d["_id"]), d["label"], d["enabled"]) for d in docs]))

async def text(update, context):
    action = context.user_data.get("admin_wait")
    if not action or not is_admin(update.effective_user.id):
        return False
    value = update.message.text.strip()
    try:
        if action == "api":
            if "|" not in value:
                raise ValueError
            label, key = [x.strip() for x in value.split("|", 1)]
            if not label or not key or len(label) > 40 or len(key) > 500:
                raise ValueError
            await add_api(label, encrypt_secret(key, settings.settings_encryption_key))
        elif action == "timeout":
            v = int(value)
            if not 10 <= v <= 600: raise ValueError
            await set_bot("processing.timeout", v)
        elif action == "maxupload":
            v = int(value)
            if not 1 <= v <= 20: raise ValueError
            await set_bot("processing.max_upload_mb", v)
        elif action == "quality":
            v = int(value)
            if not 1 <= v <= 100: raise ValueError
            await set_bot("output.jpeg_quality", v)
        else:
            raise ValueError
    except Exception:
        await update.message.reply_text("Invalid value.")
        return True
    context.user_data.pop("admin_wait", None)
    await update.message.reply_text("✅ Saved to MongoDB.")
    return True
