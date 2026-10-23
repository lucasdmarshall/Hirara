"""email_read: .eml, .msg and mbox files to structured, readable data.

Mail arrives as a MIME tree of encodings, charsets, alternatives and
attachments; an agent wants the people, the subject, the readable body, the
links and what is attached. Attachments that are Office documents or text
are read in place (``read_attachments``), so a forwarded report does not need
a second round trip. Everything here is untrusted input: nothing is fetched,
nothing executed, and HTML is only ever turned into text.
"""

from __future__ import annotations

import hashlib
import mailbox
import os
import re
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

from .readers import ReaderError, read_office

URL_RX = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
OFFICE_EXT = (".docx", ".pptx", ".xlsx")
MAX_LINKS = 200


class _HtmlText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table",
             "blockquote", "section", "article", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.lower().startswith(("http://", "https://")):
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, list[str]]:
    parser = _HtmlText()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — malformed mail HTML is the norm
        pass
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, blank = [], 0
    for line in lines:
        blank = blank + 1 if not line else 0
        if blank <= 1:
            out.append(line)
    return "\n".join(out).strip(), parser.links


def _addresses(value) -> list[dict]:
    if not value:
        return []
    return [{"name": name or None, "email": addr} for name, addr in getaddresses([str(value)]) if addr]


def _date(value) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(str(value)).isoformat()
    except (TypeError, ValueError):
        return str(value)


def _uniq(items) -> list[str]:
    seen, out = set(), []
    for item in items:
        item = item.rstrip(".,;:")
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:MAX_LINKS]


def _attachment(name: str | None, ctype: str, payload: bytes, *, read: bool, max_chars: int,
                max_rows: int) -> dict:
    item = {
        "filename": name,
        "content_type": ctype,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "text": None,
    }
    if not read:
        return item
    lower = (name or "").lower()
    try:
        if lower.endswith(OFFICE_EXT):
            doc = read_office(payload, filename=name, max_rows=max_rows)
            item["text"] = doc.markdown[:max_chars]
        elif ctype.startswith("text/") or lower.endswith((".txt", ".csv", ".md", ".json", ".log")):
            item["text"] = payload.decode("utf-8", "replace")[:max_chars]
    except ReaderError as exc:
        item["read_error"] = str(exc)
    return item


def _from_email(msg: EmailMessage, *, read_attachments: bool, include_html: bool,
                max_chars: int, max_rows: int) -> dict:
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    body_text, links = "", []
    html_raw = None
    if plain is not None:
        body_text = plain.get_content()
    if html is not None:
        html_raw = html.get_content()
        converted, links = html_to_text(html_raw)
        if not body_text.strip():
            body_text = converted
    links = _uniq(links + URL_RX.findall(body_text))

    attachments = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        attachments.append(_attachment(part.get_filename(), part.get_content_type(), payload,
                                       read=read_attachments, max_chars=max_chars,
                                       max_rows=max_rows))
    received = msg.get_all("Received") or []
    truncated = len(body_text) > max_chars
    return {
        "subject": msg.get("Subject"),
        "from": _addresses(msg.get("From")),
        "to": _addresses(msg.get("To")),
        "cc": _addresses(msg.get("Cc")),
        "reply_to": _addresses(msg.get("Reply-To")),
        "date": _date(msg.get("Date")),
        "message_id": msg.get("Message-ID"),
        "in_reply_to": msg.get("In-Reply-To"),
        "references": (msg.get("References") or "").split() or [],
        "authentication_results": msg.get_all("Authentication-Results") or [],
        "received_hops": len(received),
        "body_text": body_text[:max_chars],
        "body_html": html_raw[:max_chars] if include_html and html_raw else None,
        "links": links,
        "attachments": attachments,
        "truncated": truncated,
    }


def _from_msg(data: bytes, *, read_attachments: bool, include_html: bool, max_chars: int,
              max_rows: int) -> dict:
    try:
        import extract_msg
    except ImportError as exc:
        raise ReaderError(
            "Outlook .msg support needs extract-msg: pip install 'hirarareader[msg]'"
        ) from exc
    fd, path = tempfile.mkstemp(suffix=".msg")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        msg = extract_msg.openMsg(path)
        try:
            body_text = msg.body or ""
            html_raw = msg.htmlBody.decode("utf-8", "replace") if isinstance(msg.htmlBody, bytes) else msg.htmlBody
            links: list[str] = []
            if html_raw:
                converted, links = html_to_text(html_raw)
                if not body_text.strip():
                    body_text = converted
            attachments = []
            for att in msg.attachments:
                payload = att.data if isinstance(att.data, bytes) else b""
                attachments.append(_attachment(
                    att.longFilename or att.shortFilename, getattr(att, "mimetype", None)
                    or "application/octet-stream", payload, read=read_attachments,
                    max_chars=max_chars, max_rows=max_rows))
            return {
                "subject": msg.subject,
                "from": _addresses(msg.sender),
                "to": _addresses(msg.to),
                "cc": _addresses(msg.cc),
                "reply_to": [],
                "date": msg.date.isoformat() if hasattr(msg.date, "isoformat") else _date(msg.date),
                "message_id": getattr(msg, "messageId", None),
                "in_reply_to": None,
                "references": [],
                "authentication_results": [],
                "received_hops": None,
                "body_text": body_text[:max_chars],
                "body_html": html_raw[:max_chars] if include_html and html_raw else None,
                "links": _uniq(links + URL_RX.findall(body_text)),
                "attachments": attachments,
                "truncated": len(body_text) > max_chars,
            }
        finally:
            msg.close()
    finally:
        os.unlink(path)


def detect(data: bytes, filename: str | None) -> str:
    name = (filename or "").lower()
    if name.endswith(".msg") or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "msg"
    if name.endswith((".mbox", ".mbx")) or data[:5] == b"From ":
        return "mbox"
    return "eml"


def read_email(data: bytes, *, filename: str | None = None, read_attachments: bool = True,
               include_html: bool = False, max_messages: int = 50, max_chars: int = 200_000,
               max_rows: int = 2000) -> dict:
    if not data:
        raise ReaderError("the file is empty")
    kind = detect(data, filename)
    opts = {"read_attachments": read_attachments, "include_html": include_html,
            "max_chars": max_chars, "max_rows": max_rows}
    if kind == "msg":
        messages = [_from_msg(data, **opts)]
        total = 1
    elif kind == "mbox":
        fd, path = tempfile.mkstemp(suffix=".mbox")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            box = mailbox.mbox(path, factory=lambda f: BytesParser(policy=policy.default).parse(f))
            messages, total = [], 0
            for msg in box:
                total += 1
                if len(messages) < max(1, int(max_messages)):
                    messages.append(_from_email(msg, **opts))
            box.close()
        finally:
            os.unlink(path)
    else:
        msg = BytesParser(policy=policy.default).parsebytes(data)
        if not msg.keys():
            raise ReaderError("not an email message (no headers found)")
        messages = [_from_email(msg, **opts)]
        total = 1
    return {"format": kind, "messages": messages, "count": len(messages), "total": total}


def summary(result: dict) -> str:
    lines = []
    for m in result["messages"][:20]:
        sender = ", ".join(a["email"] for a in m["from"]) or "?"
        lines.append(f"{m['date'] or '?'} | {sender} | {m['subject'] or '(no subject)'}"
                     + (f" | {len(m['attachments'])} attachment(s)" if m["attachments"] else ""))
    if result["total"] > len(result["messages"]):
        lines.append(f"… {result['total'] - len(result['messages'])} more message(s)")
    return "\n".join(lines)


__all__ = ["detect", "html_to_text", "read_email", "summary"]
