from pathlib import Path
from datetime import datetime, timezone
import os
import secrets
import tempfile


BASE = Path(tempfile.gettempdir()) / "image_ai_bot"
BASE.mkdir(parents=True, exist_ok=True)


def _valid_file_id(file_id: str) -> bool:
    if not file_id:
        return False

    if "/" in file_id or "\\" in file_id or ".." in file_id:
        return False

    return True


def cleanup_expired():
    now = datetime.now(timezone.utc).timestamp()

    try:
        files = list(BASE.iterdir())
    except OSError:
        return

    for path in files:
        try:
            if not path.is_file():
                continue

            expires_at = path.stat().st_mtime

            if now >= expires_at:
                path.unlink(missing_ok=True)

        except OSError:
            pass


def new_file_id(extension: str | None = None) -> str:
    """
    Generate a safe temporary file ID.

    By default no extension is added.
    Callers should explicitly provide .jpg or .png
    based on the actual image content.
    """

    if extension is not None:
        extension = extension.lower()

        if extension not in {".jpg", ".png"}:
            extension = ".jpg"

    token = secrets.token_urlsafe(24).replace("/", "_")

    return token + (extension or "")


async def save_temp_file(
    file_id: str,
    data: bytes,
    content_type: str,
    filename: str,
    expires_at: datetime,
):
    if not _valid_file_id(file_id):
        raise ValueError("Invalid temporary file ID.")

    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("Temporary file data must be bytes.")

    if content_type not in {"image/jpeg", "image/png"}:
        raise ValueError("Unsupported temporary file content type.")

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    path = BASE / file_id

    try:
        path.write_bytes(bytes(data))

        # Use the requested expiration time as the file's
        # modification time so cleanup can enforce the
        # exact expiry requested by the caller.
        expiry_timestamp = expires_at.timestamp()
        os.utime(
            path,
            (expiry_timestamp, expiry_timestamp),
        )

    except OSError as exc:
        raise RuntimeError("Could not save temporary file.") from exc

    return {
        "file_id": file_id,
        "path": str(path),
        "content_type": content_type,
        "filename": filename,
        "expires_at": expires_at,
    }


async def get_temp_file(file_id: str):
    if not _valid_file_id(file_id):
        return None

    path = BASE / file_id

    if not path.is_file():
        return None

    try:
        expires_timestamp = path.stat().st_mtime
        now = datetime.now(timezone.utc).timestamp()

        if now >= expires_timestamp:
            await delete_temp_file(file_id)
            return None

        expires_at = datetime.fromtimestamp(
            expires_timestamp,
            timezone.utc,
        )

    except OSError:
        return None

    ext = path.suffix.lower()

    if ext not in {".jpg", ".png"}:
        return None

    content_type = (
        "image/png"
        if ext == ".png"
        else "image/jpeg"
    )

    return {
        "file_id": file_id,
        "path": str(path),
        "content_type": content_type,
        "filename": path.name,
        "expires_at": expires_at,
    }


async def read_temp_file(file_id: str):
    meta = await get_temp_file(file_id)

    if not meta:
        return None

    try:
        return meta, Path(meta["path"]).read_bytes()
    except OSError:
        return None


async def delete_temp_file(file_id: str):
    if not _valid_file_id(file_id):
        return

    try:
        (BASE / file_id).unlink(missing_ok=True)
    except OSError:
        pass
