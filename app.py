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
  GET  /static/jsQR.js                      vendored QR decoder for the phone page
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

APP_VERSION = "1.0.0"

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

STATIC_DIR = Path(__file__).resolve().parent / "static"

# --- Tunables (override with Railway environment variables) ----------------
SESSION_TTL = int(os.environ.get("OPENEYES_SESSION_TTL", "7200"))      # 2h idle
MAX_EVENTS = int(os.environ.get("OPENEYES_MAX_EVENTS", "200"))         # ring size
MAX_SESSIONS = int(os.environ.get("OPENEYES_MAX_SESSIONS", "500"))     # abuse cap
POLL_TIMEOUT = int(os.environ.get("OPENEYES_POLL_TIMEOUT", "25"))      # long poll
SSE_HEARTBEAT = int(os.environ.get("OPENEYES_SSE_HEARTBEAT", "20"))    # keep alive

# A Board ID is short, printable and has no spaces. This is a sanity filter,
# not a security boundary — the viewer treats anything it receives as a
# lookup key and simply reports "Board not found" when it does not match.
BOARD_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class Session:
    """One PC viewer window. Lives in memory only."""

    __slots__ = ("sid", "created", "last_seen", "phone_paired", "events", "seq", "signal")

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
        self.touch()
        # Wake every waiter, then immediately re-arm for the next scan.
        self.signal.set()
        self.signal = asyncio.Event()
        return event

    def since(self, after: int) -> list[dict]:
        return [e for e in self.events if e["seq"] > after]


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
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    _sweep()
    return {
        "ok": True,
        "service": "openeyes-phone-relay",
        "version": APP_VERSION,
        "sessions": len(SESSIONS),
        "uptime_s": int(time.time() - START_TIME),
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


@app.get("/static/jsQR.js")
def static_jsqr():
    path = STATIC_DIR / "jsQR.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="jsQR.js is not bundled")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
    return HTMLResponse(_scanner_page(session))


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
    return _SCANNER_TEMPLATE.replace("__SESSION__", json.dumps(session_id))


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
.hidden{display:none}
</style></head><body>
<header><h1>OpenEyes Board Scanner</h1><div id="link">PC: <b id="linkState">connecting…</b></div></header>

<div id="wrap"><video id="v" playsinline muted autoplay></video><div id="frame"></div></div>

<main>
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

  <div class="hint">
    Keep this page open. Every label you scan is sent straight to the paired PC,
    which highlights and focuses that board in the 3D viewer.<br><br>
    Printed labels hold only the Board ID and never expire. This pairing page
    belongs to the PC viewer window that showed the QR — if the PC restarts,
    scan its new pairing QR again.
  </div>
</main>

<canvas id="c" class="hidden"></canvas>
<script src="/static/jsQR.js"></script>
<script>
const SESSION=__SESSION__;
const video=document.getElementById('v'),canvas=document.getElementById('c'),
      ctx=canvas.getContext('2d',{willReadFrequently:true}),
      lastId=document.getElementById('lastId'),lastSt=document.getElementById('lastSt'),
      linkState=document.getElementById('linkState');
let stream=null,scanning=false,lastSent='',lastSentAt=0;

function setState(t,cls){linkState.textContent=t;linkState.className=cls||''}
function setResult(id,msg,cls){
  if(id)lastId.textContent=id;
  lastSt.textContent=msg;lastSt.className='st '+(cls||'wait');
}

// --- send a Board ID to the relay ------------------------------------------
async function send(id,source){
  id=String(id||'').trim();
  if(!id)return;
  // Debounce: the camera sees the same label ~30x/second.
  const now=Date.now();
  if(id===lastSent&&now-lastSentAt<2500)return;
  lastSent=id;lastSentAt=now;
  setResult(id,'Sending…','wait');
  try{
    const r=await fetch('/api/session/'+encodeURIComponent(SESSION)+'/scan',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({board_id:id,source:source||'phone'})
    });
    if(r.status===404){setState('session expired','bad');setResult(id,'Pairing expired — rescan the PC pairing QR.','bad');return}
    if(!r.ok){const j=await r.json().catch(()=>({}));setResult(id,'Rejected: '+(j.detail||r.status),'bad');return}
    setState('connected','ok');
    setResult(id,'Sent to the PC ✓','ok');
    if(navigator.vibrate)navigator.vibrate(60);
  }catch(e){
    setState('offline','bad');
    setResult(id,'Network error — check signal and try again.','bad');
  }
}

document.getElementById('send').onclick=()=>{
  const el=document.getElementById('manual');
  const v=el.value.trim();
  if(!v)return;
  lastSent='';                       // manual entry always goes through
  send(v,'manual');el.value='';
};
document.getElementById('manual').addEventListener('keydown',e=>{
  if(e.key==='Enter')document.getElementById('send').click();
});

// --- live camera scanning ---------------------------------------------------
async function startCamera(){
  if(stream)return;
  try{
    stream=await navigator.mediaDevices.getUserMedia({
      video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}},
      audio:false
    });
    video.srcObject=stream;
    await video.play();
    scanning=true;
    document.getElementById('camBtn').textContent='⏹ STOP CAMERA';
    setResult('','Camera on. Fill the green box with the QR.','wait');
    requestAnimationFrame(tick);
  }catch(e){
    setResult('','Camera unavailable ('+(e&&e.name||'error')+'). Use PHOTO or type the ID.','bad');
  }
}
function stopCamera(){
  scanning=false;
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}
  video.srcObject=null;
  document.getElementById('camBtn').textContent='📷 START CAMERA';
}
document.getElementById('camBtn').onclick=()=>{stream?stopCamera():startCamera()};

function tick(){
  if(!scanning)return;
  if(video.readyState===video.HAVE_ENOUGH_DATA&&video.videoWidth){
    const w=Math.min(640,video.videoWidth),
          h=Math.round(video.videoHeight*(w/video.videoWidth));
    canvas.width=w;canvas.height=h;
    ctx.drawImage(video,0,0,w,h);
    try{
      const img=ctx.getImageData(0,0,w,h);
      const code=jsQR(img.data,w,h,{inversionAttempts:'attemptBoth'});
      if(code&&code.data)send(code.data,'camera');
    }catch(e){/* frame not ready */}
  }
  requestAnimationFrame(tick);
}

// --- single photo fallback --------------------------------------------------
document.getElementById('photoBtn').onclick=()=>document.getElementById('photo').click();
document.getElementById('photo').onchange=e=>{
  const f=e.target.files&&e.target.files[0];e.target.value='';
  if(!f)return;
  const img=new Image();
  img.onload=()=>{
    const w=Math.min(1280,img.width),h=Math.round(img.height*(w/img.width));
    canvas.width=w;canvas.height=h;
    ctx.drawImage(img,0,0,w,h);
    const d=ctx.getImageData(0,0,w,h);
    const code=jsQR(d.data,w,h,{inversionAttempts:'attemptBoth'});
    if(code&&code.data){lastSent='';send(code.data,'photo')}
    else setResult('','No QR found in that photo. Try again, closer and steadier.','bad');
    URL.revokeObjectURL(img.src);
  };
  img.onerror=()=>setResult('','Could not read that image.','bad');
  img.src=URL.createObjectURL(f);
};

// --- pairing heartbeat ------------------------------------------------------
async function ping(){
  try{
    const r=await fetch('/api/session/'+encodeURIComponent(SESSION)+'/pair',{method:'POST'});
    setState(r.ok?'connected':'session expired',r.ok?'ok':'bad');
  }catch(e){setState('offline','bad')}
}
ping();setInterval(ping,15000);

// Autostart the camera; HTTPS from Railway means this is allowed.
startCamera();
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
