from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def operations():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✂️ REMOVE BG", callback_data="op:remove"),
         InlineKeyboardButton("✨ UPSCALE", callback_data="op:upscale")],
        [InlineKeyboardButton("🖼️ EXPAND", callback_data="op:expand")],
    ])

def scales(prefix, include_original=False):
    rows = []
    if include_original:
        rows.append([InlineKeyboardButton("Original", callback_data=f"{prefix}:1")])
    rows.append([
        InlineKeyboardButton("2×", callback_data=f"{prefix}:2"),
        InlineKeyboardButton("4×", callback_data=f"{prefix}:4"),
    ])
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def ratios():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1:1", callback_data="ratio:1:1"),
         InlineKeyboardButton("4:3", callback_data="ratio:4:3"),
         InlineKeyboardButton("4:5", callback_data="ratio:4:5")],
        [InlineKeyboardButton("9:16", callback_data="ratio:9:16"),
         InlineKeyboardButton("16:9", callback_data="ratio:16:9"),
         InlineKeyboardButton("2.39:1", callback_data="ratio:2.39:1")],
        [InlineKeyboardButton("A4", callback_data="ratio:a4"),
         InlineKeyboardButton("Letter", callback_data="ratio:letter")],
        [InlineKeyboardButton("Custom", callback_data="ratio:custom"),
         InlineKeyboardButton("✖ Cancel", callback_data="cancel")],
    ])

def sides():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆ TOP", callback_data="side:top"),
         InlineKeyboardButton("⬇ BOTTOM", callback_data="side:bottom")],
        [InlineKeyboardButton("⬅ LEFT", callback_data="side:left"),
         InlineKeyboardButton("➡ RIGHT", callback_data="side:right")],
        [InlineKeyboardButton("⬆⬇⬅➡ ALL SIDES", callback_data="side:all")],
        [InlineKeyboardButton("✖ Cancel", callback_data="cancel")],
    ])

def us():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Format", callback_data="us:format"),
         InlineKeyboardButton("🖼 Thumbnail", callback_data="us:thumb")],
        [InlineKeyboardButton("🔖 Prefix", callback_data="us:prefix"),
         InlineKeyboardButton("🔖 Suffix", callback_data="us:suffix")],
        [InlineKeyboardButton("🔢 Scale filename", callback_data="us:scale_name"),
         InlineKeyboardButton("🎚 JPG quality", callback_data="us:quality")],
        [InlineKeyboardButton("♻️ Reset", callback_data="us:reset")],
    ])

def bs():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Pixelcut APIs", callback_data="bs:apis"),
         InlineKeyboardButton("🔐 Privacy", callback_data="bs:privacy")],
        [InlineKeyboardButton("⚙️ Processing", callback_data="bs:processing"),
         InlineKeyboardButton("📁 Output", callback_data="bs:output")],
        [InlineKeyboardButton("🔄 API Rotation", callback_data="bs:rotation")],
    ])

def api_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add API", callback_data="api:add"),
         InlineKeyboardButton("📋 API List", callback_data="api:list")],
        [InlineKeyboardButton("⬅ Back", callback_data="bs:back")],
    ])

def privacy(enc, show):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Encryption display: {'ON 🔒' if enc else 'OFF 🔓'}", callback_data="privacy:enc")],
        [InlineKeyboardButton(f"Show API keys: {'ON 👁️' if show else 'OFF 🙈'}", callback_data="privacy:show")],
        [InlineKeyboardButton("⬅ Back", callback_data="bs:back")],
    ])

def processing(timeout, max_upload):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱ Timeout: {timeout}s", callback_data="bs:timeout"),
         InlineKeyboardButton(f"📦 Max upload: {max_upload}MB", callback_data="bs:maxupload")],
        [InlineKeyboardButton("⬅ Back", callback_data="bs:back")],
    ])

def output(quality, thumbnail):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎚 JPG quality: {quality}", callback_data="bs:quality")],
        [InlineKeyboardButton(f"🖼 Global thumbnail: {'ON' if thumbnail else 'OFF'}", callback_data="bs:thumbnail")],
        [InlineKeyboardButton("⬅ Back", callback_data="bs:back")],
    ])

def rotation(enabled):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"API rotation: {'ON 🔄' if enabled else 'OFF ⏸'}", callback_data="bs:rotation_toggle")],
        [InlineKeyboardButton("⬅ Back", callback_data="bs:back")],
    ])

def api_list(items):
    rows = []
    for oid, label, enabled in items:
        rows.append([
            InlineKeyboardButton(("🟢 " if enabled else "🔴 ") + label[:30], callback_data=f"api:toggle:{oid}"),
            InlineKeyboardButton("🗑", callback_data=f"api:delete:{oid}"),
        ])
    rows += [
        [InlineKeyboardButton("➕ Add API", callback_data="api:add")],
        [InlineKeyboardButton("⬅ Back", callback_data="bs:apis")],
    ]
    return InlineKeyboardMarkup(rows)
