from .pixelcut import run

MAX_SIDE = 2000

def build_expansion(width: int, height: int, target_width: int, target_height: int, side: str):
    if target_width < width or target_height < height:
        raise ValueError("Expand can only increase dimensions; choose a larger target.")
    dw, dh = target_width - width, target_height - height

    if side in {"left", "right"} and dh:
        raise ValueError("For left/right expansion, the target ratio must keep the original height.")
    if side in {"top", "bottom"} and dw:
        raise ValueError("For top/bottom expansion, the target ratio must keep the original width.")

    if side == "left":
        left, right = dw, 0
        top, bottom = 0, dh
    elif side == "right":
        left, right = 0, dw
        top, bottom = 0, dh
    elif side == "top":
        left, right = 0, dw
        top, bottom = dh, 0
    elif side == "bottom":
        left, right = 0, dw
        top, bottom = 0, dh
    elif side == "all":
        left = dw // 2
        right = dw - left
        top = dh // 2
        bottom = dh - top
    else:
        raise ValueError("Invalid expand side.")

    values = (left, top, right, bottom)
    if max(values) > MAX_SIDE:
        raise ValueError("Pixelcut allows up to 2000 pixels per expansion side.")
    if sum(values) == 0:
        raise ValueError("At least one expansion side must be greater than zero.")
    return left, top, right, bottom

async def expand(image_url: str, width: int, height: int, target_width: int, target_height: int, side: str):
    left, top, right, bottom = build_expansion(width, height, target_width, target_height, side)
    return await run("/v1/outpaint", {
        "image_url": image_url,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "creativity": 0,
        "output_format": "jpeg",
    })
