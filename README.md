# OpenEyes Phone Relay

A tiny public HTTPS bridge that carries **one thing** between a phone and a PC: a Board ID string.

```
printed label          phone                  Railway relay              PC viewer
 (Board ID)   ──scan──▶  /scan?session=…  ──POST──▶  session channel  ──SSE──▶  focusBoardById()
```

The PC only ever dials **out**. There is no inbound port, no port forwarding, no VPN, and no requirement that the phone and PC share a network. That is the whole point: `Office_iot_5G` isolates its clients, so the LAN route is a dead end. This route ignores the LAN entirely.

## What it does not touch

- **Printed Board QR labels are unchanged.** They still encode the bare Board ID (`20260914122851-069`) and nothing else. They never expire. The pairing QR described below is a completely separate, temporary thing.
- **No 3D data crosses this relay.** Models, manifests, dimensions and project files never leave the PC. The relay sees a session id and a Board ID, nothing more.
- **No database, no disk writes.** All state is in memory with a 2-hour idle expiry. Redeploying just unpairs everyone.
- Search, Dimension, Door, Hide, Animation, printing, the Local Viewer and the Cloud Live Library are untouched. If the relay is down or unconfigured, Phone Link reports "Offline" and every other feature keeps working.

## Deploying to Railway

The relay is self-contained. If you only want to deploy the relay, push **the contents of this `relay/` folder** to the root of the `openeyes-phone-relay` GitHub repository:

```
openeyes-phone-relay/          <- repo root, NOT a relay/ subfolder
├── app.py
├── requirements.txt
├── Procfile
├── railway.json
├── runtime.txt
├── .gitignore
├── README.md
└── static/
    └── jsQR.js
```

`static/jsQR.js` is required — it is the QR decoder the phone page runs. Without it the phone can still type Board IDs by hand, but the camera will not decode.

Then:

1. Railway → **New Project** → **Deploy from GitHub repo** → `openeyes-phone-relay`.
2. Railway detects Python via Nixpacks and installs `requirements.txt`.
3. Settings → **Networking** → **Generate Domain**. You get something like `https://openeyes-phone-relay-production.up.railway.app`.
4. No environment variables are required. Railway supplies `$PORT`; the app reads it.

### Start command

```
uvicorn app:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 75
```

This is already in both `Procfile` and `railway.json`, so Railway picks it up automatically. Only paste it into Settings → Deploy → Custom Start Command if Railway fails to detect it.

`--timeout-keep-alive 75` matters: the PC holds an SSE stream open, and a shorter keep-alive causes a reconnect every minute. It still works without it, just noisily.

### Optional environment variables

| Variable | Default | Meaning |
|---|---|---|
| `OPENEYES_SESSION_TTL` | `7200` | Idle seconds before a pairing expires |
| `OPENEYES_POLL_TIMEOUT` | `25` | Long-poll hold time |
| `OPENEYES_SSE_HEARTBEAT` | `20` | Seconds between SSE keepalive frames |
| `OPENEYES_MAX_SESSIONS` | `500` | Cap on concurrent pairings |

## Connecting the PC

On the PC, in the project root (next to `START_LOCAL_TEST.bat`):

```
SET_RELAY_URL.bat
```

Paste the Railway URL. It checks `/health`, then writes `relay_url.txt`. Refresh the viewer — no server restart, the file is re-read on every page load.

Manual alternative: put the URL on its own line in `relay_url.txt`, or set `OPENEYES_RELAY_URL` before starting the server.

## API

Implemented exactly as the existing viewer client in `app/phone_viewer.py` already calls it. Do not rename these.

| Method | Path | Side | Purpose |
|---|---|---|---|
| `GET` | `/health` | — | Liveness. Returns service name, version, live session count |
| `POST` | `/api/session` | PC | Mint a channel → `{"session_id": "<32 hex>"}` |
| `POST` | `/api/session/{sid}/keepalive` | PC | Heartbeat → `{"phone_paired": bool}`; `404` = expired |
| `GET` | `/api/session/{sid}/events?after=N` | PC | SSE. Emits `ready`, then `scan` events |
| `GET` | `/api/session/{sid}/poll?after=N` | PC | Long-poll fallback → `{"events": [...]}` |
| `GET` | `/scan?session={sid}` | Phone | Scanner page; loading it marks the phone paired |
| `POST` | `/api/session/{sid}/scan` | Phone | Submit a Board ID → `{"ok": true, "seq": N}` |
| `POST` | `/api/session/{sid}/pair` | Phone | Heartbeat from the scanner page |
| `GET` | `/static/jsQR.js` | Phone | Vendored QR decoder |

A `scan` event looks like:

```json
{"seq": 3, "board_id": "20260914122851-069", "source": "camera", "ts": 1789376188}
```

`seq` is monotonic per session. The viewer tracks the highest `seq` it has applied, so reconnecting replays anything missed during a dropped connection without re-applying anything twice.

### Design notes

- **SSE first, long poll as fallback.** The viewer tries `EventSource`; if the stream never opens (some corporate proxies buffer `text/event-stream` into uselessness) it falls back to `/poll`, which is plain `fetch` and gets through anywhere. WebSockets would add a third failure mode for no gain here — traffic is one small message per scan, and it is strictly one-directional.
- **CORS is wide open.** The viewer page lives on `http://127.0.0.1:8000` and the relay on `https://…railway.app`, so every call is cross-origin. Nothing here uses cookies or credentials, and the session id is the only capability, so `allow_origins=["*"]` is safe.
- **The session id is the security boundary.** 32 random hex characters, minted server-side, never guessable, expires on idle. Anyone holding it can push a Board ID to that viewer — which is exactly what pairing means. If a QR leaks, press **NEW SESSION** on the PC and the old one dies immediately.
- **Legacy QR tolerance.** If a label from an older version encodes a URL with `?part=<id>`, the relay lifts the Board ID out of the query string. This does not change what new labels contain.

## Testing

### 1. Relay is alive

```
https://<your-app>.up.railway.app/health
```

Expect:

```json
{"ok":true,"service":"openeyes-phone-relay","version":"1.0.0","sessions":0,"uptime_s":42}
```

If this fails, nothing else will. Check Railway's deploy logs before going further.

### 2. Relay works without any phone (pure curl, 30 seconds)

```bash
R=https://<your-app>.up.railway.app
SID=$(curl -s -X POST $R/api/session -H 'Content-Type: application/json' -d '{}' | python -c 'import sys,json;print(json.load(sys.stdin)["session_id"])')
echo $SID

# start a long poll in the background — it blocks, waiting for a scan
curl -s "$R/api/session/$SID/poll?after=0" &

# now push a board id, as the phone would
curl -s -X POST "$R/api/session/$SID/scan" -H 'Content-Type: application/json' \
     -d '{"board_id":"20260914122851-069"}'
```

The backgrounded poll should return immediately with that Board ID. If this works, the relay is correct and any remaining problem is on the PC or phone side.

### 3. PC pairing

1. Run `START_LOCAL_TEST.bat`. The header should now print your relay URL.
2. In SketchUp, **Upload Current Model** so a project exists.
3. Open `http://127.0.0.1:8000/local`.
4. The **Phone Link** chip at the top should go `Starting… → Connected`. If it says `Offline`, click it — it explains why.
5. Press **SEARCH → PAIR PHONE**. A pairing QR appears.

### 4. Phone scan

1. Scan the pairing QR with the phone's normal camera app — **once**. The phone may be on mobile data, a different Wi-Fi, anywhere.
2. It opens the OpenEyes Board Scanner page over HTTPS. Allow camera access.
3. On the PC, the Phone Link line flips to **Paired ✓** within about five seconds.
4. Point the phone at a **printed board label**. The scanner shows the Board ID and "Sent to the PC ✓".

### 5. PC receives and focuses

On the PC, within roughly a second:

- The chip shows `Phone Link: Connected • 20260914122851-069`
- The SEARCH panel shows `Last scan: 20260914122851-069 ✓`
- The Search box is filled with the received ID
- **The 3D viewer highlights and focuses that board**, cabinet still visible

The browser console logs `[PHONE] received …`, `[BOARD] found`, `[BOARD] focused`.

If the board is not in the current project, the panel says `Board not found: <id>` — the relay delivered correctly, the ID just does not belong to the loaded cabinet.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Chip stays `Offline` | `relay_url.txt` empty or commented out | Run `SET_RELAY_URL.bat` and refresh |
| Chip stays `Reconnecting…` | Relay asleep or redeploying | Open `/health` in a browser to wake it, then press **RECONNECT** |
| Phone page says "pairing has expired" | PC viewer closed, restarted, or idle >2h | On the PC: **PAIR PHONE → NEW SESSION**, rescan |
| Phone camera will not start | Permission denied, or an in-app browser | Open the link in Chrome/Safari proper; or use **PHOTO**, or type the ID |
| `Board not found` on the PC | ID is not in the loaded project | Confirm the label belongs to the cabinet currently uploaded |
| Scan sent, PC shows nothing | PC lost the stream | Watch the chip; it reconnects on its own and replays missed scans |

## Running locally (development)

```bash
cd relay
pip install -r requirements.txt
python app.py            # binds 0.0.0.0:8080
```

For a local end-to-end test, point `relay_url.txt` at `http://127.0.0.1:8080`. The PC side accepts a plain-HTTP relay **only** on `127.0.0.1`/`localhost`, because a real remote relay must be HTTPS before a phone browser will grant camera access. That check lives in `_RELAY_LOCAL_RE` in `app/local_server.py`.
