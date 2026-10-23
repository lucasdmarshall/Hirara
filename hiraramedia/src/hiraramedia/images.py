"""image_compare: what changed between two images, and where.

An agent that changed a UI, re-rendered a chart or edited a document needs
to know whether the visible result changed as intended. Eyeballing two
screenshots is unreliable even for a vision model; a pixel diff is exact.
This returns the changed share, each changed region as a box with a plain
position ("top right"), and an annotated image that marks the changes.
"""

from __future__ import annotations

import io
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .errors import MediaError

CELL = 8


def load_rgb(path: Path, max_pixels: int) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        img = Image.open(path)
        img.load()
    except Image.DecompressionBombError as exc:
        raise MediaError(f"image is larger than HM_MAX_PIXELS ({max_pixels})") from exc
    except Exception as exc:  # noqa: BLE001 — any unreadable image
        raise MediaError(f"not a readable image: {exc}") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        canvas.alpha_composite(img)
        img = canvas
    return img.convert("RGB")


def _where(x: int, y: int, w: int, h: int, width: int, height: int) -> str:
    cx, cy = (x + w / 2) / width, (y + h / 2) / height
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    col = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    return "center" if (row, col) == ("middle", "center") else f"{row} {col}"


def regions(mask: np.ndarray, diff: np.ndarray, *, min_pixels: int, gap: int = 1) -> list[dict]:
    """Group changed pixels into boxes via an 8x8-cell grid flood fill."""
    h, w = mask.shape
    gh, gw = (h + CELL - 1) // CELL, (w + CELL - 1) // CELL
    padded = np.zeros((gh * CELL, gw * CELL), dtype=bool)
    padded[:h, :w] = mask
    cells = padded.reshape(gh, CELL, gw, CELL).any(axis=(1, 3))
    seen = np.zeros_like(cells)
    out = []
    for cy, cx in zip(*np.nonzero(cells)):
        if seen[cy, cx]:
            continue
        queue = deque([(cy, cx)])
        seen[cy, cx] = True
        y0 = y1 = cy
        x0 = x1 = cx
        while queue:
            y, x = queue.popleft()
            y0, y1, x0, x1 = min(y0, y), max(y1, y), min(x0, x), max(x1, x)
            for dy in range(-gap, gap + 1):
                for dx in range(-gap, gap + 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < gh and 0 <= nx < gw and cells[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        sy, ey = y0 * CELL, min(h, (y1 + 1) * CELL)
        sx, ex = x0 * CELL, min(w, (x1 + 1) * CELL)
        sub = mask[sy:ey, sx:ex]
        ys, xs = np.nonzero(sub)
        if ys.size < min_pixels:
            continue
        bx, by = sx + int(xs.min()), sy + int(ys.min())
        bw, bh = int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1
        out.append({
            "x": bx, "y": by, "width": bw, "height": bh,
            "changed_pixels": int(ys.size),
            "mean_change": round(float(diff[sy:ey, sx:ex][sub].mean()), 3),
            "position": _where(bx, by, bw, bh, w, h),
        })
    out.sort(key=lambda r: -r["changed_pixels"])
    return out


def compare(a: Image.Image, b: Image.Image, *, threshold: float = 0.1, min_region: int = 16,
            ignore: list | None = None, resize: bool = True, max_regions: int = 50) -> tuple[dict, bytes]:
    if not 0 <= threshold < 1:
        raise MediaError("threshold must be in [0, 1)")
    size_note = None
    if a.size != b.size:
        if not resize:
            raise MediaError(f"sizes differ ({a.size[0]}x{a.size[1]} vs {b.size[0]}x{b.size[1]}); "
                             "set resize=true to compare anyway")
        size_note = f"b was {b.size[0]}x{b.size[1]}, resized to {a.size[0]}x{a.size[1]}"
        b = b.resize(a.size, Image.LANCZOS)
    xa = np.asarray(a, dtype=np.int16)
    xb = np.asarray(b, dtype=np.int16)
    diff = np.abs(xa - xb).max(axis=2).astype(np.float32) / 255.0
    for box in ignore or []:
        try:
            x, y, w, h = (int(v) for v in box)
        except (TypeError, ValueError):
            raise MediaError("ignore entries must be [x, y, width, height]") from None
        diff[max(0, y): y + h, max(0, x): x + w] = 0
    mask = diff > threshold
    changed = int(mask.sum())
    total = mask.size
    found = regions(mask, diff, min_pixels=max(1, int(min_region)))

    # Annotated image: a faded grey copy of a, changed pixels in red, boxes.
    grey = ImageOps.grayscale(a).convert("RGB")
    base = np.asarray(grey, dtype=np.float32) * 0.45 + 140
    base[mask] = (230, 30, 30)
    overlay = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(overlay)
    for i, r in enumerate(found[:max_regions], 1):
        draw.rectangle([r["x"] - 2, r["y"] - 2, r["x"] + r["width"] + 1, r["y"] + r["height"] + 1],
                       outline=(255, 160, 0), width=2)
        draw.text((r["x"], max(0, r["y"] - 12)), str(i), fill=(255, 120, 0))
    buf = io.BytesIO()
    overlay.save(buf, format="PNG", optimize=True)

    mse = float(((xa - xb).astype(np.float32) ** 2).mean())
    psnr = None if mse == 0 else round(10 * np.log10(255.0 ** 2 / mse), 2)
    result = {
        "width": a.size[0],
        "height": a.size[1],
        "identical": changed == 0 and mse == 0,
        "changed_pixels": changed,
        "changed_pct": round(100 * changed / total, 3),
        "psnr_db": psnr,
        "regions": found[:max_regions],
        "region_count": len(found),
        "size_note": size_note,
    }
    if result["identical"]:
        text = "identical"
    elif not changed:
        text = f"no visible change above threshold {threshold} (PSNR {psnr} dB)"
    else:
        parts = [f"{len(found)} changed region(s), {result['changed_pct']}% of pixels"]
        for i, r in enumerate(found[:10], 1):
            parts.append(f"#{i} {r['position']}: {r['width']}x{r['height']} at ({r['x']},{r['y']})")
        text = "; ".join(parts)
    result["text"] = text + (f"; {size_note}" if size_note else "")
    return result, buf.getvalue()


__all__ = ["compare", "load_rgb", "regions"]
