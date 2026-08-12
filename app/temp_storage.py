from pathlib import Path
from datetime import datetime, timezone
import secrets
import tempfile
import asyncio

BASE = Path(tempfile.gettempdir()) / "image_ai_bot"
BASE.mkdir(parents=True, exist_ok=True)
_lock = asyncio.Lock()

def cleanup_expired():
    now = datetime.now(timezone.utc).timestamp()
    for path in BASE.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > 20 * 60:
                path.unlink(missing_ok=True)
        except OSError:
            pass

def new_file_id():
    return secrets.token_urlsafe(24)

async def save_temp_file(file_id, data, content_type, filename, expires_at):
    path = BASE / file_id
    path.write_bytes(data)
    meta = {"file_id": file_id, "path": str(path), "content_type": content_type,
            "filename": filename, "expires_at": expires_at}
    return meta

async def get_temp_file(file_id):
    path = BASE / file_id
    if not path.exists() or "/" in file_id or "\\" in file_id:
        return None
    # Files older than 20 minutes are considered expired.
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    if age > 20 * 60:
        await delete_temp_file(file_id)
        return None
    # Content type is inferred from extension for the only supported formats.
    ext = path.suffix.lower()
    ctype = "image/png" if ext == ".png" else "image/jpeg"
    return {"file_id": file_id, "path": str(path), "content_type": ctype,
            "filename": path.name, "expires_at": datetime.fromtimestamp(path.stat().st_mtime + 20*60, timezone.utc)}

async def delete_temp_file(file_id):
    if not file_id or "/" in file_id or "\\" in file_id:
        return
    path = BASE / file_id
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
