"""HTML + CSS to PDF for agent-authored documents (resumes, letters, reports).

Renders with xhtml2pdf on top of reportlab: document CSS (type, color,
margins, tables, borders), not a browser engine. Images come from the caller
as base64 (an ``images`` map or a ``data:image`` URI). Remote and filesystem
URLs in the HTML are rejected so a document cannot fetch arbitrary hosts.
"""

from __future__ import annotations

import base64
import binascii
import html
import io
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from .maker import MakeError, _HTML_PAGE_SIZES, _pisa

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_REMOTE_ATTR = re.compile(
    r"""(?:src|href)\s*=\s*['"]?\s*(?:https?:|file:|ftp:)""",
    re.IGNORECASE,
)
_REMOTE_CSS = re.compile(
    r"""url\(\s*['"]?\s*(?:https?:|file:|ftp:)""",
    re.IGNORECASE,
)
_DATA_URI = re.compile(
    r"^data:image/(?:png|jpe?g|gif);base64,",
    re.IGNORECASE,
)


def _sniff_image(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    raise MakeError("image must be PNG, JPEG, or GIF")


def _decode_b64(raw: str, *, label: str) -> bytes:
    text = raw.strip()
    if text.lower().startswith("data:"):
        _, _, text = text.partition(",")
    try:
        return base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise MakeError(f"invalid base64 for {label}") from exc


def _safe_image_name(name: str) -> str:
    cleaned = (name or "").strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ".." in Path(cleaned).parts:
        raise MakeError(f"invalid image name: {name!r}")
    base = Path(cleaned).name
    if not _NAME_RE.fullmatch(base):
        raise MakeError(
            f"image name must be a simple filename (letters, digits, . _ -): {name!r}"
        )
    return base


def _prepare_images(
    images: dict[str, str] | None,
    *,
    max_images: int,
    max_bytes: int,
) -> dict[str, bytes]:
    if not images:
        return {}
    if not isinstance(images, dict):
        raise MakeError("images must be an object of filename to base64")
    if len(images) > max_images:
        raise MakeError(f"too many images (max {max_images})")

    out: dict[str, bytes] = {}
    total = 0
    for name, value in images.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise MakeError("images must be string filenames to base64 strings")
        key = _safe_image_name(name)
        if key in out:
            raise MakeError(f"duplicate image name: {key}")
        data = _decode_b64(value, label=key)
        if not data:
            raise MakeError(f"image {key} is empty")
        _sniff_image(data)
        total += len(data)
        if total > max_bytes:
            raise MakeError(f"images exceed {max_bytes} bytes")
        out[key] = data
    return out


def _reject_remote(document: str) -> None:
    if _REMOTE_ATTR.search(document) or _REMOTE_CSS.search(document):
        raise MakeError(
            "remote and filesystem URLs are blocked in HTML/CSS. "
            "Embed images with the images map "
            '(<img src="photo.png">) or a data:image URI, and put CSS in the css field.'
        )


def _compose_document(
    content: str,
    *,
    css: str | None,
    title: str | None,
    author: str | None,
    subject: str | None,
    page_size: str,
) -> str:
    size = _HTML_PAGE_SIZES.get(page_size.upper())
    if size is None:
        raise MakeError(f"unsupported page_size: {page_size}")

    style = f"@page {{ size: {size}; margin: 1.6cm; }}\n"
    if css:
        style += css

    style_tag = f"<style>{style}</style>"
    lowered = content.lower()
    if "<html" in lowered:
        if "<head" in lowered:
            return re.sub(
                r"(<head[^>]*>)",
                rf"\1{style_tag}",
                content,
                count=1,
                flags=re.IGNORECASE,
            )
        return re.sub(
            r"(<html[^>]*>)",
            rf"\1<head>{style_tag}</head>",
            content,
            count=1,
            flags=re.IGNORECASE,
        )

    head: list[str] = [style_tag]
    if title:
        head.append(f"<title>{html.escape(title)}</title>")
    if author:
        head.append(
            f'<meta name="author" content="{html.escape(author, quote=True)}"/>'
        )
    if subject:
        head.append(
            f'<meta name="subject" content="{html.escape(subject, quote=True)}"/>'
        )
    return f"<html><head>{''.join(head)}</head><body>{content}</body></html>"


def _materialize(images: dict[str, bytes], directory: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, data in images.items():
        ext = _sniff_image(data)
        # Keep the caller's filename so <img src="photo.png"> resolves.
        dest = directory / name
        if dest.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"}:
            dest = directory / f"{name}.{ext}"
            paths[f"{name}.{ext}"] = dest
        dest.write_bytes(data)
        paths[name] = dest
    return paths


def _decode_data_uri(uri: str, *, max_bytes: int) -> bytes:
    if not _DATA_URI.match(uri):
        raise MakeError("only base64 data:image/png|jpeg|gif URIs are allowed")
    _, _, payload = uri.partition(",")
    try:
        data = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise MakeError("invalid image data URI") from exc
    if len(data) > max_bytes:
        raise MakeError(f"image exceeds {max_bytes} bytes")
    _sniff_image(data)
    return data


def build_html_pdf(
    content: str,
    *,
    css: str | None = None,
    images: dict[str, str] | None = None,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    page_size: str = "A4",
    max_images: int = 24,
    max_image_bytes: int = 8_000_000,
) -> bytes:
    """Render HTML (and optional CSS) to PDF bytes."""
    if content is None or not str(content).strip():
        raise MakeError("html is required")

    prepared = _prepare_images(
        images, max_images=max_images, max_bytes=max_image_bytes
    )
    document = _compose_document(
        str(content),
        css=css,
        title=title,
        author=author,
        subject=subject,
        page_size=page_size,
    )
    _reject_remote(document)

    pisa = _pisa()
    with tempfile.TemporaryDirectory(prefix="hirarapdf-html-") as tmp:
        root = Path(tmp)
        files = _materialize(prepared, root)
        spilled = 0

        def link_callback(uri: str, rel: str) -> str:
            nonlocal spilled
            raw = unquote(uri or "").strip()
            if not raw or raw.startswith("#"):
                return raw
            parsed = urlparse(raw)
            if parsed.scheme in {"http", "https", "file", "ftp"}:
                raise MakeError(
                    "remote and filesystem images are blocked; "
                    "pass images as base64 or a data:image URI"
                )
            if parsed.scheme == "data" or raw.lower().startswith("data:"):
                data = _decode_data_uri(raw, max_bytes=max_image_bytes)
                spilled += len(data)
                if spilled > max_image_bytes:
                    raise MakeError(f"images exceed {max_image_bytes} bytes")
                ext = _sniff_image(data)
                dest = root / f"inline-{spilled}.{ext}"
                dest.write_bytes(data)
                return str(dest)

            name = Path(parsed.path or raw).name
            if name in files:
                return str(files[name])
            # xhtml2pdf asks for the document itself sometimes.
            if name in {"", "."} or raw.startswith("<"):
                return raw
            raise MakeError(
                f"image {raw!r} was not provided. "
                'Add it to images as {"'
                + name
                + '": "<base64>"} or use a data:image URI.'
            )

        out = io.BytesIO()
        try:
            status = pisa.CreatePDF(
                src=document,
                dest=out,
                encoding="utf-8",
                link_callback=link_callback,
            )
        except MakeError:
            raise
        except Exception as exc:  # noqa: BLE001 — bad HTML stays in the envelope
            raise MakeError(f"could not render HTML to PDF: {exc}") from exc
        if getattr(status, "err", 0):
            raise MakeError(
                f"could not render HTML to PDF ({status.err} error(s))"
            )
        data = out.getvalue()
    if not data.startswith(b"%PDF-"):
        raise MakeError("HTML renderer did not produce a PDF")
    return data


__all__ = ["build_html_pdf"]
