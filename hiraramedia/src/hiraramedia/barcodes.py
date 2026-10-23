"""barcode_read and qr_generate.

Vision models misread QR codes and barcodes: the payload is a pattern, not
text. zbar decodes them exactly (QR, EAN / UPC, Code 128 / 39, ITF, DataBar,
PDF417 where built in). If nothing is found the image is retried in greyscale,
upscaled and with contrast stretched, since phone photos of codes are often
small and flat. QR codes are generated with segno (pure Python).
"""

from __future__ import annotations

import base64
import io
import re

from PIL import Image, ImageOps

from .errors import MediaError


def _kind(text: str) -> str:
    low = text.lower()
    if re.match(r"^https?://", low):
        return "url"
    if low.startswith("wifi:"):
        return "wifi"
    if low.startswith("begin:vcard"):
        return "vcard"
    if low.startswith("mailto:"):
        return "email"
    if low.startswith("tel:"):
        return "phone"
    if low.startswith("begin:vevent"):
        return "calendar"
    if low.startswith("geo:"):
        return "location"
    return "text"


def read(img: Image.Image) -> dict:
    try:
        from pyzbar import pyzbar
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MediaError("barcode reading needs pyzbar and the zbar library "
                         "(pip install pyzbar; apt-get install libzbar0)") from exc

    attempts = [("original", img)]
    grey = ImageOps.grayscale(img)
    attempts.append(("greyscale", ImageOps.autocontrast(grey)))
    if max(img.size) < 1600:
        attempts.append(("upscaled", ImageOps.autocontrast(grey).resize(
            (img.size[0] * 2, img.size[1] * 2), Image.LANCZOS)))
    for name, candidate in attempts:
        try:
            found = pyzbar.decode(candidate)
        except Exception as exc:  # noqa: BLE001
            raise MediaError(f"barcode decoding failed: {exc}") from exc
        if found:
            scale = 2 if name == "upscaled" else 1
            codes = []
            for f in found:
                raw = f.data
                try:
                    text, binary = raw.decode("utf-8"), False
                except UnicodeDecodeError:
                    text, binary = base64.b64encode(raw).decode(), True
                codes.append({
                    "type": f.type,
                    "data": text,
                    "binary": binary,
                    "kind": "binary" if binary else _kind(text),
                    "rect": {"x": f.rect.left // scale, "y": f.rect.top // scale,
                             "width": f.rect.width // scale, "height": f.rect.height // scale},
                    "orientation": getattr(f, "orientation", None),
                    "quality": getattr(f, "quality", None),
                })
            return {"codes": codes, "count": len(codes), "pass": name}
    return {"codes": [], "count": 0, "pass": None}


def generate(data: str, *, error: str = "M", scale: int = 8, border: int = 4, fmt: str = "png",
             dark: str = "#000000", light: str = "#ffffff", micro: bool = False) -> tuple[bytes, dict]:
    try:
        import segno
    except ImportError as exc:  # pragma: no cover
        raise MediaError("qr_generate needs segno: pip install segno") from exc
    if not data:
        raise MediaError("data is required")
    if len(data) > 4000:
        raise MediaError("data is longer than a QR code can hold (about 2,900 bytes)")
    if error.upper() not in ("L", "M", "Q", "H"):
        raise MediaError("error_correction must be L, M, Q or H")
    if fmt not in ("png", "svg"):
        raise MediaError("format must be png or svg")
    if not 1 <= int(scale) <= 50 or not 0 <= int(border) <= 20:
        raise MediaError("scale must be 1..50 and border 0..20")
    try:
        qr = segno.make(data, error=error.lower(), micro=micro or None, boost_error=False)
    except Exception as exc:  # noqa: BLE001 — segno raises DataOverflowError and friends
        raise MediaError(f"cannot encode: {exc}") from exc
    buf = io.BytesIO()
    qr.save(buf, kind=fmt, scale=int(scale), border=int(border), dark=dark, light=light)
    width, height = qr.symbol_size(scale=int(scale), border=int(border))
    return buf.getvalue(), {"version": str(qr.version), "error_correction": qr.error,
                            "modules": qr.symbol_size(scale=1, border=0)[0],
                            "width": width, "height": height, "kind": _kind(data)}


__all__ = ["generate", "read"]
