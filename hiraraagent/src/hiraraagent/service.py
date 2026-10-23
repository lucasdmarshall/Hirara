"""HTTP front end.

    uvicorn hiraraagent.service:app --host 0.0.0.0 --port 9600

Agent side: ``POST /memory``, ``/ask_human``, ``/schedule``, ``/wait_until``.

Human side: ``GET /human`` is a small page listing pending questions with
answer buttons; ``GET /human/pending`` and ``POST /human/answer`` are the same
as JSON for scripts and chat bots. Set HG_HUMAN_TOKEN to require a token on
the human side (as ``?token=``, a form field, or ``Authorization: Bearer``),
and do not give that token to the agent: the tools deliberately have no way
to answer their own questions.
"""

from __future__ import annotations

import hmac
from html import escape
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from .errors import AgentError
from .tools import Toolset

_toolset = Toolset.from_env()

app = FastAPI(title="hiraraagent", version="0.1.0")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryRequest(_Body):
    action: str
    key: str | None = None
    value: Any = None
    tags: list[str] | None = None
    ttl_seconds: float | None = None
    query: str | None = None
    limit: int = 20
    offset: int = 0
    namespace: str | None = None


class AskRequest(_Body):
    action: str
    question: str | None = None
    kind: str = "question"
    options: list[str] | None = None
    allow_free_text: bool = False
    context: str | None = None
    urgency: str = "normal"
    expires_in_seconds: float | None = None
    request_id: str | None = None
    namespace: str | None = None


class ScheduleRequest(_Body):
    action: str
    title: str | None = None
    note: str | None = None
    at: str | None = None
    in_seconds: float | None = None
    repeat_seconds: float | None = None
    reminder_id: str | None = None
    include_done: bool = False
    namespace: str | None = None


class WaitRequest(_Body):
    request_id: str | None = None
    reminder_due: bool = False
    at: str | None = None
    in_seconds: float | None = None
    max_wait: float | None = None
    namespace: str | None = None


class AnswerRequest(_Body):
    request_id: str
    answer: str
    answered_by: str | None = None
    comment: str | None = None


@app.get("/health")
async def health() -> dict:
    return _toolset.health()


@app.get("/schemas")
async def schemas() -> dict:
    return {"tools": _toolset.schemas()}


@app.post("/memory")
async def memory(request: MemoryRequest) -> dict:
    return await _toolset.memory(**request.model_dump())


@app.post("/ask_human")
async def ask_human(request: AskRequest) -> dict:
    return await _toolset.ask_human(**request.model_dump())


@app.post("/schedule")
async def schedule(request: ScheduleRequest) -> dict:
    return await _toolset.schedule(**request.model_dump())


@app.post("/wait_until")
async def wait_until(request: WaitRequest) -> dict:
    return await _toolset.wait_until(**request.model_dump())


# --- the human side -------------------------------------------------------------------

def _authorised(request: Request, form_token: str | None = None) -> bool:
    expected = _toolset.config.human_token
    if not expected:
        return True
    given = form_token or request.query_params.get("token") or ""
    auth = request.headers.get("authorization", "")
    if not given and auth.lower().startswith("bearer "):
        given = auth[7:]
    return hmac.compare_digest(given.encode(), expected.encode())


def _denied():
    return JSONResponse({"error": "a valid human token is required"}, status_code=401)


@app.get("/human/pending")
async def human_pending(request: Request, namespace: str | None = None):
    if not _authorised(request):
        return _denied()
    reqs = _toolset.store.req_list(namespace, "pending")
    return {"requests": reqs, "count": len(reqs)}


@app.post("/human/answer")
async def human_answer(request: Request, body: AnswerRequest):
    if not _authorised(request):
        return _denied()
    try:
        return _toolset.store.req_answer(body.request_id, body.answer.strip(), body.answered_by,
                                         body.comment)
    except AgentError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/human/form")
async def human_form(request: Request, request_id: str = Form(...), answer: str = Form(...),
                     answered_by: str | None = Form(None), comment: str | None = Form(None),
                     token: str | None = Form(None)):
    if not _authorised(request, token):
        return _denied()
    try:
        _toolset.store.req_answer(request_id, answer.strip(), answered_by or "web", comment or None)
    except AgentError as exc:
        return HTMLResponse(_page([], error=str(exc), token=token), status_code=400)
    suffix = f"?token={escape(token)}" if token else ""
    return RedirectResponse(f"/human{suffix}", status_code=303)


@app.get("/human", response_class=HTMLResponse)
async def human_page(request: Request):
    if not _authorised(request):
        return HTMLResponse("<h1>401</h1><p>A valid token is required.</p>", status_code=401)
    reqs = _toolset.store.req_list(None, "pending")
    return HTMLResponse(_page(reqs, token=request.query_params.get("token")))


def _page(reqs: list[dict], *, error: str | None = None, token: str | None = None) -> str:
    cards = []
    hidden = f'<input type="hidden" name="token" value="{escape(token)}">' if token else ""
    for r in reqs:
        rid = escape(r["request_id"])
        buttons = "".join(
            f'<button name="answer" value="{escape(o)}">{escape(o)}</button>'
            for o in (r["options"] or []))
        free = ""
        if not r["options"] or r["allow_free_text"]:
            free = ('<input name="answer" placeholder="Your answer" required>'
                    '<button>Send</button>') if not r["options"] else (
                    '<input name="answer" placeholder="Or type an answer">')
        context = f'<pre>{escape(r["context"])}</pre>' if r.get("context") else ""
        cards.append(
            f'<section class="card {escape(r["urgency"])}">'
            f'<div class="meta">{escape(r["kind"])} · {escape(r["urgency"])} · '
            f'{escape(r["namespace"])} · {escape(r["created"] or "")}</div>'
            f'<h2>{escape(r["question"])}</h2>{context}'
            f'<form method="post" action="/human/form">{hidden}'
            f'<input type="hidden" name="request_id" value="{rid}">'
            f'<div class="row">{buttons}{free}</div>'
            f'<input name="comment" placeholder="Comment (optional)"></form></section>')
    body = "".join(cards) or '<p class="empty">Nothing is waiting for you.</p>'
    err = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30"><title>Agent requests</title>
<style>
:root {{ --bg:#f6f7f9; --fg:#1b1d21; --card:#fff; --muted:#667; --line:#dde; --accent:#2d5bd7; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#15171b; --fg:#e8e9ec; --card:#1e2127; --muted:#99a; --line:#333842; --accent:#7aa2ff; }} }}
body {{ font: 16px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--fg); margin:0; padding:16px; }}
main {{ max-width: 760px; margin: 0 auto; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:12px 0; }}
.card.high {{ border-left:4px solid #d33; }}
.meta {{ color:var(--muted); font-size:13px; }}
h2 {{ font-size:18px; margin:6px 0 10px; }}
pre {{ white-space:pre-wrap; background:var(--bg); padding:8px; border-radius:6px; font-size:14px; }}
.row {{ display:flex; flex-wrap:wrap; gap:8px; margin:8px 0; }}
button {{ background:var(--accent); color:#fff; border:0; border-radius:6px; padding:8px 14px; font-size:15px; cursor:pointer; }}
input {{ flex:1; min-width:180px; padding:8px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); }}
.empty {{ color:var(--muted); }} .error {{ color:#d33; }}
</style></head><body><main><h1>Agent requests</h1>{err}{body}</main></body></html>"""
