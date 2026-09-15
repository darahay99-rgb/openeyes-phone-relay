"""OpenEyes Phone Relay — public HTTPS bridge between a phone and a PC.

WHY THIS EXISTS
---------------
The PC running the OpenEyes Local 3D Viewer usually cannot accept inbound
connections: office Wi-Fi (e.g. an IoT SSID) isolates clients, there is no
port forwarding, and the phone may not even be on the same network. So the
PC never listens for the phone. Instead BOTH sides dial OUT to this relay
over ordinary HTTPS:

    phone  --POST /api/session/{id}/scan-->  RELAY  --SSE/poll-->  PC viewer

Nothing here needs an inbound port on the PC, a LAN route, a VPN, or a
shared subnet.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* It never sees, stores or serves 3D models, manifests or project data.
  The only thing that crosses it is a short Board ID string.
* It does not change the printed Board QR payload. Printed labels stay a
  bare Board ID (e.g. 20260914122851-069) exactly as before. This relay's
  pairing QR is a completely separate, temporary thing.
* It keeps no database and writes no files. All state is in memory and
  expires. Restarting the service simply unpairs everyone.

API CONTRACT
------------
This file implements precisely the endpoints the existing viewer client in
``app/phone_viewer.py`` already calls. Do not rename them.

  GET  /health                              liveness probe
  POST /api/session                         PC mints a session -> {session_id}
  POST /api/session/{sid}/keepalive         PC heartbeat -> {phone_paired}
  GET  /api/session/{sid}/events?after=N    PC SSE stream ("ready", "scan")
  GET  /api/session/{sid}/poll?after=N      PC long poll -> {events:[...]}
  GET  /scan?session={sid}                  phone scanner page (pairing QR target)
  POST /api/session/{sid}/scan              phone submits a Board ID
  POST /api/session/{sid}/ack               PC reports FOUND / NOT_FOUND
  GET  /api/session/{sid}/ack?seq=N         phone waits for that verdict
  GET  /static/jsQR.js                      vendored QR decoder for the phone page
  POST /api/publish/{token}                 PC uploads a cabinet (model + manifest)
  GET  /p/{token}                           the phone's OWN full 3D viewer
  GET  /static/probe-qr.png                 known-good QR for the on-phone self test
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from phone_viewer import render_phone_viewer
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)

APP_VERSION = "2.7.0"

app = FastAPI(title="OpenEyes Phone Relay", version=APP_VERSION)

# The PC viewer page is served from http://127.0.0.1:8000 while this relay
# lives on https://<something>.up.railway.app, so every call from the viewer
# is cross-origin. Only short Board IDs and opaque session ids ever pass
# through here and there are no cookies or credentials, so a permissive
# policy is safe and avoids a whole class of "it works in curl but not in
# the browser" confusion.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = _APP_DIR / "static"


def _find_jsqr() -> Path | None:
    """Locate jsQR.js in any of the places an upload realistically puts it."""
    for candidate in (STATIC_DIR / "jsQR.js", _APP_DIR / "jsQR.js",
                      _APP_DIR / "static" / "jsqr.js", _APP_DIR / "jsqr.js"):
        if candidate.is_file():
            return candidate
    return None

# --- Tunables (override with Railway environment variables) ----------------
SESSION_TTL = int(os.environ.get("OPENEYES_SESSION_TTL", "7200"))      # 2h idle
MAX_EVENTS = int(os.environ.get("OPENEYES_MAX_EVENTS", "200"))         # ring size
MAX_SESSIONS = int(os.environ.get("OPENEYES_MAX_SESSIONS", "500"))     # abuse cap
POLL_TIMEOUT = int(os.environ.get("OPENEYES_POLL_TIMEOUT", "25"))      # long poll
ACK_RESULTS = {"RECEIVED", "FOUND", "SELECTED", "NOT_FOUND"}
ACK_TIMEOUT = int(os.environ.get("OPENEYES_ACK_TIMEOUT", "8"))

SSE_HEARTBEAT = int(os.environ.get("OPENEYES_SSE_HEARTBEAT", "20"))    # keep alive

# A Board ID is short, printable and has no spaces. This is a sanity filter,
# not a security boundary — the viewer treats anything it receives as a
# lookup key and simply reports "Board not found" when it does not match.
BOARD_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class Session:
    """One PC viewer window. Lives in memory only."""

    __slots__ = ("sid", "created", "last_seen", "phone_paired", "events", "seq",
                 "signal", "ack", "ack_signal")

    def __init__(self, sid: str) -> None:
        now = time.time()
        self.sid = sid
        self.created = now
        self.last_seen = now
        self.phone_paired = False
        self.events: list[dict] = []
        self.seq = 0
        # Set whenever a new scan arrives; SSE and long poll both wait on it.
        self.signal = asyncio.Event()
        # The PC viewer's verdict for the most recent scan. This is what lets
        # the phone say "board selected on the PC" instead of the much weaker
        # "the relay accepted my POST".
        self.ack: dict | None = None
        self.ack_signal = asyncio.Event()

    def touch(self) -> None:
        self.last_seen = time.time()

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.last_seen > SESSION_TTL

    def add_scan(self, board_id: str, source: str = "phone") -> dict:
        self.seq += 1
        event = {
            "seq": self.seq,
            "board_id": board_id,
            "source": source,
            "ts": int(time.time()),
        }
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        self.phone_paired = True
        self.ack = None
        self.touch()
        # Wake every waiter, then immediately re-arm for the next scan.
        self.signal.set()
        self.signal = asyncio.Event()
        return event

    def since(self, after: int) -> list[dict]:
        return [e for e in self.events if e["seq"] > after]

    def set_ack(self, seq: int, board_id: str, result: str) -> dict:
        self.ack = {
            "seq": seq,
            "board_id": board_id,
            "result": result,
            "ts": int(time.time()),
        }
        self.touch()
        self.ack_signal.set()
        self.ack_signal = asyncio.Event()
        return self.ack


SESSIONS: dict[str, Session] = {}


def _sweep() -> None:
    """Drop idle sessions. Called on every entry point — no background task,
    nothing to crash, and nothing to keep a Railway container awake."""
    now = time.time()
    for sid in [s for s, sess in SESSIONS.items() if sess.expired(now)]:
        SESSIONS.pop(sid, None)


def _get(sid: str) -> Session:
    _sweep()
    if not SESSION_ID_RE.match(sid or ""):
        raise HTTPException(status_code=404, detail="Unknown session")
    session = SESSIONS.get(sid)
    if session is None:
        # 404 is meaningful to the viewer: it means "mint a new session".
        raise HTTPException(status_code=404, detail="Unknown session")
    session.touch()
    return session


def _normalize_board_id(raw: str) -> str:
    """Accept what a camera actually reads.

    Current printed labels encode the bare Board ID, which is the normal
    path and passes through untouched. Older labels from earlier versions
    encoded a URL like ``/local/view/<project>?part=<board id>``; rather
    than dead-ending those, the Board ID is lifted out of the query string.
    Nothing about the printed label format changes because of this — it is
    purely a tolerant reader.
    """
    text = (raw or "").strip().strip("\r\n\t ")
    if not text:
        return ""
    if "://" in text or text.startswith("/"):
        try:
            query = parse_qs(urlparse(text).query)
            for key in ("part", "board", "board_id", "id"):
                if query.get(key):
                    text = query[key][0].strip()
                    break
        except ValueError:
            pass
    return text


# ---------------------------------------------------------------------------
# PUBLISHED PROJECTS - the phone runs the full 3D viewer itself
# ---------------------------------------------------------------------------
# Until now the phone was only a scanner: it read a Board ID and pushed it to
# the PC, and the PC did the 3D. That forces a worker to walk back to the PC
# for every board. Publishing puts the SAME viewer on the phone.
#
# The PC uploads two small files once (a DAE/GLB plus its manifest - about
# 0.2 MB for a 300-board unit, because boards are plain boxes with no
# textures). The phone then opens /p/{token}, and after the first load the
# service worker keeps the model on the device, so later opens work with a
# weak signal or none at all.
#
# STORAGE: in memory for now. A redeploy or an idle container clears it and
# the PC must publish again. Mount a Railway volume and set OPENEYES_DATA_DIR
# to make it survive; the code below writes through to that directory when it
# is set, so switching is a config change, not a rewrite.

PUBLISH_TTL = int(os.environ.get("OPENEYES_PUBLISH_TTL", str(30 * 24 * 3600)))
MAX_MODEL_BYTES = int(os.environ.get("OPENEYES_MAX_MODEL_BYTES", str(64 * 1024 * 1024)))
DATA_DIR = os.environ.get("OPENEYES_DATA_DIR", "").strip()

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class Project:
    """One published cabinet. Small enough to hold in memory comfortably."""

    __slots__ = ("token", "title", "detail", "model_name", "model", "manifest",
                 "version", "created", "last_seen")

    def __init__(self, token: str) -> None:
        now = time.time()
        self.token = token
        self.title = "OpenEyes Project"
        self.detail = ""
        self.model_name = "model.dae"
        self.model = b""
        self.manifest = b"{}"
        self.version = ""
        self.created = now
        self.last_seen = now

    def touch(self) -> None:
        self.last_seen = time.time()

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.last_seen > PUBLISH_TTL


PROJECTS: dict[str, Project] = {}


def _project_dir(token: str) -> Path | None:
    if not DATA_DIR:
        return None
    return Path(DATA_DIR) / "projects" / token


def _persist(project: Project) -> None:
    """Write through to disk when a volume is configured. Best effort."""
    directory = _project_dir(project.token)
    if directory is None:
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "meta.json").write_text(json.dumps({
            "title": project.title, "detail": project.detail,
            "model_name": project.model_name, "version": project.version,
            "created": project.created,
        }), encoding="utf-8")
        (directory / "manifest.json").write_bytes(project.manifest)
        (directory / project.model_name).write_bytes(project.model)
    except OSError as exc:
        print(f"[publish] could not persist {project.token}: {exc}", flush=True)


def _restore(token: str) -> Project | None:
    directory = _project_dir(token)
    if directory is None or not (directory / "meta.json").is_file():
        return None
    try:
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        project = Project(token)
        project.title = meta.get("title", project.title)
        project.detail = meta.get("detail", "")
        project.model_name = meta.get("model_name", "model.dae")
        project.version = meta.get("version", "")
        project.created = meta.get("created", time.time())
        project.manifest = (directory / "manifest.json").read_bytes()
        project.model = (directory / project.model_name).read_bytes()
        PROJECTS[token] = project
        return project
    except (OSError, ValueError) as exc:
        print(f"[publish] could not restore {token}: {exc}", flush=True)
        return None


def _get_project(token: str) -> Project:
    if not TOKEN_RE.match(token or ""):
        raise HTTPException(status_code=404, detail="Project not found")
    now = time.time()
    for dead in [t for t, p in PROJECTS.items() if p.expired(now)]:
        PROJECTS.pop(dead, None)
    project = PROJECTS.get(token) or _restore(token)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project.touch()
    return project



# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    _sweep()
    jsqr = _find_jsqr()
    return {
        "ok": True,
        "service": "openeyes-phone-relay",
        "version": APP_VERSION,
        "sessions": len(SESSIONS),
        "uptime_s": int(time.time() - START_TIME),
        # If jsqr_bytes is 0 or missing, static/jsQR.js did not reach the
        # deployment and the camera fallback cannot work. Check this first.
        "jsqr_present": jsqr is not None,
        "jsqr_bytes": jsqr.stat().st_size if jsqr else 0,
        # Where it was found, so a flattened upload is obvious at a glance.
        "jsqr_path": (str(jsqr.relative_to(_APP_DIR)) if jsqr else None),
    }


START_TIME = time.time()


@app.get("/")
def root():
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<div style=\"font-family:system-ui,Arial,sans-serif;max-width:560px;"
        "margin:60px auto;padding:0 20px;line-height:1.6\">"
        "<h2>OpenEyes Phone Relay</h2>"
        "<p>This service only forwards Board IDs from a phone to a paired PC "
        "viewer. There is nothing to open here directly.</p>"
        "<p>On the PC, open the OpenEyes Local 3D Viewer and press "
        "<b>PAIR PHONE</b>, then scan the pairing QR it shows.</p>"
        "<p><a href='/health'>/health</a></p></div>"
    )


@app.get("/static/probe-qr.png")
def static_probe_qr():
    """A known-good QR the phone can decode with no camera involved.

    It carries a fixed, obviously-fake id so it can never be mistaken for a
    real board. If the phone can decode this but not a printed label, the
    decoder is fine and the problem is optics: focus, glare, or label size.
    """
    import qrcode
    import qrcode.image.pure

    img = qrcode.make(
        "OPENEYES-SELFTEST-0001",
        image_factory=qrcode.image.pure.PyPNGImage,
        border=4,
        box_size=6,
    )
    buf = io.BytesIO()
    img.save(buf)
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


def _serve_jsqr():
    path = _find_jsqr()
    if path is None:
        raise HTTPException(status_code=404, detail="jsQR.js is not bundled")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/static/jsQR.js")
def static_jsqr():
    return _serve_jsqr()


@app.get("/jsQR.js")
def root_jsqr():
    """Same file, root path — served so a flattened upload still works."""
    return _serve_jsqr()


# ---------------------------------------------------------------------------
# PC side
# ---------------------------------------------------------------------------
@app.post("/api/session")
async def create_session():
    """The PC viewer mints a channel for itself. No auth: the session id is
    the capability, and it is 32 random hex characters."""
    _sweep()
    if len(SESSIONS) >= MAX_SESSIONS:
        # Evict the coldest session rather than refusing a legitimate user.
        oldest = min(SESSIONS.values(), key=lambda s: s.last_seen)
        SESSIONS.pop(oldest.sid, None)
    sid = secrets.token_hex(16)          # 32 chars — inside the 16..64 window
    SESSIONS[sid] = Session(sid)
    return {"ok": True, "session_id": sid, "ttl_s": SESSION_TTL}


@app.post("/api/session/{sid}/keepalive")
async def keepalive(sid: str):
    """Heartbeat from the PC. Its reply is also how the viewer flips from
    'Not paired' to 'Paired' before any board has been scanned."""
    session = _get(sid)
    return {
        "ok": True,
        "session_id": sid,
        "phone_paired": session.phone_paired,
        "last_seq": session.seq,
    }


@app.get("/api/session/{sid}/poll")
async def poll(sid: str, after: int = 0):
    """Long poll fallback for networks that buffer or block event streams.

    Returns as soon as there is anything newer than ``after``; otherwise
    waits up to POLL_TIMEOUT seconds and returns an empty list so the
    client can immediately poll again.
    """
    session = _get(sid)
    pending = session.since(after)
    if pending:
        return {"ok": True, "events": pending, "last_seq": session.seq}

    waiter = session.signal
    try:
        await asyncio.wait_for(waiter.wait(), timeout=POLL_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    session.touch()
    return {"ok": True, "events": session.since(after), "last_seq": session.seq}


@app.get("/api/session/{sid}/events")
async def events(sid: str, request: Request, after: int = 0):
    """Server-Sent Events stream — the viewer's primary transport."""
    session = _get(sid)

    async def stream():
        cursor = after
        yield f"event: ready\ndata: {json.dumps({'session_id': sid, 'last_seq': session.seq})}\n\n"
        # Replay anything that happened while the PC was reconnecting, so a
        # scan is never silently lost across a dropped connection.
        for event in session.since(cursor):
            cursor = event["seq"]
            yield f"event: scan\ndata: {json.dumps(event)}\n\n"

        while True:
            if await request.is_disconnected():
                return
            current = SESSIONS.get(sid)
            if current is None:
                yield "event: expired\ndata: {}\n\n"
                return
            current.touch()
            waiter = current.signal
            try:
                await asyncio.wait_for(waiter.wait(), timeout=SSE_HEARTBEAT)
            except asyncio.TimeoutError:
                # Comment frame: keeps proxies and Railway's edge from
                # closing an idle stream, and is ignored by EventSource.
                yield ": keepalive\n\n"
                continue
            for event in current.since(cursor):
                cursor = event["seq"]
                yield f"event: scan\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Phone side
# ---------------------------------------------------------------------------
@app.post("/api/session/{sid}/scan")
async def submit_scan(sid: str, request: Request):
    """The phone posts a Board ID it just read from a printed label."""
    session = _get(sid)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        body = {}

    board_id = _normalize_board_id(str(body.get("board_id", "")))
    if not board_id:
        raise HTTPException(status_code=400, detail="board_id is required")
    if not BOARD_ID_RE.match(board_id):
        raise HTTPException(status_code=400, detail="board_id has an unexpected format")

    event = session.add_scan(board_id, source=str(body.get("source", "phone"))[:16])
    return {"ok": True, "seq": event["seq"], "board_id": board_id}


@app.post("/api/session/{sid}/pair")
async def mark_paired(sid: str):
    session = _get(sid)
    session.phone_paired = True
    return {"ok": True, "phone_paired": True}


@app.post("/api/session/{sid}/ack")
async def post_ack(sid: str, request: Request):
    """The PC viewer reports what it actually did with a scanned Board ID.

    This is the difference between the phone claiming "Sent to PC" (which only
    means the relay accepted a POST) and "Selected on PC" (which means the 3D
    viewer really found and focused that board). Purely additive: a PC that
    never calls this keeps working exactly as before, and the phone simply
    falls back to reporting the send.
    """
    session = _get(sid)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        body = {}

    result = str(body.get("result", "")).strip().upper()
    if result not in ACK_RESULTS:
        raise HTTPException(status_code=400, detail="result must be one of " + ", ".join(sorted(ACK_RESULTS)))
    try:
        seq = int(body.get("seq", 0))
    except (TypeError, ValueError):
        seq = 0
    board_id = _normalize_board_id(str(body.get("board_id", "")))
    return {"ok": True, "ack": session.set_ack(seq, board_id, result)}


@app.get("/api/session/{sid}/ack")
async def get_ack(sid: str, seq: int = 0):
    """The phone waits here for the PC's verdict on the scan it just sent."""
    session = _get(sid)
    if session.ack and session.ack.get("seq", 0) >= seq:
        return {"ok": True, "ack": session.ack}
    waiter = session.ack_signal
    try:
        await asyncio.wait_for(waiter.wait(), timeout=ACK_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    session.touch()
    ack = session.ack if (session.ack and session.ack.get("seq", 0) >= seq) else None
    return {"ok": True, "ack": ack}


# ---------------------------------------------------------------------------
# Publish (PC -> relay) and the phone's own 3D viewer
# ---------------------------------------------------------------------------
@app.post("/api/publish/{token}")
async def publish_project(token: str, request: Request):
    """The PC uploads one cabinet: its model file and its manifest.

    Deliberately a raw multipart-free JSON body so the PC side stays a single
    requests/urllib call with no extra dependency. The model is base64 only
    because a DAE is XML and a GLB is binary; at 0.2 MB the 33% overhead is
    irrelevant and it keeps one code path for both formats.
    """
    if not TOKEN_RE.match(token or ""):
        raise HTTPException(status_code=400, detail="Invalid project token")
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    model_name = str(body.get("model_name", "model.dae")).strip()
    if not MODEL_NAME_RE.match(model_name):
        raise HTTPException(status_code=400, detail="Invalid model_name")

    try:
        model = base64.b64decode(str(body.get("model_b64", "")), validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=400, detail="model_b64 is not valid base64")
    if not model:
        raise HTTPException(status_code=400, detail="model_b64 is empty")
    if len(model) > MAX_MODEL_BYTES:
        raise HTTPException(status_code=413, detail="Model is too large")

    manifest_raw = body.get("manifest")
    if isinstance(manifest_raw, (dict, list)):
        manifest = json.dumps(manifest_raw, ensure_ascii=False).encode("utf-8")
    else:
        manifest = str(manifest_raw or "{}").encode("utf-8")
    try:
        json.loads(manifest)
    except ValueError:
        raise HTTPException(status_code=400, detail="manifest is not valid JSON")

    project = PROJECTS.get(token) or Project(token)
    project.title = str(body.get("title", project.title))[:120] or "OpenEyes Project"
    project.detail = str(body.get("detail", ""))[:160]
    project.model_name = model_name
    project.model = model
    project.manifest = manifest
    # Version is a content hash, so the phone's cache is only busted when the
    # cabinet actually changed - the whole point of the immutable asset URL.
    project.version = hashlib.sha256(model + manifest).hexdigest()[:12]
    project.touch()
    PROJECTS[token] = project
    _persist(project)

    print(f"[publish] {token} v{project.version} "
          f"model={len(model)}B manifest={len(manifest)}B", flush=True)
    return {
        "ok": True,
        "token": token,
        "version": project.version,
        "model_bytes": len(model),
        "manifest_bytes": len(manifest),
        "viewer_url": f"/p/{token}",
        "persisted": bool(DATA_DIR),
    }


@app.get("/api/publish/{token}")
def publish_status(token: str):
    """Lets the PC check whether this cabinet is still published before
    regenerating a QR, and lets you confirm a deploy did not wipe it."""
    project = _get_project(token)
    return {
        "ok": True, "token": token, "version": project.version,
        "title": project.title, "model_bytes": len(project.model),
        "age_s": int(time.time() - project.created),
    }


@app.get("/p/{token}/manifest.json")
def phone_manifest(token: str):
    project = _get_project(token)
    return Response(project.manifest, media_type="application/json",
                    headers={"Cache-Control": "no-cache"})


@app.get("/p/{token}/model-{version}/{name}")
def phone_model(token: str, version: str, name: str):
    """Immutable per-version URL: the service worker caches this forever, and
    a changed cabinet produces a different version, hence a different URL."""
    project = _get_project(token)
    if version != project.version or name != project.model_name:
        raise HTTPException(status_code=404, detail="Model version not found")
    media = ("model/gltf-binary" if name.lower().endswith(".glb")
             else "model/vnd.collada+xml")
    return Response(project.model, media_type=media, headers={
        "Cache-Control": "public,max-age=31536000,immutable",
        "ETag": project.version,
    })


@app.get("/p/{token}/sw.js")
def phone_service_worker(token: str):
    """Keeps each immutable model version on the phone after its first load,
    so a worker on a weak signal still opens the cabinet instantly."""
    script = r"""
const CACHE='openeyes-phone-v1';
self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const url=new URL(e.request.url);
  const immutable=url.pathname.includes('/model-');
  if(immutable){
    e.respondWith(caches.open(CACHE).then(async c=>{
      const hit=await c.match(e.request);
      if(hit)return hit;
      const res=await fetch(e.request);
      if(res.ok)c.put(e.request,res.clone());
      return res;
    }));
    return;
  }
  if(url.pathname.startsWith('/p/')){
    e.respondWith(caches.open(CACHE).then(async c=>{
      try{
        const res=await fetch(e.request);
        if(res.ok)c.put(e.request,res.clone());
        return res;
      }catch(err){
        return (await c.match(e.request))||Response.error();
      }
    }));
  }
});
"""
    return Response(script, media_type="application/javascript", headers={
        "Cache-Control": "no-cache", "Service-Worker-Allowed": f"/p/{token}",
    })


@app.get("/p/{token}", response_class=HTMLResponse)
def phone_viewer_page(token: str, part: str = ""):
    """The phone's own 3D viewer.

    This calls the SAME render_phone_viewer() the PC viewer and the Cloud
    Live Library use, so Search, Dimension, Door, Hide, Animation and the
    QR scanner behave identically. Only the asset URLs differ, which is
    exactly why moving this to Cloud storage later is a config change.
    """
    project = _get_project(token)
    if not project.model:
        raise HTTPException(status_code=404, detail="Project has no model yet")
    return HTMLResponse(render_phone_viewer(
        project.title,
        project.detail or "Phone • OpenEyes",
        f"/p/{token}/model-{project.version}/{project.model_name}",
        token,
        initial_part=part,
        manifest_url=f"/p/{token}/manifest.json",
        service_worker=True,
        sw_url=f"/p/{token}/sw.js",
        print_url="",
        jsqr_url="/jsQR.js",
    ))


@app.get("/scan")
def scan_page(session: str = ""):
    """The page the PC's pairing QR points at.

    Served over Railway's HTTPS, which is what makes live camera access
    possible at all — browsers refuse getUserMedia on a plain-HTTP LAN
    address, which is exactly why the same-Wi-Fi route needed the clumsy
    'take a photo' fallback. A manual entry box is kept anyway for locked-
    down phones.
    """
    if not SESSION_ID_RE.match(session or ""):
        return HTMLResponse(_PAGE_BAD_SESSION, status_code=400)
    _sweep()
    live = SESSIONS.get(session)
    if live is None:
        return HTMLResponse(_PAGE_EXPIRED, status_code=404)
    live.phone_paired = True
    live.touch()
    return HTMLResponse(
        _scanner_page(session),
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


_PAGE_BAD_SESSION = (
    "<!doctype html><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<div style=\"font-family:system-ui,Arial,sans-serif;max-width:520px;margin:60px auto;"
    "padding:0 20px;line-height:1.6\"><h2>Invalid pairing link</h2>"
    "<p>Open the OpenEyes viewer on the PC, press <b>PAIR PHONE</b>, and scan "
    "the QR it displays.</p></div>"
)

_PAGE_EXPIRED = (
    "<!doctype html><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<div style=\"font-family:system-ui,Arial,sans-serif;max-width:520px;margin:60px auto;"
    "padding:0 20px;line-height:1.6\"><h2>This pairing has expired</h2>"
    "<p>The PC viewer was closed, restarted, or left idle too long.</p>"
    "<p>On the PC press <b>PAIR PHONE</b> &rarr; <b>NEW SESSION</b>, then scan "
    "the new QR.</p><p>Your printed board labels are unaffected — they never "
    "expire.</p></div>"
)


def _scanner_page(session_id: str) -> str:
    return (
        _SCANNER_TEMPLATE
        .replace("__SESSION__", json.dumps(session_id))
        .replace("__BUILD__", f"relay {APP_VERSION}")
    )


_SCANNER_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>OpenEyes Board Scanner</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0d0d0f;color:#f2f2f2;font-family:system-ui,-apple-system,Arial,sans-serif}
header{padding:14px 16px;background:#16161a;border-bottom:1px solid #2a2a30;display:flex;
  align-items:center;justify-content:space-between;gap:10px}
header h1{font-size:16px;margin:0;font-weight:600}
#link{font-size:12px;color:#8a8a94}
#link b{color:#7ee787}
#wrap{position:relative;background:#000;aspect-ratio:3/4;max-height:58vh;overflow:hidden}
video{width:100%;height:100%;object-fit:cover;display:block}
#frame{position:absolute;inset:12% 10%;border:3px solid rgba(126,231,135,.85);border-radius:14px;
  box-shadow:0 0 0 100vmax rgba(0,0,0,.35);pointer-events:none}
main{padding:16px}
#result{background:#16161a;border:1px solid #2a2a30;border-radius:14px;padding:16px;margin-bottom:14px;
  min-height:88px;display:flex;flex-direction:column;justify-content:center}
#result .lbl{font-size:12px;color:#8a8a94;margin-bottom:6px}
#result .id{font-size:22px;font-weight:700;word-break:break-all;line-height:1.25}
#result .st{font-size:13px;margin-top:8px}
.ok{color:#7ee787}.bad{color:#ff7b72}.wait{color:#e3b341}
.row{display:flex;gap:8px;margin-top:10px}
input{flex:1;min-width:0;padding:13px;border-radius:11px;border:1px solid #34343c;background:#0d0d0f;
  color:#f2f2f2;font-size:16px}
button{padding:13px 16px;border-radius:11px;border:0;background:#2f6fd0;color:#fff;font-size:15px;
  font-weight:600}
button.sec{background:#2a2a30}
button:active{opacity:.75}
.hint{font-size:12.5px;color:#8a8a94;line-height:1.6;margin-top:16px}
#diag{margin-top:14px;background:#0a0a0c;border:1px solid #24242a;border-radius:12px;
  padding:10px 12px;font-size:12.5px;line-height:1.9}
#diag div{display:flex;gap:10px;align-items:baseline}
#diag .dk{color:#8a8a94;flex:0 0 96px}
#diag .dv{color:#d6d6de;font-family:ui-monospace,Menlo,Consolas,monospace;
  word-break:break-all;flex:1}
#auto{background:#16161a;border:1px solid #2a2a30;border-radius:16px;padding:20px 16px;
  text-align:center}
#autoState{font-size:15px;font-weight:700;letter-spacing:.3px}
#autoState.idle{color:#8a8a94}
#autoState.scan{color:#e3b341}
#autoState.send{color:#58a6ff}
#autoState.ok{color:#7ee787}
#autoState.bad{color:#ff7b72}
#autoId{font-size:26px;font-weight:800;margin:10px 0 6px;word-break:break-all;
  line-height:1.2;color:#f2f2f2}
#autoNote{font-size:13px;color:#8a8a94;line-height:1.5}
#debug #result{display:block}
#debug #diag{display:flex;flex-direction:column}
#verBadge{font-size:11px;font-weight:600;color:#0d0d0f;background:#7ee787;
  border-radius:6px;padding:2px 7px;margin-left:7px;vertical-align:middle}
#logBox{margin-top:10px;background:#050506;border:1px solid #24242a;border-radius:10px;
  padding:10px;font-size:11px;line-height:1.6;color:#c8c8d2;max-height:40vh;
  overflow:auto;white-space:pre-wrap;word-break:break-all;
  font-family:ui-monospace,Menlo,Consolas,monospace}
#logBox .e{color:#ff7b72}#logBox .w{color:#e3b341}
.hidden{display:none}
</style></head><body>
<header><h1>OpenEyes Board Scanner <span id="verBadge">__BUILD__</span></h1><div id="link">PC: <b id="linkState">connecting…</b></div></header>

<div id="wrap"><video id="v" playsinline muted autoplay></video><div id="frame"></div></div>

<main>
  <!-- AUTO MODE: everything a worker needs, and nothing else. -->
  <div id="auto">
    <div id="autoState" class="idle">Starting camera…</div>
    <div id="autoId">—</div>
    <div id="autoNote">Point the camera at a board label. It sends by itself.</div>
  </div>

  <button id="debugToggle" class="sec" style="width:100%;margin-top:12px">⚙ DEBUG</button>

  <!-- DEBUG MODE: hidden by default, unchanged tooling. -->
  <div id="debug" class="hidden">
    <div id="result">
      <div class="lbl">Last board sent to the PC</div>
      <div class="id" id="lastId">—</div>
      <div class="st wait" id="lastSt">Point the camera at a printed board label.</div>
    </div>

    <div class="row">
      <input id="manual" placeholder="Or type a Board ID" autocomplete="off"
             autocapitalize="off" autocorrect="off" spellcheck="false">
      <button id="send">SEND</button>
    </div>
    <div class="row">
      <button id="camBtn" class="sec">📷 START CAMERA</button>
      <button id="photoBtn" class="sec">🖼 PHOTO</button>
    </div>
    <input id="photo" class="hidden" type="file" accept="image/*" capture="environment">

    <div id="diag">
      <div><span class="dk">Camera</span><span class="dv" id="dCam">starting…</span></div>
      <div><span class="dk">Decoder</span><span class="dv" id="dDec">probing…</span></div>
      <div><span class="dk">QR detected</span><span class="dv" id="dRaw">—</span></div>
      <div><span class="dk">Board ID</span><span class="dv" id="dId">—</span></div>
      <div><span class="dk">Relay send</span><span class="dv" id="dSend">—</span></div>
      <div><span class="dk">PC result</span><span class="dv" id="dAck">—</span></div>
      <div><span class="dk">Build</span><span class="dv" id="dBuild">__BUILD__</span></div>
    </div>

    <button id="logToggle" class="sec" style="width:100%;margin-top:10px">▾ SHOW SCAN TRACE</button>
    <pre id="logBox" class="hidden"></pre>
    <div class="row"><button id="logCopy" class="sec hidden">⧉ COPY TRACE</button>
         <button id="selftest" class="sec">⚙ SELF TEST</button></div>
  </div>

  <div class="hint">
    Keep this page open. Every label you scan is sent straight to the paired PC,
    which highlights and focuses that board in the 3D viewer.<br><br>
    Printed labels hold only the Board ID and never expire. This pairing page
    belongs to the PC viewer window that showed the QR — if the PC restarts,
    scan its new pairing QR again.
  </div>
</main>

<script src="/static/jsQR.js"></script>
<script>
const SESSION=__SESSION__;
const LOG='[OpenEyes QR]';

// --- on-screen log ----------------------------------------------------------
// A phone has no DevTools, so a JavaScript error here is completely invisible:
// the camera simply never starts and nothing explains why. Everything logged
// below is mirrored into a panel the user can open and copy.
const LOGLINES=[];
function uiLog(kind,parts){
  const t=new Date().toTimeString().slice(0,8);
  const msg=parts.map(x=>{
    if(x instanceof Error)return x.name+': '+x.message;
    if(typeof x==='object'){try{return JSON.stringify(x)}catch(e){return String(x)}}
    return String(x);
  }).join(' ');
  LOGLINES.push({t,kind,msg});
  if(LOGLINES.length>200)LOGLINES.shift();
  const box=document.getElementById('logBox');
  if(box){
    box.innerHTML=LOGLINES.map(l=>
      '<span class="'+(l.kind==='e'?'e':l.kind==='w'?'w':'')+'">'+
      l.t+' '+l.msg.replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;')+'</span>').join('\n');
    box.scrollTop=box.scrollHeight;
  }
}
(function(){
  const orig={log:console.log,warn:console.warn,error:console.error};
  console.log=function(){orig.log.apply(console,arguments);uiLog('i',[].slice.call(arguments))};
  console.warn=function(){orig.warn.apply(console,arguments);uiLog('w',[].slice.call(arguments))};
  console.error=function(){orig.error.apply(console,arguments);uiLog('e',[].slice.call(arguments))};
  // A silent uncaught error is the single most likely reason the camera never
  // starts, so surface it in the panel AND in the status line.
  window.addEventListener('error',e=>{
    uiLog('e',['UNCAUGHT',(e.message||'error'),'@',(e.filename||'?')+':'+(e.lineno||0)]);
    const st=document.getElementById('lastSt');
    if(st){st.textContent='Script error: '+(e.message||'unknown')+' - open SHOW LOG';st.className='st bad'}
  });
  window.addEventListener('unhandledrejection',e=>{
    const r=e&&e.reason;
    uiLog('e',['UNHANDLED PROMISE',(r&&(r.message||r.name))||String(r)]);
  });
  uiLog('i',['[OpenEyes QR] page loaded, build __BUILD__']);
  uiLog('i',['[OpenEyes QR] UA',navigator.userAgent]);
  uiLog('i',['[OpenEyes QR] secureContext='+window.isSecureContext,
             'origin='+location.origin]);
})();
const video=document.getElementById('v'),
      lastId=document.getElementById('lastId'),lastSt=document.getElementById('lastSt'),
      linkState=document.getElementById('linkState');

// Offscreen canvas, created in JS and never attached to the document. A
// display:none canvas works too, but an unattached one removes any doubt
// about layout/CSS ever influencing the pixel buffer we hand to jsQR.
const canvas=document.createElement('canvas');
const ctx=canvas.getContext('2d',{willReadFrequently:true});

let stream=null,starting=false,scanning=false,loopRunning=false,decodeBusy=false,sendInFlight=false,
    lastSent='',lastSentAt=0,everSent=false,lastDecodeAt=0;

// Native BarcodeDetector: fastest and most tolerant on Samsung Internet
// and Chrome for Android. Probed once; if the probe or the detector
// itself misbehaves we fall through to jsQR permanently.
let detector=null,detectorEmpty=0,detectorErrors=0,dupLogged='',jsqrReady=false,
    decodeCount=0,activeDecoder='';
const DECODE_INTERVAL_MS=100;      // ~10 decodes/sec is plenty and cheap
const SAME_ID_COOLDOWN_MS=2000;    // duplicate protection
const MAX_DECODE_EDGE=1280;        // cap the buffer we hand to jsQR

function setState(t,cls){linkState.textContent=t;linkState.className=cls||''}
function setResult(id,msg,cls){
  if(id)lastId.textContent=id;
  lastSt.textContent=msg;lastSt.className='st '+(cls||'wait');
}
function setDiag(id,text){const el=document.getElementById(id);if(el)el.textContent=text}

// --- AUTO mode status -------------------------------------------------------
function setAuto(state,cls,id,note){
  const st=document.getElementById('autoState'),
        el=document.getElementById('autoId'),
        nt=document.getElementById('autoNote');
  if(st){st.textContent=state;st.className=cls||'idle'}
  if(el&&id!==undefined)el.textContent=id||'\u2014';
  if(nt&&note!==undefined)nt.textContent=note;
}

// --- scan trace -------------------------------------------------------------
// Each scan gets a number and every stage is recorded against it:
//   DETECT -> NORMALIZE -> SEND -> RELAY -> PC. A scan that fails shows
//   exactly which stage it stopped at.
let scanNo=0,traceT0=0;
function traceStart(raw,decoder){
  scanNo++;traceT0=Date.now();
  console.log(LOG,'--- SCAN #'+scanNo+' -------------------------------');
  console.log(LOG,'#'+scanNo+' DETECT    raw="'+raw+'" via '+decoder);
  return scanNo;
}
function trace(n,stage,detail){
  const ms=traceT0?(Date.now()-traceT0):0;
  console.log(LOG,'#'+n+' '+stage.padEnd(9)+' '+detail+'  (+'+ms+'ms)');
}
function traceFail(n,stage,detail){
  const ms=traceT0?(Date.now()-traceT0):0;
  console.warn(LOG,'#'+n+' '+stage.padEnd(9)+' FAILED: '+detail+'  (+'+ms+'ms)');
}
function setScanningIdle(){
  // Never clobber a successful "Sent to PC" line with routine scan chatter.
  if(!everSent)setResult('','Scanning\u2026 point the camera at a board label.','wait');
}

// --- Board ID normalization -------------------------------------------------
// Identical rules to labelIdFromScanValue() in the PC viewer: a bare Board
// ID passes through untouched (this is what printed labels contain and
// always will), a legacy URL with ?part= has the ID lifted out, and a small
// JSON payload is read defensively. No loose or fuzzy matching, ever.
function labelIdFromScanValue(value){
  const v=String(value||'').trim();
  try{const u=new URL(v,location.href);const part=u.searchParams.get('part');if(part)return part.trim()}catch(e){}
  if(v.startsWith('{')){try{const j=JSON.parse(v);const c=j.id||j.label||j.labelId;if(c)return String(c).trim()}catch(e){}}
  return v;
}

// --- send a Board ID to the relay -------------------------------------------
async function send(rawValue,source){
  const raw=String(rawValue||'');
  const id=labelIdFromScanValue(raw);
  const n=traceStart(raw,source);

  // --- validation: never forward junk to the PC ---------------------------
  if(!id){traceFail(n,'NORMALIZE','decoded value is empty');return}
  if(id==='undefined'||id==='null'){traceFail(n,'NORMALIZE','literal "'+id+'"');return}
  if(id.length>128){traceFail(n,'NORMALIZE','too long ('+id.length+' chars)');return}
  if(!/^[A-Za-z0-9._:\-]+$/.test(id)){
    traceFail(n,'NORMALIZE','not a Board ID: "'+id.slice(0,40)+'"');
    setAuto('Not a board label','bad','\u2014','That QR is not an OpenEyes board label.');
    return;
  }
  trace(n,'NORMALIZE','id="'+id+'"');
  setDiag('dRaw',raw);setDiag('dId',id);

  // --- duplicate protection ----------------------------------------------
  const now=Date.now();
  if(id===lastSent&&now-lastSentAt<SAME_ID_COOLDOWN_MS){
    if(dupLogged!==id){dupLogged=id;trace(n,'SKIP','duplicate within '+SAME_ID_COOLDOWN_MS+'ms')}
    scanNo--;                       // a skipped scan does not consume a number
    return;
  }
  if(sendInFlight){trace(n,'SKIP','a send is already in flight');scanNo--;return}
  dupLogged='';
  lastSent=id;lastSentAt=now;

  sendInFlight=true;
  setAuto('Sending to PC\u2026','send',id,'Board detected. Contacting the PC.');
  setResult(id,'Sending\u2026','wait');
  trace(n,'SEND','POST /api/session/\u2026/scan');
  let seq=0;
  try{
    const r=await fetch('/api/session/'+encodeURIComponent(SESSION)+'/scan',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({board_id:id,source:source||'phone'})
    });
    if(r.status===404){
      traceFail(n,'RELAY','session expired (404)');
      setState('session expired','bad');
      setDiag('dSend','FAILED (session expired)');
      setResult(id,'Pairing expired \u2014 rescan the PC pairing QR.','bad');
      setAuto('Pairing expired','bad',id,'Scan the pairing QR on the PC again.');
      lastSent='';
      return;
    }
    if(!r.ok){
      const j=await r.json().catch(()=>({}));
      const why=j.error||j.detail||r.status;
      traceFail(n,'RELAY','HTTP '+r.status+' '+why);
      setDiag('dSend','FAILED ('+why+')');
      setResult(id,'Rejected: '+why,'bad');
      setAuto('Could not send','bad',id,'Relay rejected it. Retrying on next scan.');
      lastSent='';
      return;
    }
    const j=await r.json().catch(()=>({}));
    seq=j.seq||0;
    trace(n,'RELAY','accepted, seq='+seq);
    everSent=true;
    setState('connected','ok');
    setDiag('dSend','OK ('+id+')');
    setResult(id,'Sent to PC \u2713','ok');
    if(navigator.vibrate)navigator.vibrate(60);
  }catch(e){
    traceFail(n,'RELAY','network error: '+(e&&e.message));
    lastSent='';
    setState('offline','bad');
    setDiag('dSend','FAILED (network)');
    setResult(id,'Network error \u2014 check signal and try again.','bad');
    setAuto('No connection','bad',id,'Check mobile data or Wi-Fi.');
    return;
  }finally{
    sendInFlight=false;
  }

  // --- wait for the PC's real verdict -------------------------------------
  // "Sent to PC" only means the relay accepted a POST. The line below waits
  // for the viewer to say whether it actually found and focused the board.
  setAuto('Waiting for PC\u2026','send',id,'Relay delivered it. Waiting for the 3D viewer.');
  trace(n,'PC','waiting for viewer verdict');
  try{
    const a=await fetch('/api/session/'+encodeURIComponent(SESSION)+
                        '/ack?seq='+encodeURIComponent(seq),{method:'GET'});
    const aj=await a.json().catch(()=>({}));
    const ack=aj&&aj.ack;
    if(!ack){
      trace(n,'PC','no verdict (older PC build, or viewer busy)');
      setDiag('dAck','no reply');
      setAuto('Sent to PC \u2713','ok',id,'Delivered. This PC build does not report back.');
      return;
    }
    trace(n,'PC',ack.result+' for '+ack.board_id);
    setDiag('dAck',ack.result);
    if(ack.result==='NOT_FOUND'){
      setAuto('Board not found','bad',id,'This board is not in the model open on the PC.');
    }else{
      setAuto('Selected on PC \u2713','ok',id,'The 3D viewer highlighted and focused this board.');
      if(navigator.vibrate)navigator.vibrate([40,60,40]);
    }
  }catch(e){
    trace(n,'PC','verdict unavailable: '+(e&&e.message));
    setDiag('dAck','unavailable');
    setAuto('Sent to PC \u2713','ok',id,'Delivered, but the PC did not report back.');
  }
}

document.getElementById('send').onclick=()=>{
  const el=document.getElementById('manual');
  const v=el.value.trim();
  if(!v)return;
  lastSent='';                       // manual entry always goes through
  setDiag('dRaw',v);setDiag('dId',labelIdFromScanValue(v));
  send(v,'manual');el.value='';
};
document.getElementById('manual').addEventListener('keydown',e=>{
  if(e.key==='Enter')document.getElementById('send').click();
});

// --- one decode helper, shared by the live camera and the photo fallback ----
// Decodes the WHOLE frame. No region-of-interest cropping: the green box is
// a framing aid for the user, not a decode boundary. CSS pixels on a
// cover-fitted <video> do not map linearly onto native video pixels, so
// cropping to it risks decoding the wrong part of the image. Reliability
// beats the small CPU saving.
function decodeWithJsQR(source,nativeW,nativeH){
  if(typeof jsQR!=='function')return null;
  if(!nativeW||!nativeH)return null;
  // Only downscale if the frame is genuinely larger than the cap; never
  // upscale, and never use CSS/client dimensions.
  let w=nativeW,h=nativeH;
  const longest=Math.max(w,h);
  if(longest>MAX_DECODE_EDGE){
    const k=MAX_DECODE_EDGE/longest;
    w=Math.max(1,Math.round(w*k));
    h=Math.max(1,Math.round(h*k));
  }
  if(canvas.width!==w)canvas.width=w;
  if(canvas.height!==h)canvas.height=h;
  try{
    ctx.drawImage(source,0,0,w,h);
    const img=ctx.getImageData(0,0,w,h);
    const code=jsQR(img.data,img.width,img.height,{inversionAttempts:'attemptBoth'});
    return code&&code.data?code.data:null;
  }catch(e){
    // Log once rather than swallowing silently every frame — a silent
    // catch here is exactly what hid the previous failure.
    if(!decodeWithJsQR._warned){decodeWithJsQR._warned=true;console.warn(LOG,'jsQR decode error:',e&&e.message)}
    return null;
  }
}

async function decodeFrame(){
  // Two decoders, tried in order, ON THE SAME FRAME. This is the whole fix.
  //
  // The previous build returned null as soon as BarcodeDetector produced an
  // empty result, so jsQR was never reached. On Samsung Internet and several
  // Android WebViews, BarcodeDetector is present, getSupportedFormats()
  // truthfully reports 'qr_code', and detect() then returns [] forever. The
  // decoder reported itself available, the camera ran, and nothing was ever
  // decoded -- exactly the reported symptom. An empty result is now treated
  // as "this decoder did not find it", never as "there is nothing there".
  if(detector){
    let hits=null;
    try{
      hits=await detector.detect(video);
    }catch(e){
      detectorErrors++;
      if(detectorErrors<=3)console.warn(LOG,'BarcodeDetector error:',e&&e.message);
    }
    if(hits&&hits.length&&hits[0].rawValue){
      detectorEmpty=0;
      setDiag('dDec','BarcodeDetector');
      return hits[0].rawValue;
    }
    detectorEmpty++;
    // Only hand the loop to jsQR if jsQR actually exists. Demoting into a
    // fallback that is not loaded leaves ZERO decoders and silently kills
    // scanning until the camera is restarted.
    if((detectorEmpty>=80||detectorErrors>=5)&&jsqrReady){
      detector=null;
      console.warn(LOG,'BarcodeDetector produced nothing -> switching to jsQR');
      setDecoderLine();
    }
    // fall through to jsQR on this same frame
  }

  const raw=decodeWithJsQR(video,video.videoWidth,video.videoHeight);
  if(raw){activeDecoder='jsQR';setDecoderLine()}
  return raw;
}

// --- camera ------------------------------------------------------------------
async function ensureJsQR(){
  // The <script src="/static/jsQR.js"> tag above should already have defined
  // window.jsQR. If it did not (file missing from the deployment, blocked,
  // truncated), say so on screen instead of silently degrading -- a silent
  // failure here is indistinguishable from "the QR is unreadable".
  if(typeof jsQR==='function'){jsqrReady=true;return true}
  console.warn(LOG,'jsQR missing after page load - retrying once');
  // Try both locations: static/jsQR.js is the intended layout, /jsQR.js
  // covers an upload that flattened the folder.
  let ok=false;
  for(const path of ['/static/jsQR.js','/jsQR.js']){
    ok=await new Promise(resolve=>{
      const tag=document.createElement('script');
      tag.src=path+'?retry='+Date.now();
      tag.onload=()=>resolve(typeof jsQR==='function');
      tag.onerror=()=>resolve(false);
      document.head.appendChild(tag);
      setTimeout(()=>resolve(typeof jsQR==='function'),6000);
    });
    if(ok){console.log(LOG,'jsQR loaded from '+path);break}
    console.warn(LOG,'jsQR not available at '+path);
  }
  jsqrReady=ok;
  if(!ok)console.warn(LOG,'jsQR fallback not loaded (check /static/jsQR.js). '+
    'Not fatal while BarcodeDetector works.');
  return ok;
}

async function probeDetector(){
  try{
    if(!('BarcodeDetector' in window)){
      console.log(LOG,'BarcodeDetector unavailable -> jsQR');
      return;
    }
    const formats=await window.BarcodeDetector.getSupportedFormats();
    if(!formats||formats.indexOf('qr_code')<0){
      console.log(LOG,'BarcodeDetector has no qr_code format -> jsQR');
      return;
    }
    detector=new window.BarcodeDetector({formats:['qr_code']});
    console.log(LOG,'BarcodeDetector available');
  }catch(e){
    detector=null;
    console.log(LOG,'BarcodeDetector probe failed -> jsQR:',e&&e.message);
  }
}

function describeDecoders(){
  // activeDecoder is set the moment a decoder actually produces a result, so
  // after the first scan this reports fact rather than capability.
  if(activeDecoder)
    return activeDecoder+' \u2713  (fallback: '+(jsqrReady?'jsQR ready':'jsQR unavailable')+')';
  if(detector&&jsqrReady)return 'BarcodeDetector, fallback jsQR';
  if(detector)return 'BarcodeDetector  (fallback: jsQR unavailable)';
  if(jsqrReady)return 'jsQR';
  return 'NO DECODER \u2014 BarcodeDetector missing and jsQR not loaded';
}
function setDecoderLine(){setDiag('dDec',describeDecoders())}

function decodersAvailable(){return !!detector||jsqrReady}

function waitForVideoDimensions(){
  // Do NOT gate on readyState===HAVE_ENOUGH_DATA. On Android/Samsung a live
  // MediaStream frequently sits at HAVE_CURRENT_DATA (2) forever, which
  // makes a strict ===4 check block every decode while the preview renders
  // perfectly. Real readiness for pixel capture is videoWidth/videoHeight.
  return new Promise(resolve=>{
    const ready=()=>video.videoWidth>0&&video.videoHeight>0;
    if(ready())return resolve(true);
    let tries=0;
    const check=()=>{
      if(ready())return resolve(true);
      if(++tries>200)return resolve(false);   // ~10s
      setTimeout(check,50);
    };
    video.addEventListener('loadedmetadata',()=>{if(ready())resolve(true)},{once:true});
    check();
  });
}

async function startCamera(){
  if(stream||starting)return;
  starting=true;
  try{ await startCameraInner() } finally { starting=false }
}

async function startCameraInner(){
  // Log the preconditions. If any of these is false, getUserMedia can never
  // succeed and the failure would otherwise look identical to "camera opened
  // but decoding failed".
  console.log(LOG,'startCamera: secureContext='+window.isSecureContext,
              'mediaDevices='+!!(navigator.mediaDevices),
              'getUserMedia='+!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia));
  if(!window.isSecureContext){
    setDiag('dCam','blocked (not HTTPS)');
    setAuto('Camera blocked','bad','\u2014','Open the https:// relay address, not an IP.');
    setResult('','Camera needs HTTPS. Open the relay https:// address, not an IP.','bad');
    console.error(LOG,'not a secure context - getUserMedia is unavailable');
    return;
  }
  if(!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia)){
    setDiag('dCam','unsupported browser');
    setAuto('Browser not supported','bad','\u2014','Open this link in Chrome.');
    setResult('','This browser has no camera API. Open the link in Chrome.','bad');
    console.error(LOG,'navigator.mediaDevices.getUserMedia missing');
    return;
  }
  setDiag('dCam','requesting permission…');
  try{
    stream=await navigator.mediaDevices.getUserMedia({
      video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}},
      audio:false
    });
    video.srcObject=stream;
    video.setAttribute('playsinline','');
    try{await video.play()}catch(e){/* some browsers resolve play() late */}

    const ok=await waitForVideoDimensions();
    if(!ok){
      console.error(LOG,'Video never reported dimensions');
      setResult('','Camera started but produced no frames. Use PHOTO or type the ID.','bad');
      return;
    }
    console.log(LOG,'Camera ready '+video.videoWidth+'x'+video.videoHeight);
    setDiag('dCam','running '+video.videoWidth+'x'+video.videoHeight);

    // Continuous autofocus where the device exposes it; harmless if not.
    try{
      const track=stream.getVideoTracks()[0];
      const caps=track.getCapabilities?track.getCapabilities():{};
      if(caps.focusMode&&caps.focusMode.indexOf('continuous')>=0){
        await track.applyConstraints({advanced:[{focusMode:'continuous'}]});
      }
    }catch(e){/* optional */}

    await probeDetector();
    await ensureJsQR();
    setDecoderLine();
    if(detector&&!jsqrReady){
      console.log(LOG,'jsQR unavailable, but BarcodeDetector is present - this is fine');
    }
    if(!decodersAvailable()){
      setResult('','No QR decoder on this browser. Open the link in Chrome, or type the Board ID.','bad');
      return;
    }

    scanning=true;
    document.getElementById('camBtn').textContent='\u23f9 STOP CAMERA';
    setScanningIdle();
    setAuto('Ready to scan','scan','\u2014','Point the camera at a board label. It sends by itself.');
    startLoop();
  }catch(e){
    stream=null;
    console.error(LOG,'Camera error:',e&&e.name,e&&e.message);
    const name=(e&&e.name)||'error';
    const msg=(name==='NotAllowedError')
      ? 'Camera permission denied. Allow camera access for this site, then press START CAMERA.'
      : (name==='NotFoundError')
      ? 'No camera found on this device. Use PHOTO or type the Board ID.'
      : 'Camera unavailable ('+name+'). Use PHOTO or type the Board ID.';
    setResult('',msg,'bad');
    setDiag('dCam','failed ('+name+')');
    setAuto('Camera blocked','bad','\u2014',msg);
  }
}

function stopCamera(){
  scanning=false;
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}
  video.srcObject=null;
  document.getElementById('camBtn').textContent='\ud83d\udcf7 START CAMERA';
  setDiag('dCam','stopped');
  setAuto('Camera stopped','idle','\u2014','Open DEBUG and press START CAMERA.');
  console.log(LOG,'Camera stopped');
}
document.getElementById('camBtn').onclick=()=>{stream?stopCamera():startCamera()};

// --- single scan loop --------------------------------------------------------
// startLoop() is idempotent: loopRunning guarantees exactly one rAF chain no
// matter how many times the camera is toggled, and decodeBusy prevents
// overlapping async BarcodeDetector calls from stacking up.
function startLoop(){
  if(loopRunning)return;
  loopRunning=true;
  // requestVideoFrameCallback fires once per DECODED video frame and is the
  // most reliable signal on Android that pixels are actually available. Where
  // it is missing we fall back to requestAnimationFrame. Exactly one chain
  // runs either way.
  if(typeof video.requestVideoFrameCallback==='function'){
    console.log(LOG,'Scan loop: requestVideoFrameCallback');
    video.requestVideoFrameCallback(onFrame);
  }else{
    console.log(LOG,'Scan loop: requestAnimationFrame');
    requestAnimationFrame(tick);
  }
}

function schedule(){
  if(!scanning){loopRunning=false;return}
  if(typeof video.requestVideoFrameCallback==='function')video.requestVideoFrameCallback(onFrame);
  else requestAnimationFrame(tick);
}

async function onFrame(){ await pump(); schedule() }
async function tick(){ await pump(); schedule() }

async function pump(){
  if(!scanning)return;
  const now=Date.now();
  if(decodeBusy)return;
  if(now-lastDecodeAt<DECODE_INTERVAL_MS)return;
  // Real readiness for pixel capture is the frame size, never readyState===4:
  // a live MediaStream on Android commonly sits at HAVE_CURRENT_DATA forever.
  if(!(video.videoWidth>0&&video.videoHeight>0&&video.readyState>=2))return;

  decodeBusy=true;lastDecodeAt=now;decodeCount++;
  try{
    const raw=await decodeFrame();
    if(raw){
      setDiag('dRaw',raw);
      const id=labelIdFromScanValue(raw);
      setDiag('dId',id||'(empty)');
      send(raw,'camera');
    }else{
      setScanningIdle();
    }
  }catch(e){
    console.warn(LOG,'decode loop error:',e&&e.message);
  }finally{
    decodeBusy=false;
  }
  // Proof-of-life every ~50 decode attempts (~5s). Without this, "decoding and
  // finding nothing" and "loop not running at all" look identical on screen.
  if(decodeCount%50===0){
    console.log(LOG,'scanning... attempts='+decodeCount,
                'frame='+video.videoWidth+'x'+video.videoHeight,
                'decoder='+describeDecoders());
  }
}

// --- single photo fallback ---------------------------------------------------
// Shares decodeWithJsQR() with the live path, so any future fix helps both.
document.getElementById('photoBtn').onclick=()=>document.getElementById('photo').click();
document.getElementById('photo').onchange=e=>{
  const f=e.target.files&&e.target.files[0];e.target.value='';
  if(!f)return;
  setResult('','Reading photo\u2026','wait');
  const url=URL.createObjectURL(f);
  const img=new Image();
  img.onload=async()=>{
    let raw=null;
    if(detector){
      try{
        const hits=await detector.detect(img);
        if(hits&&hits.length&&hits[0].rawValue)raw=hits[0].rawValue;
      }catch(err){/* fall through to jsQR */}
    }
    if(!raw)raw=decodeWithJsQR(img,img.naturalWidth||img.width,img.naturalHeight||img.height);
    URL.revokeObjectURL(url);
    if(raw){
      console.log(LOG,'Detected (photo):',raw);
      setDiag('dRaw',raw);setDiag('dId',labelIdFromScanValue(raw));
      lastSent='';                    // an explicit photo always goes through
      send(raw,'photo');
    }else{
      console.log(LOG,'No QR found in photo');
      setResult('','No QR found in that photo. Try again, closer and steadier.','bad');
    }
  };
  img.onerror=()=>{URL.revokeObjectURL(url);setResult('','Could not read that image.','bad')};
  img.src=url;
};

// --- log panel + self test --------------------------------------------------
document.getElementById('debugToggle').onclick=()=>{
  const d=document.getElementById('debug'),b=document.getElementById('debugToggle');
  const hidden=d.classList.toggle('hidden');
  b.textContent=hidden?'\u2699 DEBUG':'\u2699 HIDE DEBUG';
};
document.getElementById('logToggle').onclick=()=>{
  const box=document.getElementById('logBox'),btn=document.getElementById('logToggle'),
        cp=document.getElementById('logCopy');
  const hidden=box.classList.toggle('hidden');
  cp.classList.toggle('hidden',hidden);
  btn.textContent=hidden?'\u25be SHOW SCAN TRACE':'\u25b4 HIDE SCAN TRACE';
  if(!hidden)uiLog('i',['--- log opened ---']);
};
document.getElementById('logCopy').onclick=async()=>{
  const text=LOGLINES.map(l=>l.t+' ['+l.kind+'] '+l.msg).join('\n');
  try{await navigator.clipboard.writeText(text);setDiag('dSend','log copied')}
  catch(e){uiLog('w',['clipboard blocked - select the text manually'])}
};
document.getElementById('selftest').onclick=()=>{
  document.getElementById('logBox').classList.remove('hidden');
  document.getElementById('logCopy').classList.remove('hidden');
  document.getElementById('logToggle').textContent='\u25b4 HIDE SCAN TRACE';
  runSelfTest();
};

async function runSelfTest(){
  uiLog('i',['=== SELF TEST ===']);
  uiLog('i',['build','__BUILD__']);
  uiLog('i',['secureContext',window.isSecureContext,'| origin',location.origin]);
  uiLog('i',['jsQR typeof',typeof jsQR,'| jsqrReady',jsqrReady]);
  uiLog('i',['BarcodeDetector in window',('BarcodeDetector' in window)]);
  try{
    if('BarcodeDetector' in window)
      uiLog('i',['supported formats',await window.BarcodeDetector.getSupportedFormats()]);
  }catch(e){uiLog('e',['getSupportedFormats threw',e])}
  uiLog('i',['detector active',!!detector,'| detectorEmpty',detectorEmpty,
             '| detectorErrors',detectorErrors]);
  uiLog('i',['camera stream',!!stream,'| scanning',scanning,'| loopRunning',loopRunning]);
  uiLog('i',['video',video.videoWidth+'x'+video.videoHeight,
             '| readyState',video.readyState,
             '| rVFC',typeof video.requestVideoFrameCallback==='function']);
  uiLog('i',['decodes attempted',decodeCount,'| last decode ms ago',
             lastDecodeAt?(Date.now()-lastDecodeAt):'never']);
  // Prove the relay leg independently of the camera.
  try{
    const r=await fetch('/api/session/'+encodeURIComponent(SESSION)+'/keepalive',{method:'POST'});
    const j=await r.json().catch(()=>({}));
    uiLog(r.ok?'i':'e',['relay keepalive',r.status,JSON.stringify(j)]);
  }catch(e){uiLog('e',['relay unreachable',e])}
  // Prove jsQR can decode a known-good QR with no camera involved.
  try{
    const ok=await decodeProbeImage();
    uiLog(ok?'i':'e',['jsQR decode probe',ok?('OK -> '+ok):'FAILED']);
  }catch(e){uiLog('e',['decode probe threw',e])}
  uiLog('i',['=== END SELF TEST ===']);
}

// Renders a real QR on a canvas from the server and decodes it, so a failing
// decoder can be told apart from a failing camera or an unreadable label.
async function decodeProbeImage(){
  if(typeof jsQR!=='function')return null;
  const img=await new Promise((res,rej)=>{
    const i=new Image();i.onload=()=>res(i);i.onerror=rej;
    i.src='/static/probe-qr.png?t='+Date.now();
  });
  return decodeWithJsQR(img,img.naturalWidth,img.naturalHeight);
}

// --- pairing heartbeat ------------------------------------------------------
async function ping(){
  try{
    const r=await fetch('/api/session/'+encodeURIComponent(SESSION)+'/pair',{method:'POST'});
    setState(r.ok?'connected':'session expired',r.ok?'ok':'bad');
  }catch(e){setState('offline','bad')}
}
ping();setInterval(ping,15000);

// Autostart. Some browsers only grant the camera after a user gesture, so if
// the stream is not running shortly after load we stop pretending and tell the
// user to press the button rather than leaving a black rectangle on screen.
console.log(LOG,'attempting camera autostart');
startCamera();
setTimeout(()=>{
  if(stream)return;
  console.warn(LOG,'autostart did not produce a stream - user gesture required');
  setDiag('dCam','not started - press START CAMERA');
  setAuto('Camera not started','bad','\u2014','Open DEBUG \u2192 START CAMERA and allow camera access.');
  const st=document.getElementById('lastSt');
  if(st&&!everSent){
    st.textContent='Press START CAMERA and allow camera access.';
    st.className='st wait';
  }
},3500);
</script></body></html>"""


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail},
    )


if __name__ == "__main__":
    # Local run: python app.py  (Railway uses the Procfile instead)
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
    )
