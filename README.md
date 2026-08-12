# 🤖 Image AI Telegram Bot

Professional Telegram image processing bot powered by the official Pixelcut API.

## Features

- 🪄 Remove Background
- 🔍 Upscale: 2× / 4×
- 🖼️ Expand with ratio presets and custom dimensions
- `1:1`, `4:3`, `4:5`, `9:16`, `16:9`, `2.39:1`, A4, Letter, Custom
- Custom `width × height` in pixels
- Expand side selection
- JPG / JPEG / PNG input
- JPG / PNG result documents
- User settings with `/us`
- Admin settings with `/bs`
- Multiple Pixelcut API keys with no fixed 10-key limit
- API enable/disable/delete
- API rotation and failover
- API-key encryption at rest
- Privacy control for API-key display
- Filename prefix/suffix
- Optional 2×/4× filename suffix
- Optional result thumbnail
- MongoDB persistence for settings
- Temporary image files are kept on the application instance only and automatically expire

## Telegram Flow

```text
/start
   ↓
Send your image/document
   ↓
REMOVE BG | UPSCALE
EXPAND
```

### `/start`

Asks the user to send an image/document. Settings are not shown here.

### `/us`

User settings:

- Output format
- JPG quality
- Filename prefix
- Filename suffix
- Include 2×/4× in filename
- Thumbnail
- Reset

### `/bs`

Admin-only settings:

- Pixelcut API management
- Privacy / API-key visibility
- Processing timeout
- Maximum Telegram upload size
- JPG quality
- Global thumbnail switch
- API rotation

## Pixelcut API

The integration uses the current official Pixelcut API format:

- Base URL: `https://api.developer.pixelcut.ai`
- Authentication: `X-API-Key`
- JSON request bodies
- Upscale: `POST /v1/upscale`
- Remove Background: `POST /v1/remove-background`
- Outpaint: `POST /v1/outpaint`

Pixelcut's current documentation confirms:

- Upscale accepts scale `2` or `4`.
- Upscale input limits include 25 MB, with endpoint resolution limits.
- Remove Background accepts JPEG/PNG and returns PNG when requested.
- Outpaint accepts `left`, `top`, `right`, and `bottom` values from 0–2000 pixels per side.
- Successful API responses provide a `result_url`.

References:
- https://www.pixelcut.ai/docs/api-reference
- https://www.pixelcut.ai/docs/api-reference/upscale
- https://www.pixelcut.ai/docs/api-reference/outpaint
- https://www.pixelcut.ai/api/background-remover

The bot performs Remove Background first and then, when requested, performs the selected 2×/4× upscale as a second Pixelcut operation. The same applies to Expand → 2×/4×.

## Multiple API Keys

There is no hard-coded limit of 10 API keys.

Add keys from:

```text
/bs
  → Pixelcut APIs
  → Add API
```

Each key can be enabled, disabled, or deleted.

When several keys are enabled, the bot selects keys in database order and can fail over to another key after retryable authentication, rate-limit, timeout, or service failures.

## Security

API keys are never hardcoded.

They are encrypted before being stored in MongoDB using `SETTINGS_ENCRYPTION_KEY`.

When encryption display is ON, the admin panel shows masked keys.

To display the full key in `/bs`, encryption display must be turned OFF and API-key visibility must be ON.

The application never sends API keys to ordinary users or to the browser.

> A key typed into a Telegram chat can still exist in Telegram's own message history. The bot attempts to minimize exposure by not echoing the key back.

## MongoDB

MongoDB stores persistent settings:

- User settings
- Admin settings
- Pixelcut API configurations
- API status
- Privacy settings
- Encryption settings
- Processing settings
- Output settings

Settings survive application restarts and Render redeployments as long as the same MongoDB database is used.

Uploaded image bytes are **not stored in MongoDB** because MongoDB documents have a 16 MB document limit. Temporary images are stored in the instance's temporary filesystem only and expire automatically.

## Upload Limit

Pixelcut supports images up to 25 MB, but the standard Telegram Bot API cloud file-download limit is 20 MB.

Therefore this Telegram bot safely caps downloads at **20 MB**.

## Expand

Preset ratios are calculated as an expand-only target canvas.

Example:

```text
Custom
  ↓
1920 × 1080
  ↓
TOP / BOTTOM / LEFT / RIGHT / ALL
  ↓
2× / 4×
```

Pixelcut permits a maximum of 2000 pixels per expansion direction. The bot validates this before sending the request.

If a selected one-sided direction cannot achieve the requested target ratio without changing the opposite dimension, the bot asks the user to choose a compatible side.

## Result Files

User settings can control:

```text
Prefix
Original filename
2× / 4× marker
Suffix
Extension
```

Example:

```text
upscaled_photo_4x_final.jpg
```

The result can also include a Telegram thumbnail when enabled.

## FastAPI Service

Endpoints:

```text
GET /
GET /api/healthz
GET /api/docs
GET /api/openapi.json
POST /telegram/webhook
GET /media/{temporary_file_id}
```

The FastAPI documentation and OpenAPI specification are generated automatically.

## Deployment

This is a Python web service.

### Render build command

```bash
pip install -r requirements.txt
```

### Render start command

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The application listens on `0.0.0.0` and uses the platform-provided `PORT`.

No frontend build is required.

## Environment Variables

Required:

```text
TELEGRAM_BOT_TOKEN
MONGODB_URI
ADMIN_IDS
SETTINGS_ENCRYPTION_KEY
PUBLIC_BASE_URL
WEBHOOK_SECRET
```

Optional:

```text
MONGODB_DATABASE
PIXELCUT_TIMEOUT
MAX_UPLOAD_MB
UPTIME_URL
UPTIME_INTERVAL
```

`MAX_UPLOAD_MB` is capped at 20 for Telegram cloud downloads.

### `UPTIME_URL`

Optional application self-ping feature.

If an external uptime-monitor URL is configured, the service periodically requests that URL while the process is running.

This can help with monitoring, but an application cannot wake itself after a platform has completely suspended it. A true anti-sleep setup therefore requires a supported external uptime/cron monitor or a paid/non-sleeping service plan.

## Project Structure

```text
app/
├── __init__.py
├── main.py
├── config.py
├── database.py
├── security.py
├── temp_storage.py
├── image_utils.py
├── keyboards.py
├── telegram.py
│
├── handlers/
│   ├── __init__.py
│   ├── start.py
│   ├── image.py
│   ├── settings.py
│   └── admin.py
│
└── services/
    ├── __init__.py
    ├── pixelcut.py
    ├── upscale.py
    ├── remove_bg.py
    └── expand.py

requirements.txt
render.yaml
.gitignore
README.md
```

## No Frontend Stack

This project does not use:

- React
- Vite
- Node.js
- npm
- pnpm
- TypeScript frontend
- Webpack
- frontend build tools
- `package.json`
- `node_modules`
- `vite build`
- `npm run build`
- `pnpm build`

## Testing

Before deployment, verify:

- `/` returns HTTP 200
- `/api/healthz` returns HTTP 200
- `/api/docs` returns HTTP 200
- `/api/openapi.json` returns HTTP 200
- Telegram webhook accepts valid Telegram updates
- Invalid webhook secret is rejected
- `/start`, `/us`, `/bs`
- JPG/PNG uploads
- Invalid file rejection
- 20 MB upload limit
- 2× / 4× upscale
- Remove Background → 2×/4×
- Expand → 2×/4×
- Preset ratios
- 2.39:1
- Custom dimensions
- Expand side validation
- Multiple API key rotation/failover
- MongoDB persistence
- Encryption/privacy settings
- Filename settings
- Thumbnail settings

## Important

Real Pixelcut processing requires a valid Pixelcut API key with available API credits.

Real Telegram and MongoDB end-to-end testing requires the corresponding production credentials and network access.

Do not commit credentials to GitHub.
