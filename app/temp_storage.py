from pathlib import Path
from datetime import datetime, timezone
import secrets
import tempfile

BASE = Path(tempfile.gettempdir()) / "image_ai_bot"
BASE.mkdir(parents=True, exist_ok=True)


def cleanup_expired():
    now = datetime.now(timezone.utc).timestamp()
    for path in list(BASE.iterdir()):
        try:
            if path.is_file() and now - path.stat().st_mtime > 20 * 60:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def new_file_id(extension=".jpg"):
    if extension not in {".jpg", ".png"}:
        extension = ".jpg"
    return secrets.token_urlsafe(24).replace("/", "_") + extension


async def save_temp_file(file_id, data, content_type, filename, expires_at):
    if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id:
        raise ValueError("Invalid temporary file ID.")
    path = BASE / file_id
    path.write_bytes(data)
    return {
        "file_id": file_id,
        "path": str(path),
        "content_type": content_type,
        "filename": filename,
        "expires_at": expires_at,
    }


async def get_temp_file(file_id):
    if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id:
        return None
    path = BASE / file_id
    if not path.is_file():
        return None
    try:
        if datetime.now(timezone.utc).timestamp() - path.stat().st_mtime > 20 * 60:
            await delete_temp_file(file_id)
            return None
    except OSError:
        return None
    ext = path.suffix.lower()
    if ext not in {".jpg", ".png"}:
        return None
    ctype = "image/png" if ext == ".png" else "image/jpeg"
    return {
        "file_id": file_id,
        "path": str(path),
        "content_type": ctype,
        "filename": path.name,
        "expires_at": datetime.fromtimestamp(path.stat().st_mtime + 20 * 60, timezone.utc),
    }


async def read_temp_file(file_id):
    meta = await get_temp_file(file_id)
    if not meta:
        return None
    try:
        return meta, Path(meta["path"]).read_bytes()
    except OSError:
        return None


async def delete_temp_file(file_id):
    if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id:
        return
    try:
        (BASE / file_id).unlink(missing_ok=True)
    except OSError:
        pass
