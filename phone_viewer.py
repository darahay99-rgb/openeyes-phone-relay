import html
import json


def render_phone_viewer(
    title: str,
    detail: str,
    asset_url: str,
    token: str,
    initial_part: str = "",
    manifest_url: str | None = None,
    service_worker: bool = True,
    sw_url: str = "",
    module_base: str = "https://unpkg.com/three@0.169.0",
    print_url: str | None = None,
    jsqr_url: str = "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js",
    relay_url: str = "",
    pairing_qr_url: str = "",
) -> str:
    """Render the shared 3D viewer page (used by both the Cloud /live flow and
    the PC-only /local flow). ``manifest_url``/``service_worker``/``module_base``/
    ``print_url``/``jsqr_url`` are optional overrides used by the Local flow;
    when omitted, behavior is identical to the original Cloud-only signature
    so /live/* is unaffected. ``module_base`` points the importmap at where
    three.module.js and examples/jsm/ live — the Cloud flow keeps using the
    unpkg CDN by default, while the Local flow passes "/vendor/three" so the
    viewer has zero internet dependency on the PC. ``print_url`` (Local only)
    enables the Print All / Print Selected buttons in the Search panel.
    ``jsqr_url`` points at the jsQR library used for Board Label QR scanning
    (canvas-based, works in every browser — no native BarcodeDetector
    dependency); Local passes "/vendor/jsqr/jsQR.js" for the same zero-
    internet-dependency reason as module_base.

    ``relay_url``/``pairing_qr_url`` (Local only) enable PHONE LINK: the
    viewer opens an outbound listening connection to a small public HTTPS
    relay, shows a pairing QR, and then automatically focuses whichever
    board a paired phone scans — even when the phone is on a completely
    different Wi-Fi network. Both default to "" so the Cloud /live flow is
    byte-for-byte unaffected, and so the Local flow degrades to exactly its
    previous behavior (manual Search only) when no relay is configured."""
    _sw = sw_url or f"/live/sw.js"
    values = {
        "__TITLE__": html.escape(title), "__DETAIL__": html.escape(detail),
        "__ASSET__": json.dumps(asset_url),
        "__TOKEN__": json.dumps(token),
        "__MANIFEST__": json.dumps(manifest_url if manifest_url is not None else f"/live/assets/{token}/manifest.json"),
        "__INITIAL_PART__": json.dumps(initial_part),
        "__MODULE_BASE__": module_base,
        "__PRINT_URL__": json.dumps(print_url or ""),
        "__JSQR_URL__": jsqr_url,
        "__RELAY_URL__": json.dumps((relay_url or "").rstrip("/")),
        "__PAIRING_QR_URL__": json.dumps(pairing_qr_url or ""),
        "__SW_REGISTER__": (
            (
                "if('serviceWorker'in navigator)navigator.serviceWorker.register("
                f"{json.dumps(_sw)},{{scope:{json.dumps(_sw.rsplit('/', 1)[0] + '/')}}}"
                ").catch(()=>{});"
            )
            if service_worker else ""
        ),
    }
    page = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>__TITLE__</title>
<style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#000;color:#fff;font-family:Arial,sans-serif}
:root{--sidebar-w:96px}
@media (max-width:480px){:root{--sidebar-w:74px}}
#view{position:absolute;left:0;right:var(--sidebar-w);top:50px;bottom:0;touch-action:none;transition:bottom .15s ease,top .15s ease,right .15s ease}
canvas{display:block;width:100%;height:100%}
header{position:absolute;z-index:5;inset:0 var(--sidebar-w) auto 0;min-height:50px;padding:6px 13px;background:#090909;border-bottom:1px solid #292929;font-weight:700;font-size:14px;overflow:hidden}
header small{display:block;margin-top:2px;color:#aaa;font-size:10px;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#boardInfo{color:#ffe45c;font-weight:700}
.rightBar{position:absolute;z-index:6;top:0;right:0;bottom:0;width:var(--sidebar-w);padding:8px 6px;display:flex;flex-direction:column;gap:8px;background:#090909;border-left:1px solid #292929;overflow-y:auto}
.rightBar button,.panel button{border:1px solid #333;border-radius:10px;background:#141414;color:#cfcfcf;font-weight:700;white-space:normal;min-height:40px}
.rightBar button{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:10px 4px;font-size:10px;min-height:68px;width:100%}
.rightBar button .icon{font-size:19px;line-height:1}
.rightBar button.active{background:#0b57d0;border-color:#4c8dff;color:#fff}
/* ---- Phone rail: TikTok-style icons ---------------------------------------
   Narrow screens only, so the PC viewer keeps its labelled buttons. The rail
   loses its panel and border and floats over the 3D: no background box, no
   text, just icons. The model gets the full width of the screen, which
   matters most on a phone held in portrait. A drop shadow keeps the glyphs
   readable over both the white cabinet and the dark background.            */
@media (max-width:820px){
  :root{--sidebar-w:60px}
  .rightBar{background:transparent;border-left:none;padding:6px 4px;gap:14px;
    justify-content:center;pointer-events:none}
  .rightBar button{background:transparent;border:none;min-height:0;padding:4px 0;
    width:100%;gap:0;pointer-events:auto;
    filter:drop-shadow(0 1px 3px rgba(0,0,0,.95)) drop-shadow(0 0 1px rgba(0,0,0,.8))}
  .rightBar button .lbl{display:none}
  .rightBar button .icon{font-size:27px}
  .rightBar button:active{transform:scale(.88)}
  /* Active tool is shown by a tinted glyph rather than a filled box. */
  .rightBar button.active{background:transparent;border:none;color:#4c8dff;
    filter:drop-shadow(0 0 6px rgba(76,141,255,.85))}
}
.panel{position:absolute;z-index:8;left:0;right:var(--sidebar-w);bottom:0;max-height:24vh;overflow:auto;padding:7px 9px;border:1px solid #2c2c2c;border-top-width:1px;border-left:none;border-right:none;border-bottom:none;background:#000000b3;box-shadow:0 -4px 16px #0009;transition:max-height .15s ease,right .15s ease}
.panel.collapsed{max-height:36px;overflow:hidden}
.hidden{display:none!important}
.row{display:flex;gap:6px;flex-wrap:wrap}
.row input{min-width:150px;flex:1;border:1px solid #444;border-radius:8px;background:#050505;color:#fff;padding:9px;min-height:40px}
.result{padding:8px 3px;border-bottom:1px solid #333}
.result small{color:#bbb}
.close{float:right;min-height:32px;min-width:32px}
.badge{display:inline-block;padding:2px 6px;border-radius:99px;background:#284;color:#fff;font-size:10px}
#toast{position:absolute;z-index:9;left:50%;top:58px;transform:translateX(-50%);max-width:90%;padding:6px 11px;border-radius:8px;background:#111d;text-align:center;pointer-events:none;font-size:12px}
.dim{color:#ffe45c}
.info{line-height:1.5;font-size:13px}
.scanVideo{width:100%;max-height:36vh;background:#000;border-radius:8px}
.speed{min-height:36px;border-radius:8px;background:#0a0a0a;color:#fff;border:1px solid #333;font-size:11px;padding:2px 4px}
.subtools button{flex:1;min-width:64px}
.animRow{overflow-x:auto;flex-wrap:nowrap;-webkit-overflow-scrolling:touch}
.animDock{display:flex;align-items:center;gap:10px;padding:8px 12px;max-height:none;overflow-x:auto;overflow-y:hidden;white-space:nowrap}
.animInfo{display:flex;align-items:center;gap:8px;flex:0 0 auto}
.animInfo .icon{color:#4c8dff;font-size:17px}
.animInfoTitle{color:#4c8dff;font-weight:700;font-size:12px}
.animInfoStep{color:#aaa;font-size:11px}
.vDivider{width:1px;align-self:stretch;background:#333;flex:0 0 auto}
.animRow button{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-width:62px;padding:6px 8px;font-size:9px}
.animRow button .icon{font-size:15px}
.animRow button.active{background:#0b57d0;border-color:#4c8dff;color:#fff}
.speedBox{display:flex;align-items:center;gap:6px;flex:0 0 auto}
.speedBox .icon{font-size:15px;color:#aaa}
.speedLbl{font-size:9px;color:#aaa}
.animRow button{flex:0 0 auto;min-width:66px}
.panelHead{display:flex;align-items:center;justify-content:space-between;gap:6px}
.panelHead h3{margin:0 0 4px;font-size:13px}
.panelHeadBtns{display:flex;gap:4px}
.minBtn{min-height:28px;min-width:30px;padding:2px 6px !important;font-size:14px}
.dimModes{display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;margin-top:2px}
.fullWidthRow{display:grid;grid-template-columns:1fr;gap:5px;margin-top:5px}
.dimModes button{font-size:11px;padding:6px 3px}
.dimModes button .short{display:none}
@media (max-width:480px){.dimModes button .full{display:none}.dimModes button .short{display:inline}}
.dimSubModes{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:4px}
.dimSideModes{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:4px;margin-top:4px}
.dimPlacementModes{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-top:4px}
.dimPlacementModes button{font-size:10px;padding:6px 3px;min-height:34px}
.dimPlacementModes button.active::before{content:'✓ '}
.dimSubModes button,.dimSideModes button{font-size:11px;padding:6px 3px;min-height:34px}
.dimSubModes button.active::before,.dimSideModes button.active::before{content:'✓ '}
.dimStatus{margin:0;padding:6px 8px;border:1px solid #2c2c2c;border-radius:8px;background:#080808;color:#ffe45c;font-weight:700;line-height:1.25;font-size:11px;display:flex;align-items:center;justify-content:center;text-align:center}
.dimActions{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-top:4px}.dimActions button,.dimActions .dimStatus{min-height:32px;padding:4px 5px;font-size:9px}.dimCompactOffset{display:grid!important;grid-template-columns:auto 72px minmax(90px,.7fr) minmax(140px,1.3fr);gap:4px!important;align-items:center;margin-top:4px!important}.dimCompactOffset input,.dimCompactOffset select{min-height:30px;padding:4px!important;font-size:10px!important}.dimCompactOffset .dimStatus{min-height:30px;padding:4px 6px;font-size:9px}
.dimModes button.active{background:#0b57d0;border-color:#4c8dff}
#fallbackBanner{position:absolute;z-index:7;left:0;right:var(--sidebar-w);top:50px;padding:5px 10px;background:#1a1a1a;color:#ffe45c;font-size:11px;text-align:center;border-bottom:1px solid #333}
/* PHONE LINK status chip — deliberately tiny and tucked into the header's
   existing right edge so it adds no new row, bar or panel to the viewer. */
#phoneChip{position:absolute;z-index:7;top:9px;right:calc(var(--sidebar-w) + 9px);display:flex;align-items:center;gap:6px;max-width:42vw;padding:4px 9px;border:1px solid #2c2c2c;border-radius:99px;background:#0d0d0d;color:#9a9a9a;font-size:10px;font-weight:700;line-height:1.2;cursor:pointer;overflow:hidden}
#phoneChip .pcDot{width:8px;height:8px;border-radius:50%;background:#555;flex:0 0 auto}
#phoneChip .pcDot.ok{background:#00c853}#phoneChip .pcDot.warn{background:#ffb300}#phoneChip .pcDot.bad{background:#d32f2f}
#phoneChip .pcTxt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#phoneChip .pcLast{color:#ffe45c;font-weight:400}
@media (max-width:480px){#phoneChip{max-width:36vw;font-size:9px;padding:3px 7px}}
#pairPanel .pairWrap{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}
#pairPanel .pairQr{width:150px;height:150px;background:#fff;border-radius:10px;padding:6px;flex:0 0 auto}
#pairPanel .pairText{flex:1;min-width:180px;font-size:12px;line-height:1.55;color:#cfcfcf}
#pairPanel .pairText b{color:#fff}
#pairPanel .pairNote{color:#8d8d8d;font-size:11px}
#pairPanel code{background:#191919;padding:2px 6px;border-radius:4px;word-break:break-all}
.phoneStatus{margin-top:5px;padding:6px 9px;border:1px solid #2c2c2c;border-radius:8px;background:#080808;font-size:11px;line-height:1.45;color:#9a9a9a;word-break:break-all}
.phoneStatus b{color:#cfcfcf}
.phoneStatus .okTxt{color:#00e676;font-weight:700}
.phoneStatus .badTxt{color:#ff8a80;font-weight:700}
.phoneStatus .waitTxt{color:#ffb300;font-weight:700}
</style></head><body><header>__TITLE__<small>__DETAIL__</small><small id="boardInfo" class="hidden"></small></header><div id="phoneChip" class="hidden" title="Phone Link — tap to show the pairing QR"><span class="pcDot"></span><span class="pcTxt">Phone Link: Offline</span></div><div id="fallbackBanner" class="hidden">Whole cabinet fallback — individual board metadata unavailable</div><div id="view"></div><div id="toast">Loading 3D…</div>
<div class="rightBar"><button id="animation"><span class="icon">▶</span><span class="lbl">ANIMATION</span></button><button id="dimension"><span class="icon">📐</span><span class="lbl">DIMENSION</span></button><button id="search"><span class="icon">🔍</span><span class="lbl">SEARCH</span></button><button id="doorBtn"><span class="icon">🚪</span><span class="lbl">DOOR</span></button><button id="hideModeBtn"><span class="icon">👁</span><span class="lbl">HIDE</span></button><button id="unhideAllBtn"><span class="icon">👁‍🗨</span><span class="lbl">UNHIDE ALL</span></button><button id="clearDimensionBtn"><span class="icon">✕</span><span class="lbl">CLEAR</span></button><button id="backBtn"><span class="icon">◀</span><span class="lbl">BACK</span></button></div>
<div id="animationPanel" class="panel hidden animDock"><div class="animInfo"><span class="icon">▶</span><div><div class="animInfoTitle">ANIMATION</div><div class="animInfoStep" id="animStepText">Step 0 / 0</div></div></div><div class="vDivider"></div><div class="row subtools animRow"><button id="play"><span class="icon">▶</span><span class="lbl">PLAY</span></button><button id="pause"><span class="icon">⏸</span><span class="lbl">PAUSE</span></button><button id="replay"><span class="icon">↻</span><span class="lbl">REPLAY</span></button><button id="explode"><span class="icon">💥</span><span class="lbl">EXPLODE</span></button><button id="prev"><span class="icon">←</span><span class="lbl">PRE</span></button><button id="next"><span class="icon">→</span><span class="lbl">NEXT</span></button></div><div class="vDivider"></div><div class="speedBox"><span class="icon">⏱</span><div><div class="speedLbl">SPEED</div><select id="speed"><option value="0.5">0.5×</option><option value="1" selected>1.0×</option><option value="1.5">1.5×</option><option value="2">2.0×</option></select></div></div><div class="vDivider"></div><div class="speedBox"><span class="icon">📏</span><div><div class="speedLbl">DISTANCE</div><select id="animDistance"><option value="0.5">Near</option><option value="1" selected>Normal</option><option value="1.6">Far</option></select></div></div></div>
<div id="dimensionPanel" class="panel hidden"><div class="dimModes"><button id="boardSize" class="active"><span class="full">3 POINT</span><span class="short">3 POINT</span></button><button id="selectBoards"><span class="full">MULTI SELECT</span><span class="short">MULTI</span></button><button id="pointToPoint"><span class="full">POINT</span><span class="short">POINT</span></button></div><div id="threePointSettingsRow" class="dimPlacementModes"><button id="tpLeft">LEFT</button><button id="tpRight">RIGHT</button><button id="tpFront">FRONT</button><button id="tpBack">BACK</button><button id="tpTop">TOP</button><button id="tpBottom">BOTTOM</button></div><div id="threePointOffsetRow" class="dimCompactOffset"><span style="font-size:11px;color:#9a9a9a;white-space:nowrap">OFFSET (mm)</span><input type="number" id="tpOffsetInput" value="0" style="width:70px;background:#141414;border:1px solid #333;border-radius:8px;color:#cfcfcf;padding:6px"><select id="tpTickSelect" style="background:#141414;border:1px solid #333;border-radius:8px;color:#cfcfcf;padding:6px;flex:1"><option value="in">TICK IN</option><option value="out">TICK OUT</option></select></div><div id="multiPlacementRow" class="dimPlacementModes hidden"><button id="placeMiddle" class="active">MIDDLE</button><button id="placeLeft">LEFT</button><button id="placeRight">RIGHT</button><button id="placeTop">TOP</button><button id="placeBottom">BOTTOM</button><button id="placeFront">FRONT</button><button id="placeBack">BACK</button></div><div class="dimActions"><div id="dimStatus" class="dimStatus">Select a board</div><button id="doneDimension">✓ DONE</button></div></div>
<div id="searchPanel" class="panel hidden"><div class="row"><button id="scan">📷 SCAN QR</button><button id="pairPhone" class="hidden">📱 PAIR PHONE</button></div><div class="row"><input id="query" placeholder="Enter Label ID"><button id="find">SEARCH</button></div><div id="phoneStatus" class="phoneStatus hidden"></div><div class="row"><button id="printAll" class="hidden">🖨 Print All</button><button id="printSelected" class="hidden">🖨 Print Selected</button></div><div id="results"></div></div>
<div id="doorPanel" class="panel hidden"><div class="dimStatus" style="margin:0">Tap any board you want to use as a door. First tap registers it; each tap opens/closes it.</div></div>
<div id="infoPanel" class="panel hidden"><button class="close" data-close="infoPanel">✕</button><div id="info" class="info"></div><div class="row"><button id="isolate">👁 Isolate</button><button id="showAll">↩ Show All</button><button id="assemblyStep">▶ Assembly Step</button></div></div>
<div id="scanPanel" class="panel hidden"><button class="close" data-close="scanPanel">✕</button><h3>Scan QR / Barcode</h3><video id="scanVideo" class="scanVideo" autoplay playsinline></video><input id="scanPhotoInput" type="file" accept="image/*" capture="environment" class="hidden"><button id="scanPhotoBtn" class="hidden">📷 TAKE PHOTO / SCAN QR</button><p id="scanHelp">Point the camera at an OpenEyes Label.</p></div>
<div id="pairPanel" class="panel hidden"><button class="close" data-close="pairPanel">✕</button><div class="panelHead"><h3>Open on a phone</h3></div><div class="pairWrap"><img id="pairQrImg" class="pairQr hidden" alt="Pairing QR"><div class="pairText"><div id="pairSteps"><b>1.</b> Open the phone camera and scan this QR <b>once</b>.<br><b>2.</b> The phone opens this cabinet in <b>3D on the phone itself</b>.<br><b>3.</b> In the phone viewer press SEARCH → SCAN QR, then scan any printed board label — that board is selected, highlighted and zoomed <b>on the phone</b>.</div><div class="pairNote" id="pairStatus" style="margin-top:6px"></div><div class="row" style="margin-top:7px"><button id="pairNewSession">↻ RE-PUBLISH</button><button id="pairRetry">⇄ RECONNECT</button></div><div class="pairNote" style="margin-top:6px">This QR carries the published project link. Printed board labels are different — they hold only a permanent Board ID and never expire.</div></div></div></div>
<script src="__JSQR_URL__"></script>
<script type="importmap">{"imports":{"three":"__MODULE_BASE__/build/three.module.js","three/addons/":"__MODULE_BASE__/examples/jsm/"}}</script><script type="module">
import * as THREE from 'three';import{OrbitControls}from'three/addons/controls/OrbitControls.js';import{GLTFLoader}from'three/addons/loaders/GLTFLoader.js';import{ColladaLoader}from'three/addons/loaders/ColladaLoader.js';
const asset=__ASSET__,projectToken=__TOKEN__,manifestUrl=__MANIFEST__,initialPart=__INITIAL_PART__,printUrl=__PRINT_URL__,relayUrl=__RELAY_URL__,pairingQrUrl=__PAIRING_QR_URL__;const host=document.getElementById('view'),toast=document.getElementById('toast');
const scene=new THREE.Scene();scene.background=new THREE.Color(0x000000);const camera=new THREE.PerspectiveCamera(40,1,.001,10000);camera.position.set(3,2,4);const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=THREE.SRGBColorSpace;host.appendChild(renderer.domElement);const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;scene.add(new THREE.HemisphereLight(0xffffff,0x333333,2.5));const sun=new THREE.DirectionalLight(0xffffff,2.2);sun.position.set(4,8,5);scene.add(sun);
let root,manifest={parts:[],dimensions:[],motions:[]},partMap=new Map(),nodeToPart=new Map(),motionMap=new Map(),nodeToMotion=new Map(),ordered=[],step=-1,timer=null,dimensionObjects=[],stream=null,selectedId='',measurePoints=[],measureTotalMm=0,mmPerUnit=1000,unitsConfirmed=false,declaredMmPerUnit=null,chainParts=[],chainObjects=[],chainResultObjects=[],modelReady=false,completedDimensionGroups=[],completedPointGroups=[],boardDimObjects=[];
// New user-facing state (replaces the old TICK IN/TICK OUT/L-R-Top-B
// naming). chainPlacement drives WHERE a MULTI SELECT dimension chain
// is drawn. The old internal chainStyle/chainSide variables are kept
// (generateDimensionChain() still reads them) but are now DERIVED from
// chainPlacement via applyChainPlacement() rather than being set
// directly by any visible button -- no TICK IN/TICK OUT button exists
// anymore.
let chainPlacement='middle+front',chainStyle='in',chainSide='front',chainMiddle=true,chainPlacements=new Set(['front']);
// 3 POINT placement settings (per explicit request): which edge each of
// the 3 axes anchors to (Left/Right for the board's W axis, Front/Back
// for its D axis, Top/Bottom for its thickness axis), plus a
// configurable OFFSET distance and TICK IN (inset, toward center) /
// TICK OUT (outset, beyond the board's true edge) direction. Defaults
// match the ORIGINAL 3 POINT corner exactly (nothing ticked = Left,
// Front, Top, offset 0) -- zero behavior change for anyone who never
// touches these settings.
let threePointSides={left:false,right:false,front:false,back:false,top:false,bottom:false},threePointOffsetMm=0,threePointTickMode='in';
function applyChainPlacement(){
  const sides=[...chainPlacements];
  if(chainMiddle){chainPlacement=['middle',...sides].join('+');chainStyle='in';chainSide=sides[0]||'front'}
  else if(sides.length){chainPlacement=sides.join('+');chainStyle='out';chainSide=sides[0]}
  else{chainPlacement='none';chainStyle='in';chainSide='front'}
}
// Fixed, uniform outside-dimension offset (mm): every TICK OUT side (Left/
// Right/Top/Bottom) is drawn at exactly this distance beyond the cabinet's
// own outer boundary, so the four sides form a clean, balanced, symmetrical
// frame -- not a per-cabinet calculated value (no door-width/2, no A-B/4).
// This is DISPLAY/POSITION ONLY; it can never change a measured mm value.
const OUTSIDE_DIM_OFFSET_MM=120;
// --- Assembly Animation engine state ---------------------------------------
// animSteps[i] = {part, node, category, confidence, home:{pos,quat},
// start:{pos,quat}} built ONCE (buildAssemblySteps) and reused — never
// rebuilt per frame/click, per the performance requirement. stepByLabel is
// the SAME kind of Label ID -> index lookup map used everywhere else, so
// QR/Search/manual-tap can all resolve a step in O(1) without walking the
// scene.
let animSteps=[],stepByLabel=new Map(),animState='idle',animCurrentStep=-1,animTween=null,animGroupTween=null,animActiveNode=null,animAutoFocus=true,animSpeed=1,animDuplicateLabels=[],animDistanceMul=1,animFrame=null,animStepTimer=null;
// Interaction state machine: IDLE (normal orbit) | BOARD_SIZE | POINT_TO_POINT.
// `mode` is the live interaction state; `subMode` remembers which Dimension
// tool (board/points) was last active so re-opening Dimension resumes it.
let mode='idle',subMode='board';
function resize(){const w=host.clientWidth,h=host.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false)}addEventListener('resize',()=>{resize();applyViewInset()});resize();
// Lightweight camera tween used by fitWithContext() (Search/Scan auto-focus)
// so the move is smooth instead of an instant jump. Orbit/zoom keep working
// throughout and after: this only overrides camera.position/controls.target
// for the tween's short duration, controls.update() still runs every frame
// exactly as before when no tween is active.
let cameraTween=null;
function tweenCameraTo(targetPos,targetLookAt,duration=700){
  cameraTween={startPos:camera.position.clone(),targetPos,startTarget:controls.target.clone(),targetTarget:targetLookAt,t0:performance.now(),duration}
}
renderer.setAnimationLoop(()=>{
  if(cameraTween){
    const t=Math.min(1,(performance.now()-cameraTween.t0)/cameraTween.duration);
    const e=t*t*(3-2*t); // smoothstep
    camera.position.lerpVectors(cameraTween.startPos,cameraTween.targetPos,e);
    controls.target.lerpVectors(cameraTween.startTarget,cameraTween.targetTarget,e);
    if(t>=1)cameraTween=null
  }
  if(animTween&&!animTween.paused){
    const t=Math.min(1,(performance.now()-animTween.startTime)/animTween.duration),e=easeSnap(t);
    const s=animSteps[animTween.stepIndex];
    // Defensive: animSteps can be rebuilt into a NEW array mid-tween (the
    // DISTANCE control forces a rebuild), which could leave stepIndex
    // pointing past the end of the fresh array. This runs every single
    // frame, so an unguarded access here was the single most likely
    // source of a real crash reported from an actual running build
    // ("Cannot read properties of undefined (reading 'node')").
    if(s&&s.node){
      s.node.position.lerpVectors(animTween.fromPos,animTween.toPos,e);
      s.node.quaternion.slerpQuaternions(animTween.fromQuat,animTween.toQuat,e);
      if(t>=1){s.node.position.copy(animTween.toPos);s.node.quaternion.copy(animTween.toQuat);onBoardTweenComplete()}
    }else{
      animTween=null;
    }
  }
  if(animGroupTween){
    const t=Math.min(1,(performance.now()-animGroupTween.startTime)/animGroupTween.duration),e=easeOutExplode(t);
    animGroupTween.items.forEach(it=>{it.node.position.lerpVectors(it.fromPos,it.toPos,e);it.node.quaternion.slerpQuaternions(it.fromQuat,it.toQuat,e)});
    if(t>=1){animGroupTween.items.forEach(it=>{it.node.position.copy(it.toPos);it.node.quaternion.copy(it.toQuat)});animGroupTween=null}
  }
  controls.update();renderer.render(scene,camera)
});
function fit(object=root){if(!object)return;const box=new THREE.Box3().setFromObject(object),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),d=Math.max(size.x,size.y,size.z)||1;controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(d*1.5,d*.9,d*1.5));camera.near=d/1000;camera.far=d*100;camera.updateProjectionMatrix();controls.update()}
// Context-preserving focus used by selectPart() (Search/Scan/list-click/
// Animation-step selection): unlike fit(), the framing distance never goes
// below ~32% of the WHOLE cabinet's own diagonal, so focusing on a small
// board still keeps the surrounding cabinet visible instead of zooming in
// so tight all context is lost. Smoothly tweens instead of jumping.
function fitWithContext(object){
  if(!object||!root)return;
  const box=new THREE.Box3().setFromObject(object),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
  const cabinetDiag=new THREE.Box3().setFromObject(root).getSize(new THREE.Vector3()).length()||1;
  const d=Math.max(size.x,size.y,size.z,cabinetDiag*.32);
  camera.near=d/1000;camera.far=d*100;camera.updateProjectionMatrix();
  tweenCameraTo(center.clone().add(new THREE.Vector3(d*1.5,d*.9,d*1.5)),center)
}
function nodeKey(value){return String(value||'').toLowerCase().replace(/[^a-z0-9]/g,'')}
function metadataFor(id){return [...(manifest.parts||[]),...(manifest.motions||[])].find(x=>x.id===id)}
// Node matching: EXACT name match first (this is what the SketchUp Local
// Viewer plugin guarantees — it renames each board to its manifest Label
// before export, so the COLLADA node name equals the Label exactly). Loose
// substring matching is only a fallback for older/Cloud (assimp) exports
// whose node names may have punctuation stripped, and it is gated behind a
// minimum key length so a short id can't accidentally swallow an unrelated,
// much larger node (this was the root cause of both the wrong-board-picked
// and the wildly-wrong-unit-calibration bugs).
function nodesFor(id){
  if(!root)return[];
  const meta=metadataFor(id)||{},wanted=[id,meta.name,meta.abfPartNumber].map(nodeKey).filter(Boolean);
  if(!wanted.length)return[];
  let matches=[];
  root.traverse(o=>{const key=nodeKey(o.name);if(key&&wanted.includes(key))matches.push(o)});
  if(!matches.length){
    root.traverse(o=>{const key=nodeKey(o.name);if(!key)return;if(wanted.some(w=>w.length>=4&&(key===w||key.includes(w)||w.includes(key))))matches.push(o)});
  }
  if(!matches.length)return[];
  // Assimp can preserve the same component name on both a parent node and its
  // child mesh. Keep only the highest matching node to avoid moving twice.
  const set=new Set(matches);return matches.filter(o=>{let p=o.parent;while(p){if(set.has(p))return false;p=p.parent}return true})
}
// --- Unified hover/selection highlight ---------------------------------
// Viewer-only translucent OVERLAY meshes — never a material edit. Each
// highlighted mesh gets one child overlay sharing its exact geometry, so
// the highlight always covers the FULL board (every sub-mesh), never just
// one face/edge, and the original mesh.material is never touched, cloned,
// or replaced (nothing here can modify model/material data). The overlay
// is excluded from raycasting (`overlay.raycast=()=>{}`) so it never
// interferes with board/corner picking.
const overlays=new Map();
function addOverlay(mesh,hex,opacity){
  let overlay=overlays.get(mesh);
  if(!overlay){
    const mat=new THREE.MeshBasicMaterial({color:hex,transparent:true,opacity,depthWrite:false,side:THREE.DoubleSide});
    overlay=new THREE.Mesh(mesh.geometry,mat);
    overlay.renderOrder=15;overlay.raycast=()=>{};
    // Tag the overlay so it is skipped by paintNode()/restoreNode()'s own
    // traverse() calls below. node.traverse() walks a LIVE reference to
    // .children, so adding this overlay as a child DURING traversal (via
    // mesh.add(overlay) on the next line) would otherwise make traverse()
    // visit the overlay itself in the same pass — and since the overlay is
    // also a Mesh, that caused infinite addOverlay-on-overlay recursion
    // ("Maximum call stack size exceeded") the first time any board was
    // actually selected. This flag is the fix.
    overlay.userData.oeHighlightOverlay=true;
    mesh.add(overlay);overlays.set(mesh,overlay)
  }else{
    overlay.material.color.set(hex);overlay.material.opacity=opacity
  }
}
function removeOverlayFrom(mesh){
  const overlay=overlays.get(mesh);if(!overlay)return;
  mesh.remove(overlay);overlay.material.dispose();overlays.delete(mesh)
}
function paintNode(node,hex,opacity){node.traverse(o=>{if(o.isMesh&&!o.userData.oeHighlightOverlay)addOverlay(o,hex,opacity)})}
function restoreNode(node){node.traverse(o=>{if(o.isMesh&&!o.userData.oeHighlightOverlay)removeOverlayFrom(o)})}
const HOVER_COLOR=0x69f0ae,HOVER_OPACITY=.28,SELECT_COLOR=0x00c853,SELECT_OPACITY=.42;
let hoverPart=null,selectedPart=null;
// 3 POINT keeps a stack of selected boards. Each board owns its own
// dimension objects so BACK can remove only the most recent board/3-point
// marker while all earlier selections remain visible.
let threePointParts=[],threePointGroups=[];
function isInThreePoint(part){return part&&threePointParts.some(p=>p.id===part.id)}
function isInChain(part){return part&&chainParts.some(p=>p.id===part.id)}
function setHover(part){
  if(part===hoverPart)return;
  if(hoverPart&&hoverPart!==selectedPart&&!isInChain(hoverPart)&&!isInThreePoint(hoverPart))(partMap.get(hoverPart.id)||[]).forEach(restoreNode);
  hoverPart=part;
  if(hoverPart&&hoverPart!==selectedPart&&!isInChain(hoverPart)&&!isInThreePoint(hoverPart))(partMap.get(hoverPart.id)||[]).forEach(n=>paintNode(n,HOVER_COLOR,HOVER_OPACITY));
}
function setSelectedBoard(part){
  if(selectedPart&&selectedPart!==part)(partMap.get(selectedPart.id)||[]).forEach(restoreNode);
  selectedPart=part;
  if(selectedPart)(partMap.get(selectedPart.id)||[]).forEach(n=>paintNode(n,SELECT_COLOR,SELECT_OPACITY));
}
function clearSelectedBoard(){if(selectedPart){(partMap.get(selectedPart.id)||[]).forEach(restoreNode);selectedPart=null}}
function selectPart(id){
  const p=manifest.parts.find(x=>x.id===id);if(!p)return;selectedId=id;
  setSelectedBoard(p);
  const nodes=partMap.get(id)||nodesFor(id);
  if(nodes.length)fitWithContext(nodes[0]);
  updateBoardInfoHeader(p);
  document.getElementById('info').innerHTML=`<b>${esc(p.name)}</b> <span class="badge">${esc(p.id)}</span><br>Type: ${esc(p.type||'part')}<br>Size: ${num(p.size?.x)} × ${num(p.size?.y)} × ${num(p.size?.z)} mm<br>Material: ${esc(p.material||'-')}<br>Edge: ${esc(p.edgeBanding||'-')}<br>ABF: ${esc(p.abfPartNumber||'-')}`;
  show('infoPanel');history.replaceState(null,'',location.pathname+'?part='+encodeURIComponent(id))
}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function num(x){return Number(x||0).toFixed(1)}function mmText(x){return `${Number(x||0).toLocaleString(undefined,{maximumFractionDigits:1})} mm`}
function show(id){['animationPanel','dimensionPanel','searchPanel','doorPanel','infoPanel','scanPanel','pairPanel'].forEach(x=>{if(x!==id)document.getElementById(x).classList.add('hidden')});document.getElementById(id).classList.remove('hidden');applyViewInset()}
function hide(id){document.getElementById(id).classList.add('hidden');applyViewInset()}
// --- Main Side Bar section switching (UI layer only) -----------------------
// Only one of ANIMATION/DIMENSION/SEARCH/DOOR is ever open at a time; each
// opens its own compact BOTTOM INLINE control bar (show()/hide() already
// existed and already enforce "only one panel visible"). This layer adds:
// (a) pressing the SAME active button again collapses it, (b) a single
// global BACK button that closes whichever section is open, restoring
// existing state cleanly via the SAME exit functions each section already
// had (exitAnimation()/exitDimension()) rather than any new logic.
let activeMainSection=null;
function setMainSectionActive(name){
  document.querySelectorAll('.rightBar button').forEach(b=>b.classList.remove('active'));
  if(name)document.getElementById(name==='door'?'doorBtn':name==='hide'?'hideModeBtn':name).classList.add('active');
}
function closeActiveSection(){
  if(activeMainSection==='animation')exitAnimation();
  else if(activeMainSection==='dimension')exitDimension();
  else if(activeMainSection==='search'){hide('searchPanel');hide('scanPanel');stopScan()}
  else if(activeMainSection==='door')hide('doorPanel');
  else if(activeMainSection==='hide')hideModeActive=false;
  activeMainSection=null;setMainSectionActive(null)
}
function openMainSection(name){
  if(activeMainSection&&activeMainSection!==name)closeActiveSection();
  activeMainSection=name;setMainSectionActive(name);
  if(name==='animation'){show('animationPanel');buildAssemblySteps(false);updateAnimHeader(animCurrentStep)}
  else if(name==='dimension'){show('dimensionPanel');setDimensionMode(subMode)}
  else if(name==='search'){show('searchPanel')}
  else if(name==='door'){show('doorPanel');requireDoorMotionOrWarn()}
  else if(name==='hide'){hideModeActive=true;toast.textContent='👁 Tap any board to hide it'}
}
// Sidebar buttons are now true section selectors, not panel visibility
// toggles. Re-clicking the already-selected section keeps its bottom panel
// open; clicking a different sidebar section swaps directly to that panel.
// A bottom panel is hidden only when the sidebar has no active section
// (for example after the global BACK closes the current tool).
function toggleMainSection(name){openMainSection(name)}
// Closing the Scan camera — whether via its own ✕ button or the
// auto-close after a successful scan below — must fully reset
// activeMainSection back to null (via closeActiveSection()), not just
// hide scanPanel in isolation. REAL BUG this fixes: show('scanPanel')
// already hides searchPanel as a side effect (mutual exclusivity), so
// after closing the scanner the user was left with BOTH panels hidden
// but activeMainSection still stuck at 'search' and the Search button
// still marked active — meaning the very next click on Search would
// TOGGLE IT CLOSED instead of reopening it, leaving no way to scan
// another board without first clicking BACK. Confirmed directly: a
// real second click on #scan timed out ("element is not visible")
// after closing the scanner once.
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>{if(b.dataset.close==='scanPanel'){closeActiveSection()}else{hide(b.dataset.close)}stopScan()});
// --- Responsive layout: keep the 3D view visible around whatever panel/
// toolbar is actually on screen, instead of a fixed inset. -----------------
function applyViewInset(){
  const header=document.querySelector('header');
  const headerH=header?header.getBoundingClientRect().height:50;
  const bannerVisible=!document.getElementById('fallbackBanner').classList.contains('hidden');
  const openPanel=document.querySelector('.panel:not(.hidden)');
  let extra=0;
  if(openPanel&&!openPanel.classList.contains('collapsed')){
    extra=Math.min(openPanel.getBoundingClientRect().height,window.innerHeight*.25);
  }
  document.getElementById('view').style.top=(headerH+(bannerVisible?22:0))+'px';
  document.getElementById('view').style.bottom=extra+'px';
}
function prepareParts(){
  ordered=[...manifest.parts].filter(p=>nodesFor(p.id).length).sort((a,b)=>(a.assemblyOrder||0)-(b.assemblyOrder||0));
  partMap=new Map(ordered.map(p=>[p.id,nodesFor(p.id)]));
  nodeToPart=new Map();
  partMap.forEach((nodes,id)=>{const p=ordered.find(x=>x.id===id);nodes.forEach(n=>nodeToPart.set(n,p))});
  ordered.forEach(p=>partMap.get(p.id).forEach(n=>{n.userData.home=n.position.clone()}));
  // Backward-compatible DOOR fix: older exports may have an empty motions[]
  // even though manifest.parts still contains the original Door/Drawer name.
  // Recover those motions locally so the DOOR button works without forcing a
  // re-export just to populate manifest.motions.
  const declaredMotionIds=new Set((manifest.motions||[]).map(m=>m.id));
  const recovered=(manifest.parts||[]).flatMap(p=>{
    if(declaredMotionIds.has(p.id))return[];
    const name=String(p.name||'').toLowerCase();
    if(name.includes('drawer')||name.includes('tiroir'))return[{id:p.id,type:'drawer'}];
    if(name.includes('door'))return[{id:p.id,type:'door'}];
    return[];
  });
  if(recovered.length){manifest.motions=[...(manifest.motions||[]),...recovered];console.log('[OE-DOOR] Recovered',recovered.length,'motion(s) from part names')}
  motionMap=new Map((manifest.motions||[]).map(m=>[m.id,nodesFor(m.id)]));
  nodeToMotion=new Map();
  (manifest.motions||[]).forEach(m=>(motionMap.get(m.id)||[]).forEach(n=>nodeToMotion.set(n,m)));
  motionMap.forEach(nodes=>nodes.forEach(n=>{n.userData.motionHome=n.position.clone();n.userData.motionQuat=n.quaternion.clone();n.userData.motionScale=n.scale.clone()}));
  updateFeatureButtons()
}
function updateFeatureButtons(){const dims=(manifest.dimensions||[]).length,motions=[...motionMap.values()].filter(x=>x.length).length;document.getElementById('animation').title=ordered.length?`${ordered.length} mapped boards`:'No GLB boards mapped';document.getElementById('dimension').title=dims?`${dims} saved dimensions`:'Create dimensions in SketchUp before upload';document.getElementById('doorBtn').title=motions?`${motions} doors/drawers mapped`:'No mapped doors or drawers'}
// =============================================================================
// AUTO-ASSEMBLY ANIMATION ENGINE
// =============================================================================
// Board identity: every step below carries the SAME `part` object (a
// manifest.parts entry, keyed by its permanent Label ID) and the SAME
// `node` (from partMap/nodeToPart) used by Board Size, Select Boards,
// Search, and QR Scan — there is no separate animation-only board id.
//
// Classification (D): geometry-first. For each board we look at its WORLD
// bounding box size (which of X/Y/Z is thinnest = the panel's thickness
// axis) and its normalized position inside the CABINET's own bounding box
// (0=one extreme, 1=the other, along the axis relevant to that thickness
// direction). Board/part NAMES are never consulted. Ambiguous cases fall
// back to a generic category (shelf/divider) or 'other' rather than
// guessing a specific side.
const CATEGORY_GROUP={bottom:1,left:2,right:3,top:4,back:5,divider:6,shelf:7,drawer:8,door:9,other:10};
const CATEGORY_LABEL={bottom:'Bottom',left:'Left Side',right:'Right Side',top:'Top',divider:'Vertical Divider',shelf:'Shelf',back:'Back Panel',drawer:'Drawer / Internal',door:'Door / Front',other:'Other'};
// Detect the cabinet's OWN stable local axes rather than assuming world
// X/Y/Z always equals the cabinet's up/width/depth — important because
// an exported model can be rotated in the scene as a single rigid unit.
// Two-pass, fallback-safe: pass 1 classifies every board using world
// axes exactly as before (fast, zero risk for the extremely common
// not-rotated case); if enough "panel" boards agree on an up direction
// that meaningfully differs from world +Y, pass 2 re-derives an
// orthonormal up/depth/width frame from that vote and every direction
// calculation below uses THIS frame instead of raw world axes. Boards
// tipped fully onto their side (up-vote nearly perpendicular to gravity)
// are a known, documented limitation — the vote can't disambiguate that
// case from "wide, short cabinet" using panel normals alone.
function detectCabinetFrame(rawPanels){
  let sx=0,sy=0,sz=0,totalWeight=0;
  // CRITICAL: only panels whose thin-axis is a candidate "up" normal
  // (i.e. pass-1 classified them as bottom/top/shelf) get a vote here.
  // Including divider/back/door panels too was a REAL bug found via
  // real-browser testing: their thin-axis points in a DIFFERENT physical
  // direction (perpendicular to up), so summing everything together
  // produced a bogus diagonal "up" vote even for a perfectly ordinary,
  // axis-aligned, unrotated test cabinet — which then scrambled every
  // downstream category.
  const upLikeCategories=new Set(['bottom','top','shelf']);
  rawPanels.forEach(r=>{
    if(!r.thinDir||!r.weight||!upLikeCategories.has(r.category))return;
    const d=r.thinDir.clone();
    const ax=Math.abs(d.x),ay=Math.abs(d.y),az=Math.abs(d.z);
    if(ay>=ax&&ay>=az){if(d.y<0)d.negate()}
    else if(ax>=az){if(d.x<0)d.negate()}
    else{if(d.z<0)d.negate()}
    sx+=d.x*r.weight;sy+=d.y*r.weight;sz+=d.z*r.weight;totalWeight+=r.weight;
  });
  const worldUp=new THREE.Vector3(0,1,0);
  if(totalWeight<1e-6)return{up:worldUp,depth:new THREE.Vector3(0,0,1),width:new THREE.Vector3(1,0,0),rotated:false};
  const vote=new THREE.Vector3(sx,sy,sz);
  if(vote.lengthSq()<1e-9)return{up:worldUp,depth:new THREE.Vector3(0,0,1),width:new THREE.Vector3(1,0,0),rotated:false};
  vote.normalize();
  if(vote.dot(worldUp)>.97){
    // Not meaningfully rotated -- keep the existing, already-verified
    // world-axis system unchanged (zero regression risk).
    return{up:worldUp,depth:new THREE.Vector3(0,0,1),width:new THREE.Vector3(1,0,0),rotated:false};
  }
  const up=vote;
  // Build the other two axes orthogonal to the detected up, preferring
  // whichever of world X/Z is LEAST aligned with up as the seed (avoids
  // a degenerate near-parallel cross product).
  const seed=Math.abs(up.dot(new THREE.Vector3(0,0,1)))<Math.abs(up.dot(new THREE.Vector3(1,0,0)))?new THREE.Vector3(0,0,1):new THREE.Vector3(1,0,0);
  const width=new THREE.Vector3().crossVectors(up,seed).normalize();
  const depth=new THREE.Vector3().crossVectors(width,up).normalize();
  return{up,depth,width,rotated:true};
}
function classifyBoard(node,cabinetBox,frame){
  const box=new THREE.Box3().setFromObject(node),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
  const cabSize=cabinetBox.getSize(new THREE.Vector3());
  const nx=cabSize.x>1e-6?(center.x-cabinetBox.min.x)/cabSize.x:.5;
  const ny=cabSize.y>1e-6?(center.y-cabinetBox.min.y)/cabSize.y:.5;
  const dims=[{axis:'x',v:size.x},{axis:'y',v:size.y},{axis:'z',v:size.z}].sort((a,b)=>a.v-b.v);
  const thin=dims[0],mid=dims[1],big=dims[2];
  const isPanel=thin.v>1e-6&&(mid.v/thin.v>2.2)&&(big.v/thin.v>2.2);
  const thinDirWorld=thin.axis==='x'?new THREE.Vector3(1,0,0):thin.axis==='y'?new THREE.Vector3(0,1,0):new THREE.Vector3(0,0,1);
  const EDGE=.16;
  if(!frame||!frame.rotated){
    // Fast path: world axes (identical to the original, already-verified
    // behavior when the cabinet isn't meaningfully rotated).
    if(isPanel){
      if(thin.axis==='y'){
        if(ny<=EDGE)return{category:'bottom',confidence:1-ny/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
        if(ny>=1-EDGE)return{category:'top',confidence:(ny-(1-EDGE))/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
        return{category:'shelf',confidence:.6,thinDir:thinDirWorld,weight:mid.v*big.v};
      }
      if(thin.axis==='x'){
        if(nx<=EDGE)return{category:'left',confidence:1-nx/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
        if(nx>=1-EDGE)return{category:'right',confidence:(nx-(1-EDGE))/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
        return{category:'divider',confidence:.6,thinDir:thinDirWorld,weight:mid.v*big.v};
      }
      const nz=cabSize.z>1e-6?(center.z-cabinetBox.min.z)/cabSize.z:.5;
      return{category:'backOrDoor',confidence:.5,zSide:nz<.5?'near':'far',area:size.x*size.y,thinDir:thinDirWorld,weight:mid.v*big.v};
    }
    const m=.08,nz=cabSize.z>1e-6?(center.z-cabinetBox.min.z)/cabSize.z:.5;
    const inside=nx>m&&nx<1-m&&ny>m&&ny<1-m&&nz>m&&nz<1-m;
    return inside?{category:'drawer',confidence:.5,thinDir:thinDirWorld,weight:mid.v*big.v}:{category:'other',confidence:.2,thinDir:thinDirWorld,weight:mid.v*big.v};
  }
  // Rotated-frame path: project onto the DETECTED up/width/depth axes
  // instead of raw world X/Y/Z, via the cabinet's own corner extent
  // along each axis (robust to rotation, unlike a raw min/max on X/Y/Z).
  function normAlong(dir){
    const box2=cabinetBox,corners=[
      new THREE.Vector3(box2.min.x,box2.min.y,box2.min.z),new THREE.Vector3(box2.max.x,box2.min.y,box2.min.z),
      new THREE.Vector3(box2.min.x,box2.max.y,box2.min.z),new THREE.Vector3(box2.min.x,box2.min.y,box2.max.z),
      new THREE.Vector3(box2.max.x,box2.max.y,box2.min.z),new THREE.Vector3(box2.max.x,box2.min.y,box2.max.z),
      new THREE.Vector3(box2.min.x,box2.max.y,box2.max.z),new THREE.Vector3(box2.max.x,box2.max.y,box2.max.z),
    ];
    let mn=Infinity,mx=-Infinity;corners.forEach(c=>{const s=dir.dot(c);if(s<mn)mn=s;if(s>mx)mx=s});
    const v=dir.dot(center);
    return mx>mn?(v-mn)/(mx-mn):.5;
  }
  const nUpF=normAlong(frame.up);
  const thinAlongUp=Math.abs(thinDirWorld.dot(frame.up))>.7;
  const thinAlongWidth=Math.abs(thinDirWorld.dot(frame.width))>.7;
  if(isPanel){
    if(thinAlongUp){
      if(nUpF<=EDGE)return{category:'bottom',confidence:1-nUpF/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
      if(nUpF>=1-EDGE)return{category:'top',confidence:(nUpF-(1-EDGE))/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
      return{category:'shelf',confidence:.6,thinDir:thinDirWorld,weight:mid.v*big.v};
    }
    if(thinAlongWidth){
      const nW=normAlong(frame.width);
      if(nW<=EDGE)return{category:'left',confidence:1-nW/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
      if(nW>=1-EDGE)return{category:'right',confidence:(nW-(1-EDGE))/EDGE,thinDir:thinDirWorld,weight:mid.v*big.v};
      return{category:'divider',confidence:.6,thinDir:thinDirWorld,weight:mid.v*big.v};
    }
    const nD=normAlong(frame.depth);
    return{category:'backOrDoor',confidence:.5,zSide:nD<.5?'near':'far',area:size.x*size.y,thinDir:thinDirWorld,weight:mid.v*big.v};
  }
  const m=.08,nW2=normAlong(frame.width),nD2=normAlong(frame.depth);
  const inside=nUpF>m&&nUpF<1-m&&nW2>m&&nW2<1-m&&nD2>m&&nD2<1-m;
  return inside?{category:'drawer',confidence:.5,thinDir:thinDirWorld,weight:mid.v*big.v}:{category:'other',confidence:.2,thinDir:thinDirWorld,weight:mid.v*big.v};
}
// Start ("waiting") position per category, using the cabinet's OWN local
// frame (never assuming world X/Y/Z = the cabinet's up/left/front) and a
// distance derived from the CABINET's own boundary in that direction
// (never the board's own length, which made long shelves/side panels
// travel unrealistically far) plus a small clearance, clamped to a
// moderate range of the cabinet's diagonal so nothing starts absurdly
// far off-screen or uncomfortably close.
function categoryDirection(category,frame,node,cabinetBox){
  switch(category){
    case'bottom':return frame.up.clone().negate();
    case'top':return frame.up.clone();
    case'left':return frame.width.clone().negate();
    case'right':return frame.width.clone();
    case'divider':case'shelf':case'door':case'drawer':return frame.depth.clone();
    case'back':return frame.depth.clone().negate();
    default:{
      const c=cabinetBox.getCenter(new THREE.Vector3()),world=new THREE.Vector3();
      node.getWorldPosition(world);const dir=world.sub(c);
      if(dir.lengthSq()<1e-6)dir.copy(frame.up);
      return dir.normalize();
    }
  }
}
function startPosForDirection(dir,homePos,cabinetBox){
  const cabDiag=cabinetBox.getSize(new THREE.Vector3()).length()||1;
  function extentAlongDir(box,d){
    const corners=[new THREE.Vector3(box.min.x,box.min.y,box.min.z),new THREE.Vector3(box.max.x,box.min.y,box.min.z),
      new THREE.Vector3(box.min.x,box.max.y,box.min.z),new THREE.Vector3(box.min.x,box.min.y,box.max.z),
      new THREE.Vector3(box.max.x,box.max.y,box.min.z),new THREE.Vector3(box.max.x,box.min.y,box.max.z),
      new THREE.Vector3(box.min.x,box.max.y,box.max.z),new THREE.Vector3(box.max.x,box.max.y,box.max.z)];
    let mx=-Infinity;corners.forEach(p=>{const s=d.dot(p);if(s>mx)mx=s});
    return mx;
  }
  const clearance=cabDiag*.06;
  const boundaryDist=Math.max(extentAlongDir(cabinetBox,dir)-dir.dot(homePos),0)+clearance;
  const clampedDist=THREE.MathUtils.clamp(boundaryDist,cabDiag*.12,cabDiag*.45);
  return homePos.clone().add(dir.clone().multiplyScalar(clampedDist*animDistanceMul));
}
function computeStartPosition(node,category,homePos,cabinetBox,frame){
  return startPosForDirection(categoryDirection(category,frame,node,cabinetBox),homePos,cabinetBox);
}
// Category-aware fallback direction priority (tried in order if the
// preferred/natural direction collides with an already-assembled
// board). "front"/"back" are the cabinet's own DETECTED depth axis, not
// raw world Z, so this stays correct even for a rotated cabinet.
const COLLISION_DIRECTION_PRIORITY={
  shelf:['front','back','top','left','right','bottom'],
  divider:['front','back','top','left','right','bottom'],
  drawer:['front','back','top','left','right','bottom'],
  door:['front','back','top','left','right','bottom'],
  left:['left','front','top','back'],
  right:['right','front','top','back'],
  top:['top','front','left','right','back'],
  bottom:['bottom','front','left','right','back'],
  back:['back','top','left','right'],
  other:['front','back','top','left','right','bottom'],
};
function namedDirectionVector(name,frame){
  switch(name){
    case'front':return frame.depth.clone();
    case'back':return frame.depth.clone().negate();
    case'top':return frame.up.clone();
    case'bottom':return frame.up.clone().negate();
    case'left':return frame.width.clone().negate();
    case'right':return frame.width.clone();
    default:return null;
  }
}
// Real world-space bounding box at a CANDIDATE transform, preserving
// the node's actual center-to-origin offset (a node's local origin is
// not always its geometry's center) — temporarily applies the candidate
// transform, forces a matrixWorld update, measures the real box, then
// restores the node's original transform. Never permanently modifies
// the scene while testing.
function worldBoxAtCandidate(node,pos,quat){
  const origPos=node.position.clone(),origQuat=node.quaternion.clone();
  node.position.copy(pos);node.quaternion.copy(quat);node.updateMatrixWorld(true);
  const box=new THREE.Box3().setFromObject(node);
  node.position.copy(origPos);node.quaternion.copy(origQuat);node.updateMatrixWorld(true);
  return box;
}
// Samples 10 positions (was 4) along the candidate path and shrinks the
// tested box by ~3% (was a flat 85%) so boards can end up touching at
// their final position without a false positive, while still catching
// genuine mid-path overlaps.
function pathCollides(node,fromPos,toPos,quat,assembledBoxes){
  if(!assembledBoxes.length)return false;
  for(let s=1;s<10;s++){
    const p=fromPos.clone().lerp(toPos,s/10);
    const box=worldBoxAtCandidate(node,p,quat);
    const shrink=box.getSize(new THREE.Vector3()).multiplyScalar(.03);
    box.min.add(shrink);box.max.sub(shrink);
    for(const ab of assembledBoxes)if(box.intersectsBox(ab))return true;
  }
  return false;
}
function resolveStartPosition(step,cabinetBox,assembledBoxes,frame){
  if(!pathCollides(step.node,step.start.pos,step.home.pos,step.home.quat,assembledBoxes))return step.start.pos;
  const priority=COLLISION_DIRECTION_PRIORITY[step.category]||COLLISION_DIRECTION_PRIORITY.other;
  let best=null,bestDist=Infinity;
  priority.forEach(name=>{
    const dir=namedDirectionVector(name,frame);
    if(!dir)return;
    const candidate=startPosForDirection(dir,step.home.pos,cabinetBox);
    if(pathCollides(step.node,candidate,step.home.pos,step.home.quat,assembledBoxes))return;
    const d=candidate.distanceTo(step.home.pos);
    if(d<bestDist){bestDist=d;best=candidate}
  });
  if(best)return best;
  console.warn(`OpenEyes Animation: no collision-free path found for ${step.part.id} among ${priority.length} candidate directions — using the default path anyway (fallback).`);
  return step.start.pos;
}
// Builds animSteps ONCE (called lazily the first time it's needed — either
// the Animation panel opens, or a QR/Search/manual selection needs to
// resolve a step before the panel was ever opened). Deterministic: group
// by category (E), then bottom-to-top, then left-to-right, then Label ID
// as the final tie-breaker, so the SAME unchanged model always produces
// the SAME order (never raw mesh/scene order).
let animBuilt=false;
function buildAssemblySteps(force){
  if(animBuilt&&!force)return animDuplicateLabels;
  animSteps=[];stepByLabel=new Map();animDuplicateLabels=[];
  if(!ordered.length){animBuilt=true;return animDuplicateLabels}
  const cabinetBox=new THREE.Box3().setFromObject(root);
  const seen=new Map();
  // Pass 1: classify with world axes (cheap, already-verified) to find
  // candidate "panel" boards for the up-axis vote.
  const pass1=[];
  ordered.forEach(p=>{
    seen.set(p.id,(seen.get(p.id)||0)+1);
    const nodes=partMap.get(p.id)||[];
    const node=nodes[0];
    if(!node)return;
    pass1.push({part:p,node,result:classifyBoard(node,cabinetBox,null)});
  });
  const frame=detectCabinetFrame(pass1.map(r=>r.result));
  animFrame=frame;
  // Pass 2: only re-classify (using the detected local frame) if the
  // cabinet is actually meaningfully rotated -- otherwise pass 1's
  // results are reused as-is (identical to the pre-rotation-aware
  // behavior, zero regression for the common case).
  const raw=pass1.map(r=>{
    const result=frame.rotated?classifyBoard(r.node,cabinetBox,frame):r.result;
    const center=new THREE.Box3().setFromObject(r.node).getCenter(new THREE.Vector3());
    return{part:r.part,node:r.node,category:result.category,confidence:result.confidence,zSide:result.zSide,area:result.area,center,group:CATEGORY_GROUP[result.category]||10};
  });
  // Resolve back-vs-door among thin panels along the depth axis: whichever
  // depth extreme has more TOTAL thin-panel area is treated as the back
  // (normally exactly one back panel); the other extreme's thin panels
  // are doors/fronts.
  const zCandidates=raw.filter(r=>r.category==='backOrDoor');
  if(zCandidates.length){
    let nearArea=0,farArea=0;
    zCandidates.forEach(r=>{if(r.zSide==='near')nearArea+=r.area;else farArea+=r.area});
    const backSide=nearArea>=farArea?'near':'far';
    zCandidates.forEach(r=>{r.category=r.zSide===backSide?'back':'door';r.group=CATEGORY_GROUP[r.category]});
  }
  // assemblyOrder override: if every mapped board declares a distinct
  // numeric manifest.parts[].assemblyOrder, that explicit order wins
  // outright over auto-classification (still deterministic, still a
  // total order).
  const explicitOrders=raw.map(r=>r.part.assemblyOrder);
  const hasExplicitOrder=raw.length>0&&explicitOrders.every(v=>typeof v==='number'&&isFinite(v))&&new Set(explicitOrders).size===explicitOrders.length;
  const depthAxis=frame.depth;
  if(hasExplicitOrder){
    raw.sort((a,b)=>a.part.assemblyOrder-b.part.assemblyOrder);
  }else{
    raw.sort((a,b)=>{
      if(a.group!==b.group)return a.group-b.group;
      const au=a.center.dot(frame.up),bu=b.center.dot(frame.up);
      if(Math.abs(au-bu)>1e-5)return au-bu; // bottom-to-top
      const aw=a.center.dot(frame.width),bw=b.center.dot(frame.width);
      if(Math.abs(aw-bw)>1e-5)return aw-bw; // left-to-right
      const ad=a.center.dot(depthAxis),bd=b.center.dot(depthAxis);
      if(Math.abs(ad-bd)>1e-5)return ad-bd; // back-to-front
      return a.part.id<b.part.id?-1:a.part.id>b.part.id?1:0; // Label ID tie-break
    });
  }
  raw.forEach((r,i)=>{
    const homePos=r.node.position.clone(),homeQuat=r.node.quaternion.clone();
    const startPos=computeStartPosition(r.node,r.category,homePos,cabinetBox,frame);
    animSteps.push({part:r.part,node:r.node,category:r.category,confidence:r.confidence,
      home:{pos:homePos,quat:homeQuat},start:{pos:startPos,quat:homeQuat.clone()}});
    stepByLabel.set(r.part.id,i);
  });
  animDuplicateLabels=[...seen.entries()].filter(([,c])=>c>1).map(([id])=>id);
  if(animDuplicateLabels.length)console.warn('OpenEyes Animation: duplicate Label IDs found (using first match only):',animDuplicateLabels);
  animBuilt=true;
  return animDuplicateLabels;
}
// Smoother-step: gentle acceleration AND deceleration (the previous
// cubic ease-out started too aggressively and stopped suddenly — a
// board would visibly "jump" into motion the instant a tween began).
// EXPLODE uses a plain ease-out (still gentle at the start, brisker at
// the end) since it's a simultaneous outward motion, not a one-at-a-
// time assembly step.
function easeSnap(t){t=THREE.MathUtils.clamp(t,0,1);return t*t*t*(t*(t*6-15)+10)}
function easeOutExplode(t){t=THREE.MathUtils.clamp(t,0,1);return 1-Math.pow(1-t,3)}
// Cumulative assembly visibility: boards up to and including activeIndex
// are visible; every board strictly after it is completely hidden (not
// merely moved off to a waiting position) until its own step begins.
// This is the single shared rule used consistently by every Animation
// entry point below, so a future board never sits visible at its
// start/waiting position — it only appears the moment its own
// reveal-and-animate step begins. Box3.setFromObject(root) (used
// elsewhere for cabinet-size/collision calculations) is unaffected by
// .visible, so hiding future boards never changes any measurement.
function applyAssemblyVisibility(activeIndex){
  animSteps.forEach((step,index)=>{if(step&&step.node)step.node.visible=index<=activeIndex});
}
function startBoardTween(idx,fromPos,fromQuat,toPos,toQuat,durationMs){
  animTween={stepIndex:idx,fromPos:fromPos.clone(),fromQuat:fromQuat.clone(),toPos:toPos.clone(),toQuat:toQuat.clone(),startTime:performance.now(),duration:Math.max(80,durationMs),pausedElapsed:0,paused:false};
}
function startGroupTween(items,durationMs){animGroupTween={items,startTime:performance.now(),duration:Math.max(80,durationMs)}}
// Active-board highlight reuses the EXACT SAME overlay system as Board
// Size/Select Boards/Search/Scan (paintNode/restoreNode) — no second
// highlight engine. Completed/future boards keep their normal material
// (the simpler of the two options M explicitly allows), which also
// avoids extra per-board material work on every step for phone
// performance.
function setAnimActive(idx){
  if(animActiveNode){restoreNode(animActiveNode);animActiveNode=null}
  animCurrentStep=idx;
  if(idx>=0&&animSteps[idx]){paintNode(animSteps[idx].node,SELECT_COLOR,SELECT_OPACITY);animActiveNode=animSteps[idx].node}
}
function updateAnimHeader(idx){
  const stepEl=document.getElementById('animStepText');
  if(stepEl)stepEl.textContent=(idx==null||idx<0||!animSteps.length)?`Step 0 / ${animSteps.length}`:`Step ${idx+1} / ${animSteps.length}`;
  const el=document.getElementById('boardInfo');
  if(idx==null||idx<0||!animSteps.length){el.classList.add('hidden');el.textContent='';applyViewInset();return}
  const step=animSteps[idx];
  if(!step){el.classList.add('hidden');el.textContent='';applyViewInset();return}
  const sizes=[step.part.size?.x,step.part.size?.y,step.part.size?.z].map(Number).sort((a,b)=>b-a);
  el.textContent=`Step ${idx+1} / ${animSteps.length} — L ${mmText(sizes[0])} | W ${mmText(sizes[1])} | D ${mmText(sizes[2])} | Label ${step.part.id}`;
  el.classList.remove('hidden');applyViewInset();
}
function cancelAnimStepTimer(){if(animStepTimer){clearTimeout(animStepTimer);animStepTimer=null}}
const STEP_PAUSE_MS=160;
function onBoardTweenComplete(){
  const idx=animTween.stepIndex;animTween=null;
  setAnimActive(idx);
  updateAnimHeader(idx);
  if(animState==='playing'){
    if(idx+1<animSteps.length){
      // A short pause after each board reaches home (per section 9: hold
      // the completed board's green highlight briefly before the next
      // one starts, instead of the next board beginning the INSTANT the
      // previous tween finishes). Cancellable by every other control so
      // it can never fire a step after PAUSE/mode-exit/etc.
      cancelAnimStepTimer();
      animStepTimer=setTimeout(()=>{
        animStepTimer=null;
        if(animState==='playing')playStepAnimated(idx+1);
      },STEP_PAUSE_MS/animSpeed);
    }else{
      animState='complete';toast.textContent=`Animation Complete\n${animSteps.length}/${animSteps.length} boards`;
    }
  }
}
// Duration scales with how far the board actually has to travel (short
// hops are faster, long ones a little slower) instead of a flat 900ms
// for every board regardless of distance.
function animationDuration(fromPos,toPos,cabinetBox){
  const distance=fromPos.distanceTo(toPos);
  const reference=(cabinetBox.getSize(new THREE.Vector3()).length()||1)*.22;
  return THREE.MathUtils.clamp(850*(distance/Math.max(reference,1e-6)),600,1300)/animSpeed;
}
function playStepAnimated(idx){
  if(idx<0||idx>=animSteps.length||!animSteps[idx]||!animSteps[idx].node)return;
  const step=animSteps[idx],cabinetBox=new THREE.Box3().setFromObject(root);
  step.node.position.copy(step.start.pos);step.node.quaternion.copy(step.start.quat);
  const assembledBoxes=animSteps.slice(0,idx).map(s=>new THREE.Box3().setFromObject(s.node));
  const startPos=resolveStartPosition(step,cabinetBox,assembledBoxes,animFrame||{up:new THREE.Vector3(0,1,0),depth:new THREE.Vector3(0,0,1),width:new THREE.Vector3(1,0,0)});
  step.node.position.copy(startPos);
  applyAssemblyVisibility(idx);
  setAnimActive(idx);
  updateAnimHeader(idx);
  // During continuous PLAY, the CABINET's own position/framing must stay
  // put — only the individual boards travel to assemble it. Re-focusing
  // the camera on every single board (the previous behavior) shifted the
  // camera's look-at target to wherever each board happened to be,
  // which visually reads as "the whole cabinet is jumping around" even
  // though its actual 3D position never moved. Fixed by NOT touching the
  // camera at all during the automatic step-to-step sequence; camera
  // focus is still used for deliberate one-shot navigation (NEXT/
  // PREVIOUS/jump-to-step from QR or Search), where a single decisive
  // move is expected and useful rather than disruptive.
  startBoardTween(idx,startPos,step.start.quat,step.home.pos,step.home.quat,animationDuration(startPos,step.home.pos,cabinetBox));
}
function pauseAnimTween(){if(animTween&&!animTween.paused){animTween.pausedElapsed=performance.now()-animTween.startTime;animTween.paused=true}}
function resumeAnimTween(){if(animTween&&animTween.paused){animTween.startTime=performance.now()-animTween.pausedElapsed;animTween.paused=false}}
function startAnimation(){
  buildAssemblySteps(false);
  cancelAnimStepTimer();
  if(animTween){const s=animSteps[animTween.stepIndex];if(s){s.node.position.copy(animTween.fromPos);s.node.quaternion.copy(animTween.fromQuat)}animTween=null}
  animGroupTween=null;
  animSteps.forEach(s=>{s.node.position.copy(s.start.pos);s.node.quaternion.copy(s.start.quat)});
  applyAssemblyVisibility(-1);
  setAnimActive(-1);animState='ready';updateAnimHeader(-1);
  toast.textContent=animSteps.length?'Ready to assemble':'⚠ No 3D boards mapped. Upload again with the updated exporter.';
}
function playAnimation(){
  buildAssemblySteps(false);
  if(!animSteps.length){toast.textContent='⚠ No 3D boards mapped. Upload again with the updated exporter.';return}
  if(animState==='paused'&&animTween){animState='playing';resumeAnimTween();return}
  if(animCurrentStep>=animSteps.length-1){startAnimation()}
  animState='playing';
  playStepAnimated(animCurrentStep+1);
}
function pauseAnimation(){if(animState!=='playing')return;animState='paused';cancelAnimStepTimer();pauseAnimTween();toast.textContent='⏸ Paused'}
function nextStep(){
  buildAssemblySteps(false);
  if(!animSteps.length)return;
  cancelAnimStepTimer();
  // Defensive: if a stale tween references an index that no longer
  // exists in the CURRENT animSteps array (e.g. DISTANCE was changed,
  // which force-rebuilds animSteps into a new array mid-session), clear
  // it instead of crashing. This is exactly the class of bug behind a
  // real "Cannot read properties of undefined (reading 'node')" crash
  // reported from an actual running build.
  if(animTween){
    const s=animSteps[animTween.stepIndex];
    if(s&&s.node){s.node.position.copy(animTween.toPos);s.node.quaternion.copy(animTween.toQuat)}
    animTween=null;
  }
  if(animCurrentStep>=animSteps.length-1){toast.textContent='Animation Complete';return}
  const idx=animCurrentStep+1;
  animSteps.forEach((s,i)=>{if(!s||!s.node)return;if(i<=idx){s.node.position.copy(s.home.pos);s.node.quaternion.copy(s.home.quat)}else{s.node.position.copy(s.start.pos);s.node.quaternion.copy(s.start.quat)}});
  applyAssemblyVisibility(idx);
  setAnimActive(idx);animState='paused';updateAnimHeader(idx);
  if(animAutoFocus&&animSteps[idx]&&animSteps[idx].node)fitWithContext(animSteps[idx].node);
}
function previousStep(){
  buildAssemblySteps(false);
  if(!animSteps.length)return;
  cancelAnimStepTimer();
  if(animTween){
    const s=animSteps[animTween.stepIndex];
    if(s&&s.node){s.node.position.copy(animTween.fromPos);s.node.quaternion.copy(animTween.fromQuat)}
    animTween=null;
  }
  const idx=Math.max(animCurrentStep-1,-1);
  animSteps.forEach((s,i)=>{if(!s||!s.node)return;if(i<=idx){s.node.position.copy(s.home.pos);s.node.quaternion.copy(s.home.quat)}else{s.node.position.copy(s.start.pos);s.node.quaternion.copy(s.start.quat)}});
  applyAssemblyVisibility(idx);
  setAnimActive(idx);animState=idx<0?'ready':'paused';updateAnimHeader(idx);
  if(idx>=0&&animAutoFocus&&animSteps[idx]&&animSteps[idx].node)fitWithContext(animSteps[idx].node);
}
function replayAnimation(){cancelAnimStepTimer();startAnimation();playAnimation()}
function explodeAnimation(){
  buildAssemblySteps(false);
  if(!animSteps.length){toast.textContent='⚠ No 3D boards mapped. Upload again with the updated exporter.';return}
  cancelAnimStepTimer();
  if(animTween){const s=animSteps[animTween.stepIndex];if(s&&s.node){s.node.position.copy(animTween.toPos);s.node.quaternion.copy(animTween.toQuat)}animTween=null}
  // EXPLODE shows every board (moving them all outward simultaneously) --
  // it must never inherit hidden state left over from a cumulative PLAY
  // run that stopped partway through.
  animSteps.forEach(s=>{if(s.node)s.node.visible=true});
  setAnimActive(-1);
  const items=animSteps.map(s=>({node:s.node,fromPos:s.node.position.clone(),fromQuat:s.node.quaternion.clone(),toPos:s.start.pos,toQuat:s.start.quat}));
  startGroupTween(items,700/animSpeed);
  animCurrentStep=-1;animState='ready';updateAnimHeader(-1);
  toast.textContent=`💥 Exploding ${animSteps.length} boards`;
}
// QR Scan / Search / manual-3D-tap all resolve to this SAME function
// (section W/X/Y): jump straight to a board's assembly step — steps
// before it assembled, that step itself assembled + green, steps after
// it left at their waiting/start position.
function jumpToAnimationStep(idx){
  if(!animSteps.length)return;
  if(idx<0||idx>=animSteps.length||!animSteps[idx]||!animSteps[idx].node)return;
  cancelAnimStepTimer();
  if(animTween){animTween=null}
  animGroupTween=null;
  animSteps.forEach((s,i)=>{if(!s||!s.node)return;if(i<=idx){s.node.position.copy(s.home.pos);s.node.quaternion.copy(s.home.quat)}else{s.node.position.copy(s.start.pos);s.node.quaternion.copy(s.start.quat)}});
  applyAssemblyVisibility(idx);
  setAnimActive(idx);animState='paused';updateAnimHeader(idx);
  if(animAutoFocus)fitWithContext(animSteps[idx].node);
}
// Leaving Animation mode (closing the panel) must never leave the model in
// a half-assembled/inconsistent state (AE): always restore the fully
// assembled ("source of truth") state, exactly as it was before Animation
// touched anything -- board FINAL transforms (home) are the ones actually
// saved/exported, never altered by any of the code above.
function exitAnimation(){
  cancelAnimStepTimer();
  if(animTween)animTween=null;
  animGroupTween=null;
  animSteps.forEach(s=>{s.node.position.copy(s.home.pos);s.node.quaternion.copy(s.home.quat);s.node.visible=true});
  setAnimActive(-1);
  animCurrentStep=animSteps.length?animSteps.length-1:-1;
  animState=animSteps.length?'complete':'idle';
  updateAnimHeader(-1);
  hide('animationPanel');
}

document.getElementById('animation').onclick=()=>toggleMainSection('animation');
function setActiveAnimButton(id){document.querySelectorAll('.animRow button').forEach(b=>b.classList.toggle('active',b.id===id))}
document.getElementById('play').onclick=()=>{setActiveAnimButton('play');playAnimation()};
document.getElementById('pause').onclick=()=>{setActiveAnimButton('pause');pauseAnimation()};
document.getElementById('replay').onclick=()=>{setActiveAnimButton('replay');replayAnimation()};
document.getElementById('explode').onclick=()=>{setActiveAnimButton('explode');explodeAnimation()};
document.getElementById('prev').onclick=()=>{setActiveAnimButton('prev');previousStep()};
document.getElementById('next').onclick=()=>{setActiveAnimButton('next');nextStep()};
document.getElementById('speed').onchange=e=>{animSpeed=Number(e.target.value)||1};
// DISTANCE: configurable travel distance for boards' waiting/start
// position (Near/Normal/Far), per request. Changing it only affects
// WHERE each board starts from -- never its final position -- and takes
// effect by rebuilding the (cached) per-step start positions and
// resetting to the ready/waiting state so the new distance is
// immediately visible.
document.getElementById('animDistance').onchange=e=>{
  animDistanceMul=Number(e.target.value)||1;
  buildAssemblySteps(true);
  startAnimation();
};
// Single source-of-truth Label ID -> board resolver, used by typed Search
// (exact match), QR/barcode Scan, and search-result taps alike — so scan
// and manual selection always behave identically. EXACT match only
// against manifest part ids (never substring/name/array-position/nearest-
// board guessing). Mode-aware: while SELECT BOARDS (chain) mode is
// active this adds the board to the dimension chain (same as a manual
// tap on the model); otherwise it performs a normal single-board
// select+focus+highlight, exactly like tapping the board in 3D.
function resolveAndSelectBoard(labelId,opts){
  opts=opts||{};
  const id=String(labelId||'').trim();
  if(!id)return false;
  // The exact root cause of a real, confirmed bug (found via a genuine
  // end-to-end test: a real QR image through a real fake-camera device
  // through the actual jsQR/tick() pipeline): if a board is scanned/typed
  // BEFORE the model+manifest have finished loading, manifest.parts is
  // still empty and the lookup silently "fails" even though the board is
  // real — showing a misleading "Board not found" when the true problem
  // is just that data isn't ready yet. Now reported accurately instead.
  if(!modelReady){toast.textContent='Model is still loading — please wait a moment and try again';return false}
  const part=manifest.parts.find(p=>p.id===id);
  if(!part){toast.textContent='Board not found in this project';return false}
  if(mode==='chain'){
    chooseChainBoard(part);
  }else{
    // Search / QR scan is a LOCATION aid, not an assembly-step command.
    // Always restore the cabinet to its final assembled state first, then
    // keep every board visible and only highlight + context-focus the match.
    // This lets an installer see exactly WHERE the scanned board belongs.
    if(animSteps.length)exitAnimation();
    ordered.forEach(p=>(partMap.get(p.id)||[]).forEach(n=>n.visible=true));
    hiddenStack=[];
    selectPart(part.id);
    if(!opts.silent)toast.textContent='Board found ✓';
  }
  return true
}
// THE single entry point for "make this Board ID the focused board", used
// by BOTH the manual Search button and the remote phone-scan receiver, so
// there is exactly one selection path and no duplicated search logic. It
// wraps resolveAndSelectBoard() (which already does find -> select ->
// highlight -> focus camera) with the two extra steps the scan workflow
// needs: normalize the raw text, and un-hide the board first if a worker
// had previously hidden it — otherwise the camera would fly to a board
// that is invisible on screen, which reads as "nothing happened".
function unhideBoardIfHidden(id){
  if(!hiddenStack.length)return false;
  let restored=false;
  hiddenStack=hiddenStack.filter(h=>{
    if(h.part&&h.part.id===id){h.node.visible=true;restored=true;return false}
    return true
  });
  return restored;
}
function focusBoardById(boardId,opts){
  opts=opts||{};
  // Scanners routinely pick up trailing newlines/spaces; strip them before
  // anything else so a physically fine label never looks "not found".
  const id=String(boardId==null?'':boardId).replace(/[\u200b\r\n\t]/g,'').trim();
  if(!id){toast.textContent='Invalid Board QR';return false}
  if(!modelReady){toast.textContent=`Model is still loading — ${id} will need another scan`;return false}
  if(!manifest.parts.some(p=>p.id===id)){
    // Never throw here: the listener must stay alive for the next scan.
    toast.textContent=`Board not found in current 3D project: ${id}`;
    console.warn('[BOARD] not found:',id);
    return false;
  }
  const wasHidden=unhideBoardIfHidden(id);
  const ok=resolveAndSelectBoard(id,{silent:true});
  if(ok)toast.textContent=`Found: ${id}${wasHidden?' (unhidden)':''}`;
  return ok;
}
// Exposed for manual troubleshooting from the browser console.
window.focusBoardById=focusBoardById;
document.getElementById('search').onclick=()=>toggleMainSection('search');
document.getElementById('doorBtn').onclick=()=>toggleMainSection('door');
document.getElementById('backBtn').onclick=()=>{
  // BACK is context-aware: it first steps back inside the tool the user is
  // currently standing in. In DIMENSION this means undo the most recent
  // 3 POINT board / MULTI board / POINT tap. Only when there is nothing
  // left to undo does BACK leave the Dimension panel. This makes 3 POINT
  // work naturally: tap any board -> its dimension follows immediately;
  // press BACK -> that board/dimension is removed.
  if(activeMainSection==='dimension'){
    const didUndo=backDimension();
    if(didUndo)return;
    closeActiveSection();
    return;
  }
  // HIDE keeps its existing one-board-at-a-time undo behavior.
  if(hiddenStack.length){
    const h=hiddenStack.pop();
    h.node.visible=true;
    toast.textContent=`👁 ${h.part.id} unhidden`;
    return;
  }
  closeActiveSection();
};
function find(){
  const q=document.getElementById('query').value.trim(),qLower=q.toLowerCase();
  const items=manifest.parts.filter(p=>!qLower||[p.id,p.name,p.abfPartNumber].some(x=>String(x||'').toLowerCase().includes(qLower))).slice(0,50);
  document.getElementById('results').innerHTML=items.map(p=>`<div class="result" data-part="${esc(p.id)}"><b>${esc(p.name)}</b><br><small>${esc(p.id)} • ${num(p.size?.x)}×${num(p.size?.y)}×${num(p.size?.z)} mm</small></div>`).join('')||'<p>No board found.</p>';
  document.querySelectorAll('[data-part]').forEach(x=>x.onclick=()=>{hide('searchPanel');focusBoardById(x.dataset.part)});
  // Typed or pasted EXACT Label ID selects immediately -- no extra tap.
  // Same focusBoardById() the phone-scan receiver calls: ONE code path.
  if(q&&manifest.parts.some(p=>p.id===q))focusBoardById(q)
}
document.getElementById('find').onclick=find;document.getElementById('query').oninput=find;
// Print All / Print Selected -- Local flow only (printUrl is '' for Cloud
// /live, so these stay hidden and unwired there).
if(printUrl){
  document.getElementById('printAll').classList.remove('hidden');
  document.getElementById('printSelected').classList.remove('hidden');
  document.getElementById('printAll').onclick=()=>window.open(printUrl,'_blank');
  document.getElementById('printSelected').onclick=()=>{
    if(!selectedId){toast.textContent='Select a board first, then Print Selected.';return}
    window.open(printUrl+'?part='+encodeURIComponent(selectedId),'_blank')
  };
}
document.getElementById('isolate').onclick=()=>{const nodes=partMap.get(selectedId)||[];if(!nodes.length){toast.textContent='⚠ This Label ID is not mapped to a 3D node.';return}ordered.forEach(p=>partMap.get(p.id).forEach(n=>n.visible=p.id===selectedId));toast.textContent='👁 Isolated board'};document.getElementById('showAll').onclick=()=>{ordered.forEach(p=>partMap.get(p.id).forEach(n=>n.visible=true));fit();hide('infoPanel')};document.getElementById('assemblyStep').onclick=()=>{buildAssemblySteps(false);const i=stepByLabel.get(selectedId);if(i!==undefined){show('animationPanel');jumpToAnimationStep(i)}else toast.textContent='⚠ This board has no mapped assembly step'};
// --- Dimension labels: TEXT ONLY, no background rectangle. A dark stroke
// behind the yellow fill keeps it readable on both light and dark surfaces
// without ever covering the model with a filled badge. ---------------------
function labelSprite(text){
  const c=document.createElement('canvas');c.width=256;c.height=64;
  const x=c.getContext('2d');x.clearRect(0,0,256,64);
  x.font='bold 30px Arial';x.textAlign='center';x.textBaseline='middle';
  x.lineWidth=6;x.strokeStyle='rgba(0,0,0,.85)';x.strokeText(text,128,32);
  x.fillStyle='#ffe45c';x.fillText(text,128,32);
  const t=new THREE.CanvasTexture(c);t.needsUpdate=true;
  const s=new THREE.Sprite(new THREE.SpriteMaterial({map:t,depthTest:false,transparent:true}));
  s.scale.set(.32,.08,1);s.renderOrder=12;return s
}
// --- Unit calibration --------------------------------------------------------
// three.js's GLTFLoader (glTF spec) and ColladaLoader (via <unit meter=...>)
// both normalize a loaded scene to meters, so 1 scene unit = 1 m = 1000 mm is
// the physically-correct default — not an arbitrary constant. The previous
// bug was NOT the constant; it was that nodesFor() could loosely substring-
// match the wrong (often much larger) node for a small board, so the
// manifest-based cross-check computed a garbage ratio (e.g. ~9-18) and that
// garbage got adopted outright. The fix: nodesFor() now requires an exact
// name match first (see above), and calibration additionally REJECTS any
// per-axis ratio far outside a sane neighbourhood of the 1000 baseline, and
// only trusts the manifest-derived median when several parts agree with low
// spread — a single bad match can no longer corrupt every measurement.
function readColladaUnit(url){
  if(!url.toLowerCase().includes('.dae'))return Promise.resolve(null);
  return fetch(url).then(r=>r.text()).then(text=>{
    const m=text.match(/<unit[^>]*meter\s*=\s*"([\d.eE+-]+)"/i);
    if(!m)return null;
    const meterPerUnit=parseFloat(m[1]);
    if(!isFinite(meterPerUnit)||meterPerUnit<=0)return null;
    return meterPerUnit*1000;
  }).catch(()=>null)
}
function calibrateUnits(){
  mmPerUnit=1000;unitsConfirmed=false;
  // A whole-cabinet fallback "board" IS the overall selection — using its
  // size to calibrate would be calibrating against the wrong (huge) object,
  // exactly what item 2 of the fix request forbids.
  if(manifest.fallbackWholeCabinet)return;
  const ratios=[];
  (manifest.parts||[]).forEach(p=>{
    const nodes=nodesFor(p.id);if(!nodes.length)return;
    const world=new THREE.Box3();nodes.forEach(n=>world.expandByObject(n));
    const actual=world.getSize(new THREE.Vector3()).toArray().map(Math.abs).sort((a,b)=>a-b);
    const declared=[p.size?.x,p.size?.y,p.size?.z].map(Number).filter(x=>x>0).sort((a,b)=>a-b);
    for(let i=0;i<Math.min(actual.length,declared.length);i++){
      if(actual[i]<=1e-6)continue; // zero/degenerate axis -> reject
      const ratio=declared[i]/actual[i];
      if(ratio<100||ratio>10000)continue; // extreme outlier vs. the 1000 baseline -> reject
      ratios.push(ratio)
    }
  });
  if(ratios.length){
    ratios.sort((a,b)=>a-b);
    const median=ratios[Math.floor(ratios.length/2)];
    const spread=ratios.length>1?ratios[ratios.length-1]/ratios[0]:1;
    if(spread<=3){mmPerUnit=median;unitsConfirmed=true}
  }
  if(declaredMmPerUnit&&Math.abs(declaredMmPerUnit-mmPerUnit)/mmPerUnit>.5){
    console.warn(`OpenEyes Local Viewer: COLLADA <unit meter> implies ${declaredMmPerUnit.toFixed(1)} mm/unit but the calibrated value in use is ${mmPerUnit.toFixed(1)} mm/unit — verify on a real device if measurements look off.`)
  }
  if(!unitsConfirmed){
    toast.textContent='⚠ Unit calibration not confirmed — measurements may be approximate'
  }
}
// Compact board-info line shown in the project header (top), replacing the
// old L/W/D/Label text that used to sit inside the large Dimension panel.
// Only visible while a board is selected in BOARD SIZE mode.
function updateBoardInfoHeader(part){
  const el=document.getElementById('boardInfo');
  if(!part){el.classList.add('hidden');el.textContent='';applyViewInset();return}
  if(manifest.fallbackWholeCabinet){
    el.textContent='Whole cabinet fallback — individual board metadata unavailable';
  }else{
    const sizes=[part.size?.x,part.size?.y,part.size?.z].map(Number).sort((a,b)=>b-a);
    el.textContent=`L ${mmText(sizes[0])} | W ${mmText(sizes[1])} | D ${mmText(sizes[2])} | Label ${part.id||'Not assigned'}`;
  }
  el.classList.remove('hidden');applyViewInset()
}
function updateChainHeader(){
  const el=document.getElementById('boardInfo');
  if(!chainParts.length){el.classList.add('hidden');el.textContent='';applyViewInset();return}
  const last=chainParts[chainParts.length-1];
  let detail;
  if(manifest.fallbackWholeCabinet){
    detail='Whole cabinet fallback — individual board metadata unavailable';
  }else{
    const sizes=[last.size?.x,last.size?.y,last.size?.z].map(Number).sort((a,b)=>b-a);
    detail=`L ${mmText(sizes[0])} | W ${mmText(sizes[1])} | D ${mmText(sizes[2])} | Label ${last.id||'Not assigned'}`;
  }
  el.textContent=`Selected: ${chainParts.length} board${chainParts.length===1?'':'s'} — ${detail}`;
  el.classList.remove('hidden');applyViewInset()
}
function clearChainSelection(){
  // Clears the in-progress SELECT BOARDS scaffolding (order-number labels
  // + green highlight + the chainParts list) but leaves any already-
  // generated chainResultObjects (the finished GAP/THICKNESS chain) alone
  // — same "finished measurement stays visible after closing the panel"
  // precedent as POINT TO POINT's dimensionObjects.
  chainObjects.forEach(o=>scene.remove(o));chainObjects=[];
  chainParts.forEach(p=>(partMap.get(p.id)||[]).forEach(restoreNode));
  chainParts=[]
}
// CLEAR is the ONLY thing that removes completed dimension chains. DONE,
// switching placement side, selecting a new board sequence, or closing
// the panel must NEVER call this — see clearMeasure()/setDimensionMode()/
// exitDimension() below, none of which call it anymore.
function clearChainResult(){
  completedDimensionGroups.forEach(g=>g.objects.forEach(o=>scene.remove(o)));
  completedDimensionGroups=[];
  chainResultObjects.forEach(o=>scene.remove(o));chainResultObjects=[]
}
function clearMeasure(){
  dimensionObjects.forEach(o=>scene.remove(o));dimensionObjects=[];measurePoints=[];measureTotalMm=0;hideSnapDot();
  if(subMode==='board'){clearThreePointSelection(false);updateBoardInfoHeader(null)}
  if(subMode==='chain'){clearChainSelection();updateBoardInfoHeader(null)}
  document.getElementById('dimStatus').textContent=subMode==='board'?'Select a board':subMode==='chain'?'Tap boards in order: 1, 2, 3 …':'Points: 0 | Total = 0 mm'
}
function setDimensionMode(next){
  // Clear whichever mode is CURRENTLY active (using the still-old subMode)
  // before switching, so nothing from BOARD SIZE / POINT TO POINT /
  // SELECT BOARDS is ever left highlighted/orphaned when changing modes.
  clearMeasure();
  // REAL bug found and fixed: MULTI SELECT's chain now auto-draws live as
  // boards are picked (no DONE needed to SEE it) -- but clearMeasure()
  // above only clears the in-progress SELECTION scaffolding (chainParts,
  // order-number labels), not the already-drawn chainResultObjects
  // geometry itself, which was intentionally left alone so a DONE-
  // committed chain stays visible after leaving the panel. Confirmed via
  // direct testing: switching away from an UNCOMMITTED live preview (2+
  // boards picked, DONE never pressed) left its dimension line/label
  // geometry rendering in the scene indefinitely, completely untracked
  // (completedDimensionGroups stayed at 0 -- it was never actually kept,
  // just orphaned). Clearing ONLY chainResultObjects here (never
  // clearChainResult(), which would also wipe genuinely DONE-committed
  // groups from completedDimensionGroups -- a separate array that must
  // persist across mode switches).
  if(subMode==='chain'){chainResultObjects.forEach(o=>scene.remove(o));chainResultObjects=[]}
  subMode=next;mode=next;setHover(null);hideSnapDot();
  clearMeasure(); // sets the correct default status text for the new mode
  document.getElementById('boardSize').classList.toggle('active',next==='board');
  document.getElementById('pointToPoint').classList.toggle('active',next==='points');
  document.getElementById('selectBoards').classList.toggle('active',next==='chain');
  // Explicit, mode-based visibility (not just relying on the initial HTML
  // 'hidden' class): multiPlacementRow only for MULTI SELECT (chain),
  // hidden for 3 POINT and POINT. This directly fixes the reported bug
  // where the old MULTI-SELECT-only controls (TICK IN/TICK OUT/L/R/TOP/B)
  // could remain visible while a different mode was active.
  document.getElementById('multiPlacementRow').classList.toggle('hidden',next!=='chain');
  document.getElementById('threePointSettingsRow').classList.toggle('hidden',next!=='board');
  document.getElementById('threePointOffsetRow').classList.toggle('hidden',next!=='board');
  // 3 POINT already auto-applies the moment a board is selected (see
  // chooseBoard -> drawThreePointDimension) -- there's nothing left to
  // "finish", so DONE is redundant there and hidden entirely, per
  // explicit request. MULTI SELECT and POINT still need it: both
  // require picking several boards/points in sequence, and DONE is the
  // only signal that tells the app the person is finished picking.
  const doneBtn=document.getElementById('doneDimension');
  const actions=document.querySelector('.dimActions');
  const status=document.getElementById('dimStatus');
  const offsetRow=document.getElementById('threePointOffsetRow');
  const multiRow=document.getElementById('multiPlacementRow');
  const multiBack=document.getElementById('placeBack');
  doneBtn.classList.toggle('hidden',next==='board');
  // Compact layout requested by workshop users:
  // 3 POINT = OFFSET + TICK + status on one row.
  // MULTI SELECT = BACK + status + DONE as three equal cells on one row.
  if(next==='board'){
    offsetRow.appendChild(status);
    if(multiBack.parentElement!==multiRow) multiRow.appendChild(multiBack);
  }else{
    if(status.parentElement!==actions) actions.insertBefore(status,doneBtn);
    if(next==='chain') actions.insertBefore(multiBack,status);
    else if(multiBack.parentElement!==multiRow) multiRow.appendChild(multiBack);
  }
  actions.style.gridTemplateColumns=next==='chain'?'repeat(3,1fr)':(next==='board'?'1fr':'1fr 1fr');
  applyViewInset();
  controls.enabled=true
}
function exitDimension(){
  mode='idle';setHover(null);hideSnapDot();clearThreePointSelection(false);updateBoardInfoHeader(null);
  clearChainSelection();
  // Same real bug/fix as setDimensionMode() above, for the OTHER way to
  // leave Dimension mode (the sidebar's BACK button): an uncommitted
  // live-preview chain (DONE never pressed) must not be left rendering
  // in the scene, untracked, after exiting entirely. Only the
  // uncommitted chainResultObjects are cleared here -- genuinely DONE-
  // committed groups (completedDimensionGroups) are a separate array and
  // must persist.
  chainResultObjects.forEach(o=>scene.remove(o));chainResultObjects=[];
  // Keep finished/auto 3 POINT dimensions visible when leaving Dimension.
  document.getElementById('dimension').classList.remove('active');
  hide('dimensionPanel')
}
// BACK: undo one step without reloading the viewer or touching the
// underlying calculation. In BOARD_SIZE mode it just deselects the current
// board. In SELECT BOARDS mode it removes only the most recently selected
// board. In POINT_TO_POINT mode it drops the most recently added point and
// REPLAYS the remaining points through the existing, unmodified
// addMeasurePoint()/distance calculation — so segment/Total math is never
// duplicated or reimplemented, only re-run on one fewer point.
// backDimension() is no longer wired to a UI button (the in-panel BACK
// button was removed per explicit request to simplify the action row
// down to Status/Clear/Done) -- kept defined here, unused, rather than
// deleted, in case this "undo the most recent selection" capability is
// wanted again later. document.getElementById('backDimension') no
// longer exists, so binding an onclick to it was removed too (it would
// throw on load otherwise).
function backDimension(){
  if(subMode==='board'){
    if(!threePointParts.length){toast.textContent='Nothing to go back from.';return false}
    const removed=threePointParts.pop();
    const group=threePointGroups.pop();
    if(group)group.objects.forEach(o=>scene.remove(o));
    (partMap.get(removed.id)||[]).forEach(restoreNode);
    selectedPart=threePointParts.length?threePointParts[threePointParts.length-1]:null;
    if(selectedPart)(partMap.get(selectedPart.id)||[]).forEach(n=>paintNode(n,SELECT_COLOR,SELECT_OPACITY));
    updateBoardInfoHeader(selectedPart);
    document.getElementById('dimStatus').textContent=threePointParts.length?`3 POINT selected: ${threePointParts.length} board${threePointParts.length===1?'':'s'} — BACK removes last`:'Select a board';
    toast.textContent=`↶ Removed 3 POINT from ${removed.id}`;
    return true
  }
  if(subMode==='chain'){
    if(!chainParts.length){toast.textContent='Nothing to go back from.';return false}
    const removed=chainParts.pop();
    (partMap.get(removed.id)||[]).forEach(restoreNode);
    const label=chainObjects.pop();
    if(label)scene.remove(label);
    chainResultObjects.forEach(o=>scene.remove(o));chainResultObjects=[];
    if(chainParts.length>=2)generateDimensionChain();
    updateChainHeader();
    document.getElementById('dimStatus').textContent=chainParts.length?`Selected: ${chainParts.length} board${chainParts.length===1?'':'s'}`:'Tap boards in order: 1, 2, 3 …';
    toast.textContent=`↶ Removed ${removed.id}`;
    return true
  }
  if(!measurePoints.length){toast.textContent='Nothing to go back from.';return false}
  const remaining=measurePoints.slice(0,-1);
  clearMeasure();
  remaining.forEach(p=>addMeasurePoint(p));
  toast.textContent='↶ Last point removed';
  return true
}
// partAt() resolves a raycast hit to the nearest ENCLOSING mapped board by
// walking up from the hit mesh and checking the O(1) reverse index built in
// prepareParts() — it can never "fall through" to an unrelated part earlier
// in manifest order, and it stops at the first (innermost) match, so a large
// common parent is never selected instead of the real board.
function partAt(object){let o=object;while(o){const p=nodeToPart.get(o);if(p)return p;o=o.parent}return null}
const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
// THREE.Raycaster does NOT skip invisible objects by default -- that is
// entirely the caller's responsibility (confirmed: Object3D.raycast()
// implementations never check this.visible, and Raycaster.intersectObject
// never checks it either). This was a REAL bug matching a real report:
// after hiding a board, tapping a DIFFERENT board behind/near it (e.g. to
// measure it with 3 POINT) still hit the hidden board first, since its
// geometry was still fully raycastable despite being invisible. Fixed by
// filtering out any hit whose object OR any ancestor has visible===false,
// matching the same semantics actual rendering already uses.
function isEffectivelyVisible(obj){let o=obj;while(o){if(o.visible===false)return false;o=o.parent}return true}
function hitsAt(event){const rect=renderer.domElement.getBoundingClientRect();pointer.x=((event.clientX-rect.left)/rect.width)*2-1;pointer.y=-((event.clientY-rect.top)/rect.height)*2+1;raycaster.setFromCamera(pointer,camera);return raycaster.intersectObject(root,true).filter(h=>isEffectivelyVisible(h.object))}
// Corner snapping: candidates come ONLY from the board resolved by partAt()
// (never the whole cabinet), deduplicated, filtered to those not far behind
// the actual raycast hit (rejects back-facing/occluded vertices that would
// otherwise win on screen-space distance alone), and matched within a
// pointer-type-appropriate screen radius. Used for BOTH the live green hover
// preview and the committed tap, so preview and commit can never disagree.
function snapCorner(event,hit){
  const rect=renderer.domElement.getBoundingClientRect(),part=partAt(hit.object),nodes=part?(partMap.get(part.id)||nodesFor(part.id)):[hit.object];
  root.updateMatrixWorld(true);
  const raw=[];
  nodes.forEach(node=>node.traverse(o=>{if(!o.isMesh||!o.geometry?.attributes?.position)return;const a=o.geometry.attributes.position,step=Math.max(1,Math.ceil(a.count/20000));for(let i=0;i<a.count;i+=step)raw.push(new THREE.Vector3().fromBufferAttribute(a,i).applyMatrix4(o.matrixWorld))}));
  const box=new THREE.Box3();nodes.forEach(n=>box.expandByObject(n));
  for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])raw.push(new THREE.Vector3(x,y,z));
  const eps=Math.max(box.getSize(new THREE.Vector3()).length()*.001,1e-5),seen=[],candidates=[];
  raw.forEach(p=>{if(!seen.some(q=>q.distanceToSquared(p)<eps*eps)){seen.push(p);candidates.push(p)}});
  const camPos=camera.position,maxDist=hit.distance+(box.getSize(new THREE.Vector3()).length()||1),radius=event.pointerType==='touch'?28:15;
  let best=null,bestPx=radius;const projected=new THREE.Vector3();
  for(const p of candidates){
    if(camPos.distanceTo(p)>maxDist)continue; // reject candidates far behind the visible surface
    projected.copy(p).project(camera);
    if(projected.z<-1||projected.z>1)continue; // outside camera frustum depth
    const sx=(projected.x+1)*rect.width/2+rect.left,sy=(-projected.y+1)*rect.height/2+rect.top,d=Math.hypot(sx-event.clientX,sy-event.clientY);
    if(d<bestPx){bestPx=d;best=p}
  }
  return best
}
let snapDot=null;
function ensureSnapDot(){if(!snapDot){snapDot=new THREE.Mesh(new THREE.SphereGeometry(.013,12,8),new THREE.MeshBasicMaterial({color:HOVER_COLOR,depthTest:false}));snapDot.renderOrder=14;snapDot.visible=false;scene.add(snapDot)}return snapDot}
function showSnapDot(p){const d=ensureSnapDot();d.position.copy(p);d.visible=true}
function hideSnapDot(){if(snapDot)snapDot.visible=false}
function addMeasurePoint(p){hideSnapDot();const dot=new THREE.Mesh(new THREE.SphereGeometry(.012,12,8),new THREE.MeshBasicMaterial({color:0xffe45c,depthTest:false}));dot.position.copy(p);dot.renderOrder=13;scene.add(dot);dimensionObjects.push(dot);measurePoints.push(p.clone());if(measurePoints.length>1){const a=measurePoints.at(-2),b=measurePoints.at(-1),value=a.distanceTo(b)*mmPerUnit;measureTotalMm+=value;const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]),new THREE.LineBasicMaterial({color:0xffe45c,depthTest:false}));line.renderOrder=10;const mid=a.clone().add(b).multiplyScalar(.5);const segDir=b.clone().sub(a).normalize();const viewDir=camera.position.clone().sub(mid).normalize();const perp=new THREE.Vector3().crossVectors(segDir,viewDir);if(perp.lengthSq()>1e-8)perp.normalize().multiplyScalar(.03*(measurePoints.length%2?1:-1));const label=labelSprite(mmText(value));label.position.copy(mid).add(perp);scene.add(line,label);dimensionObjects.push(line,label)}document.getElementById('dimStatus').textContent=`Points: ${measurePoints.length} | Total = ${mmText(measureTotalMm)}`}
function clearBoardDimObjects(){
  boardDimObjects.forEach(o=>scene.remove(o));boardDimObjects=[];
  threePointGroups.forEach(g=>g.objects.forEach(o=>scene.remove(o)));
  threePointGroups=[];
}
function clearThreePointSelection(removeDimensions=true){
  threePointParts.forEach(p=>(partMap.get(p.id)||[]).forEach(restoreNode));
  threePointParts=[];
  if(removeDimensions)clearBoardDimObjects();
  clearSelectedBoard();
}
// SINGLE SELECT board-size dimension visual (new this round — the
// previous behavior only highlighted the board and showed L/W/D as text
// in the header; this draws real dimension lines in the 3D scene).
// STYLE 1: full dimension-line presentation (extension lines + dimension
// line + diagonal end ticks) for both Length and Width, offset to the
// board's own adjacent edges, with a centered thickness label.
// STYLE 2: a cleaner presentation — plain text labels positioned near
// each edge, no lines/ticks — same underlying L/W/H values, different
// presentation only, per the spec's explicit "measurement values must
// remain identical" requirement.
function drawThreePointDimension(part,targetObjects=null,clearFirst=true){
  // 3 POINT (replaces the previous SINGLE SELECT NUMBER/SIZE BOARD text
  // styles per explicit request): automatically places 3 yellow point
  // markers at one corner of the board's top face and its two adjacent
  // corners (matching the board's own W and D edges), with 2 yellow
  // dimension lines and labels -- reusing the EXACT visual style already
  // established by the manual POINT-TO-POINT mode (labelSprite, 0xffe45c
  // dots/lines), just triggered automatically for the whole board
  // instead of tapped corner-by-corner.
  if(clearFirst)clearBoardDimObjects();
  const out=targetObjects||boardDimObjects;
  const nodes=partMap.get(part.id)||[];
  if(!nodes.length){console.warn('[OE-DIM] drawThreePointDimension: no 3D node found for',part.id);return}
  const node=nodes[0];
  const box=new THREE.Box3().setFromObject(node);
  const size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
  console.log('[OE-DIM] Board:',part.id,'| box size:',[size.x,size.y,size.z],'| center:',[center.x,center.y,center.z]);
  const dims=[{v:size.x,dir:new THREE.Vector3(1,0,0)},{v:size.y,dir:new THREE.Vector3(0,1,0)},{v:size.z,dir:new THREE.Vector3(0,0,1)}].sort((a,b)=>b.v-a.v);
  const wDim=dims[0],dDim=dims[1],thickDim=dims[2];
  const faceNormal=thickDim.dir.clone();
  const diag=size.length()||1;
  const liftAbove=faceNormal.clone().multiplyScalar(Math.max(diag*.004,.0016));
  // Resolve the anchor corner from the placement settings. If both
  // members of a Left/Right, Front/Back, or Top/Bottom pair are ticked,
  // the "positive" one (Right/Back/Top) wins -- a simple, documented
  // tie-break.
  let wSign=-1,dSign=-1,tSign=1;
  if(threePointSides.left)wSign=-1;
  if(threePointSides.right)wSign=1;
  if(threePointSides.front)dSign=1;
  if(threePointSides.back)dSign=-1;
  if(threePointSides.bottom)tSign=-1;
  if(threePointSides.top)tSign=1;
  const offsetUnits=(threePointOffsetMm/mmPerUnit)*(threePointTickMode==='out'?1:-1);
  console.log('[OE-DIM] 3-point placement:',threePointSides,'| offset:',threePointOffsetMm,'mm',threePointTickMode,'| resolved signs w/d/t:',[wSign,dSign,tSign]);
  // The TRUE corner (and its two true neighbors) sit exactly on the
  // board's real edges, at the chosen W-side/D-side of the top (or
  // bottom, if Bottom is ticked) face -- matching the reference image's
  // layout exactly when nothing is ticked (defaults to the original
  // Left/Front/Top corner). The offset then translates ALL THREE points
  // together, as one rigid unit, by the same amount along both the W
  // and D directions -- this was a REAL bug found via direct
  // measurement: the previous version only offset the shared corner
  // itself while its two neighbors stayed pinned to the board's true
  // edges, so the overall marker never visually detached from the
  // board even with TICK OUT and a real offset (confirmed: the offset
  // corner's OWN position was mathematically exactly correct, e.g.
  // precisely 100mm beyond the true edge for TICK OUT -- but the marker
  // as a whole still looked "attached" because 2 of its 3 points never
  // moved). Now every line's LENGTH still equals the board's true W or D
  // measurement exactly (a pure rigid translation changes position, not
  // length), while TICK OUT genuinely moves the entire marker into open
  // space beside the board, and TICK IN moves it entirely inward.
  const trueCornerVec=wDim.dir.clone().multiplyScalar(wSign*wDim.v/2).add(dDim.dir.clone().multiplyScalar(dSign*dDim.v/2)).add(faceNormal.clone().multiplyScalar(tSign*thickDim.v/2));
  const trueCorner=center.clone().add(trueCornerVec).add(liftAbove);
  const trueCornerW=trueCorner.clone().add(wDim.dir.clone().multiplyScalar(-wSign*wDim.v));
  const trueCornerD=trueCorner.clone().add(dDim.dir.clone().multiplyScalar(-dSign*dDim.v));
  const offsetVec=wDim.dir.clone().multiplyScalar(wSign*offsetUnits).add(dDim.dir.clone().multiplyScalar(dSign*offsetUnits));
  const corner=trueCorner.clone().add(offsetVec);
  const cornerW=trueCornerW.clone().add(offsetVec);
  const cornerD=trueCornerD.clone().add(offsetVec);
  function dot(p){
    const d=new THREE.Mesh(new THREE.SphereGeometry(.012,12,8),new THREE.MeshBasicMaterial({color:0xffe45c,depthTest:false}));
    d.position.copy(p);d.renderOrder=13;scene.add(d);out.push(d);return d;
  }
  function lineWithLabel(a,b){
    const value=a.distanceTo(b)*mmPerUnit;
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]),new THREE.LineBasicMaterial({color:0xffe45c,depthTest:false}));
    line.renderOrder=10;
    const mid=a.clone().add(b).multiplyScalar(.5);
    const segDir=b.clone().sub(a).normalize();
    const viewDir=camera.position.clone().sub(mid).normalize();
    const perp=new THREE.Vector3().crossVectors(segDir,viewDir);
    if(perp.lengthSq()>1e-8)perp.normalize().multiplyScalar(.03);
    const label=labelSprite(mmText(value));
    label.position.copy(mid).add(perp);
    scene.add(line,label);out.push(line,label);
    console.log('[OE-DIM] 3-point segment:',mmText(value),'| from:',[a.x,a.y,a.z],'to:',[b.x,b.y,b.z]);
  }
  dot(corner);dot(cornerW);dot(cornerD);
  lineWithLabel(corner,cornerW);
  lineWithLabel(corner,cornerD);
}
function chooseBoard(part){
  // 3 POINT is cumulative: board 1 keeps its dimension when board 2 is
  // selected, board 1+2 keep theirs when board 3 is selected, etc.
  if(threePointParts.some(p=>p.id===part.id)){toast.textContent='3 POINT: board already selected';return}
  threePointParts.push(part);
  selectedPart=part;
  (partMap.get(part.id)||[]).forEach(n=>paintNode(n,SELECT_COLOR,SELECT_OPACITY));
  updateBoardInfoHeader(part);
  if(!manifest.fallbackWholeCabinet){
    const objects=[];
    drawThreePointDimension(part,objects,false);
    threePointGroups.push({part,objects});
  }
  document.getElementById('dimStatus').textContent=manifest.fallbackWholeCabinet?'Whole cabinet selected':`3 POINT selected: ${threePointParts.length} board${threePointParts.length===1?'':'s'} — BACK removes last`;
}
// --- SELECT BOARDS (Dimension Chain) ---------------------------------------
function chooseChainBoard(part){
  if(chainParts.some(p=>p.id===part.id)){toast.textContent='Board already selected';return}
  chainParts.push(part);
  const nodes=partMap.get(part.id)||[];
  nodes.forEach(n=>paintNode(n,SELECT_COLOR,SELECT_OPACITY));
  const box=new THREE.Box3();nodes.forEach(n=>box.expandByObject(n));
  const label=labelSprite(String(chainParts.length));
  label.position.copy(box.getCenter(new THREE.Vector3()));
  scene.add(label);chainObjects.push(label);
  updateChainHeader();
  // Per explicit request: the chain now runs AUTOMATICALLY the moment
  // there are enough boards to measure between (2+), updating live as
  // each additional board is added -- no need to wait for DONE to see
  // it. generateDimensionChain() already only clears its own CURRENT
  // working set on each call (never a previously completed group), so
  // calling it repeatedly here is exactly as safe as calling it once.
  // DONE is still meaningful here (unlike 3 POINT): it COMMITS this
  // live preview as its own completed group, so picking MORE boards
  // afterward starts a fresh group instead of extending this one.
  if(chainParts.length>=2){
    generateDimensionChain();
    document.getElementById('dimStatus').textContent=`Selected: ${chainParts.length} boards — chain updated live. Tap DONE to keep it, or add more boards.`;
  }else{
    document.getElementById('dimStatus').textContent=`Selected: ${chainParts.length} board${chainParts.length===1?'':'s'} — select at least one more.`;
  }
}
// Dominant direction of spread among the selected boards' world centers,
// found by power iteration on their 3x3 covariance matrix. This is used
// instead of a hardcoded world axis (e.g. Z) specifically so the chain
// still comes out correct if the cabinet/model is rotated in the scene.
// Clean, neutral CAD-style label for the Dimension Chain ONLY — separate
// from labelSprite() (which stays exactly as before for POINT TO POINT,
// unchanged per the request to leave that mode untouched). No heavy
// black/yellow outline, no bright color: light/white text with only a
// thin, subtle dark edge for legibility against both light and dark
// surfaces.
function chainLabelSprite(text,sizeMul){
  const c=document.createElement('canvas');
  const x=c.getContext('2d');
  x.font='bold 32px Arial';
  const metrics=x.measureText(text);
  const paddingX=20,paddingY=14;
  c.width=Math.ceil(metrics.width+paddingX*2);
  c.height=32+paddingY*2;
  // Re-set font: changing canvas.width/height resets the 2D context.
  x.font='bold 32px Arial';x.textAlign='center';x.textBaseline='middle';
  // No background card behind the text (explicit request: no dimension
  // text/number should have a background, in either SINGLE or MULTI
  // SELECT). A dark outline stroke keeps it readable against varied
  // board colors instead, matching the convention already used for
  // SINGLE SELECT's board-size labels.
  x.lineWidth=6;x.strokeStyle='rgba(0,0,0,.6)';x.strokeText(text,c.width/2,c.height/2);
  x.fillStyle='#e53935';x.fillText(text,c.width/2,c.height/2);
  const t=new THREE.CanvasTexture(c);t.needsUpdate=true;
  const s=new THREE.Sprite(new THREE.SpriteMaterial({map:t,transparent:true,depthTest:false,depthWrite:false}));
  s.renderOrder=999;
  // The sprite's own scale is derived from the CANVAS's real aspect
  // ratio (which now varies with text length, e.g. "210mm" vs "TOTAL
  // 665mm") so text is never stretched or squished — callers must NOT
  // override .scale afterward with a fixed width:height ratio; pass
  // sizeMul instead (e.g. TOTAL uses a slightly larger sizeMul to read
  // as more prominent, without touching the aspect ratio).
  const isPhoneW=(host.clientWidth||window.innerWidth)<480;
  const h=(isPhoneW?.045:.055)*(sizeMul||1);
  s.scale.set(h*(c.width/c.height),h,1);
  console.log('[OE-DIM-CHAIN] Label:',JSON.stringify(text),'| canvas:',[c.width,c.height],'| scale:',[s.scale.x,s.scale.y]);
  return s
}
function principalAxis(points){
  if(points.length<2)return new THREE.Vector3(0,1,0);
  const mean=new THREE.Vector3();points.forEach(p=>mean.add(p));mean.divideScalar(points.length);
  let cxx=0,cxy=0,cxz=0,cyy=0,cyz=0,czz=0;
  points.forEach(p=>{const dx=p.x-mean.x,dy=p.y-mean.y,dz=p.z-mean.z;cxx+=dx*dx;cxy+=dx*dy;cxz+=dx*dz;cyy+=dy*dy;cyz+=dy*dz;czz+=dz*dz});
  let v=new THREE.Vector3(1,1,1).normalize();
  for(let i=0;i<25;i++){
    const nv=new THREE.Vector3(cxx*v.x+cxy*v.y+cxz*v.z,cxy*v.x+cyy*v.y+cyz*v.z,cxz*v.x+cyz*v.y+czz*v.z);
    if(nv.lengthSq()<1e-12)break;
    v=nv.normalize()
  }
  // Snap to a clean world axis when the raw fit is already close to one.
  // REAL bug found via direct measurement: selecting boards that mostly
  // stack along a clean axis (e.g. 4 shelves, all vertical) PLUS one
  // board of a very different shape/orientation (e.g. a full-height side
  // panel) pulls this least-squares fit a few degrees off pure vertical
  // -- confirmed directly: axis=[0.0156,0.9999,0] instead of [0,1,0]
  // after adding a side panel to a shelf selection. That small tilt then
  // cascades: the sort order along the tilted axis can interleave the
  // outlier board BETWEEN shelves (producing a NEGATIVE gap, confirmed:
  // -228mm), and facePoint()'s edge-vertex selection flips to the wrong
  // side for some boards -- together producing exactly the triangular/
  // converging line pattern reported, instead of clean parallel
  // dimension lines. Snapping to the dominant world axis whenever the
  // fit is already within about 15 degrees of one (dot product > .97)
  // makes the whole chain robust to a single outlier board, matching
  // what the person's eye obviously reads as "these are stacked
  // vertically" even when one selected board doesn't perfectly agree.
  const worldAxes=[new THREE.Vector3(1,0,0),new THREE.Vector3(0,1,0),new THREE.Vector3(0,0,1)];
  for(const w of worldAxes){if(Math.abs(v.dot(w))>.97)return v.dot(w)>=0?w.clone():w.clone().negate()}
  return v
}
// Samples the REAL world-space vertices of a board's mesh geometry (via
// matrixWorld, same pattern snapCorner() already uses for corner
// sampling). Deliberately NOT Box3.expandByObject()/setFromObject(): that
// re-derives a WORLD-AXIS-ALIGNED box, which inflates for any board that
// is itself rotated (e.g. the whole cabinet is rotated) — a thin rotated
// panel's axis-aligned box can be much thicker than the panel actually
// is. Sampling true vertices and projecting them onto the chain's own
// principal axis avoids that "rotated bounding box" error entirely.
function worldVerticesOf(node){
  const pts=[];
  node.traverse(o=>{
    if(!o.isMesh||!o.geometry?.attributes?.position)return;
    const a=o.geometry.attributes.position,step=Math.max(1,Math.ceil(a.count/2000));
    for(let i=0;i<a.count;i+=step)pts.push(new THREE.Vector3().fromBufferAttribute(a,i).applyMatrix4(o.matrixWorld))
  });
  return pts
}
// Builds the GAP/THICKNESS/GAP/… chain from the selected boards' REAL
// world-space vertices projected onto the principal axis — never
// center-to-center, never a declared-size assumption, and never a
// world-axis-aligned box (which would over-report a rotated board's
// extent — see worldVerticesOf() above). Boards are re-sorted into
// physical order along the axis (NOT tap order) before building the
// chain, so tapping them out of physical order still produces a correct
// result.
//
//   GAP(i,i+1)      = far face of board i  ->  near face of board i+1
//   THICKNESS(board) = board's own extent along the axis
//   Thickness is included only for INTERIOR boards (not the first/last
//   selected), matching: [bottom face B1] -> GAP -> [top face B2] ->
//   THICKNESS -> [bottom face B2] -> GAP -> [top face B3] -> …
function generateDimensionChain(){
  if(chainParts.length<2)return false;
  console.log('[OE-DIM-CHAIN] Building chain:',chainParts.length,'boards |',chainParts.map(p=>p.id),'| style:',chainStyle,'| placement:',chainPlacement,'| side:',chainSide);
  // Reset only the CURRENT (about-to-be-built) working set — never the
  // already-completed dimension groups from earlier DONE presses. Those
  // are only ever removed by the CLEAR button (clearAllDimensions).
  chainResultObjects.forEach(o=>scene.remove(o));chainResultObjects=[];
  const boardVerts=chainParts.map(p=>{
    const nodes=partMap.get(p.id)||[];
    let verts=[];nodes.forEach(n=>{verts=verts.concat(worldVerticesOf(n))});
    if(!verts.length){ // defensive fallback: a board with unreadable geometry still gets SOME position
      const box=new THREE.Box3();nodes.forEach(n=>box.expandByObject(n));
      verts=[box.getCenter(new THREE.Vector3())]
    }
    return verts
  });
  const centers=boardVerts.map(verts=>{const c=new THREE.Vector3();verts.forEach(v=>c.add(v));return c.divideScalar(verts.length)});
  const axis=principalAxis(centers);
  const projected=chainParts.map((p,i)=>{
    let min=Infinity,max=-Infinity;
    boardVerts[i].forEach(v=>{const s=axis.dot(v);if(s<min)min=s;if(s>max)max=s});
    return {part:p,min,max,idx:i}
  });
  projected.sort((a,b)=>((a.min+a.max)/2)-((b.min+b.max)/2));
  // Detect a board that spans across MULTIPLE other selected boards along
  // the measurement axis (e.g. a full-height side panel selected
  // alongside individual shelves) -- this doesn't fit the "sequential
  // stack" pattern GAP/THICKNESS segments assume, and produces a
  // negative/overlapping gap no matter how correct the axis itself is
  // (confirmed directly: even with a perfectly vertical axis, a full-
  // height board's own midpoint still sorts it into the MIDDLE of a
  // shelf stack, since GAP/THICKNESS assume each board occupies its own
  // distinct slot along the axis). Rather than silently drawing a
  // confusing/crossed result, this is surfaced clearly so the person can
  // adjust their selection (e.g. measure the shelves as their own group,
  // and the side panel separately).
  function overlapsRange(a,b){return a.min<b.max&&b.min<a.max}
  const outliers=projected.filter(p=>projected.filter(q=>q!==p&&overlapsRange(p,q)).length>=2);
  if(outliers.length){
    const names=outliers.map(o=>o.part.id).join(', ');
    console.warn('[OE-DIM-CHAIN] Board(s) span across multiple other selected boards along the measurement axis (not a simple stack):',outliers.map(o=>o.part.id));
    toast.textContent=`⚠ ${names} span${outliers.length===1?'s':''} across other selected boards — select it/them separately from a stacked group (e.g. shelves) for a clean chain.`;
  }
  const segments=[];
  for(let i=0;i<projected.length-1;i++){
    const a=projected[i],b=projected[i+1];
    segments.push({type:'GAP',mm:(b.min-a.max)*mmPerUnit,from:a.max,to:b.min,fromIdx:a.idx,toIdx:b.idx});
    if(i+1<projected.length-1){
      const c=projected[i+1];
      segments.push({type:'THICKNESS',mm:(c.max-c.min)*mmPerUnit,from:c.min,to:c.max,fromIdx:c.idx,toIdx:c.idx})
    }
  }
  // --- Visual placement ONLY (never touches the segments/mm values above).
  // TICK IN: a single clear-opening dimension drawn INSIDE the span between
  // the first and last selected boundary boards (never through an outside
  // offset).
  // TICK OUT: the existing multi-segment GAP/THICKNESS/GAP chain, now
  // placed on the EXPLICIT side the user chose (Left/Right/Top/Bottom)
  // rather than an auto-detected one, at a single UNIFORM offset distance
  // (OUTSIDE_DIM_OFFSET_MM) beyond the cabinet's own outer boundary on
  // every side, so Left/Right/Top/Bottom all sit the same distance out and
  // form a balanced frame around the cabinet — never a door-width/2 or
  // A-B/4 calculation, and never anything derived from screen pixels.
  const lateralOrigin=new THREE.Vector3();centers.forEach(c=>lateralOrigin.add(c));lateralOrigin.divideScalar(centers.length);
  const worldUp=new THREE.Vector3(0,1,0);
  const isPhone=(host.clientWidth||window.innerWidth)<480;
  const lineMat=new THREE.LineBasicMaterial({color:0xd9d9d9,depthTest:false,transparent:true,opacity:.85});
  // Dimension heads are POINT markers (instead of diagonal tick strokes).
  // Bright yellow points are easier to read on both light and dark models,
  // and match the existing 3 POINT / POINT-TO-POINT visual language.
  function dimensionHeadPoint(p,targetArray=chainResultObjects){
    const r=isPhone?.010:.012;
    const d=new THREE.Mesh(new THREE.SphereGeometry(r,12,8),new THREE.MeshBasicMaterial({color:0xffe45c,depthTest:false}));
    d.position.copy(p);d.renderOrder=13;scene.add(d);targetArray.push(d);return d
  }
  function orthogonalTo(axisVec,dir){
    const p=dir.clone().sub(axisVec.clone().multiplyScalar(axisVec.dot(dir)));
    return p.lengthSq()>1e-8?p.normalize():null
  }
  function extentAlong(object,dir){
    const box=new THREE.Box3().setFromObject(object);
    const corners=[
      new THREE.Vector3(box.min.x,box.min.y,box.min.z),new THREE.Vector3(box.max.x,box.min.y,box.min.z),
      new THREE.Vector3(box.min.x,box.max.y,box.min.z),new THREE.Vector3(box.min.x,box.min.y,box.max.z),
      new THREE.Vector3(box.max.x,box.max.y,box.min.z),new THREE.Vector3(box.max.x,box.min.y,box.max.z),
      new THREE.Vector3(box.min.x,box.max.y,box.max.z),new THREE.Vector3(box.max.x,box.max.y,box.max.z),
    ];
    let min=Infinity,max=-Infinity;corners.forEach(c=>{const s=dir.dot(c);if(s<min)min=s;if(s>max)max=s});
    return {min,max}
  }

  if(chainStyle==='in'){
    // Per-compartment clear openings (MIDDLE FRONT / internal dimension
    // mode): every CONSECUTIVE pair of selected boundaries gets its own
    // separate clear-opening dimension, positioned at that opening's own
    // real location — never one single dimension spanning the whole
    // selection. (Root cause of the old "one 665mm dimension" bug: it
    // only ever computed first-boundary-to-last-boundary, exactly the
    // "min selected -> max selected -> one dimension" pattern. Fixed by
    // iterating every adjacent pair, the same way TICK OUT's segment
    // chain already does — see the 'out' branch below — just without
    // interleaved thickness segments, since normal internal/clear
    // dimensions default to clear openings only.)
    function facePointCenter(boardIdx,axisValue){
      const verts=boardVerts[boardIdx];
      let bestDist=Infinity;verts.forEach(v=>{const d=Math.abs(axis.dot(v)-axisValue);if(d<bestDist)bestDist=d});
      const tol=Math.max(bestDist*1.5,1e-6);
      const matched=verts.filter(v=>Math.abs(axis.dot(v)-axisValue)<=tol+1e-9);
      const c=new THREE.Vector3();(matched.length?matched:verts).forEach(v=>c.add(v));
      return c.divideScalar(matched.length||verts.length)
    }
    // Use a STABLE, camera-independent offset direction — the same fix
    // already proven for TICK OUT's Left/Right (see widestHorizontalAxis()
    // below, hoisted and reusable here). The previous camera-derived
    // direction caused the dimension lines/labels to visibly shift and
    // even overlap each other depending on the viewing angle at the
    // moment DONE was pressed — confirmed directly in a real screenshot
    // from an actual installed build (diagonal-looking lines through the
    // shelves, and the TOTAL label rendering on top of a segment label).
    // MIDDLE is a measurement STYLE, while FRONT/RIGHT/LEFT/TOP/BOTTOM/BACK
    // choose the presentation FACE.  This lets MIDDLE work as a real pair
    // such as MIDDLE + FRONT or MIDDLE + RIGHT instead of clearing the side.
    // Put each internal clear-opening dimension onto the selected cabinet
    // face plane, while keeping the measured values/anchors unchanged.
    const inHorizPerp=widestHorizontalAxis(axis);
    const inVertPerp=orthogonalTo(axis,worldUp)||new THREE.Vector3(0,1,0);
    const inDepthPerp=narrowestHorizontalAxis(axis);
    if(inDepthPerp.dot(new THREE.Vector3(0,0,1))<0)inDepthPerp.negate();
    const inSideDirs={
      left:inHorizPerp.clone().negate(),right:inHorizPerp.clone(),
      top:inVertPerp.clone(),bottom:inVertPerp.clone().negate(),
      front:inDepthPerp.clone(),back:inDepthPerp.clone().negate()
    };
    const inActiveSides=chainPlacements.size?[...chainPlacements]:['front'];
    // Build one fixed cross-section lane for the selected face pair.
    // Every point on this lane differs ONLY along the measurement axis,
    // so MIDDLE+FRONT / MIDDLE+RIGHT / etc. can never become visually
    // diagonal when adjacent boards have slightly different edge vertices.
    const inLaneBase=lateralOrigin.clone().sub(axis.clone().multiplyScalar(axis.dot(lateralOrigin)));
    const inClearance=(isPhone?2:3)/mmPerUnit;
    inActiveSides.forEach(side=>{
      const d=inSideDirs[side];if(!d)return;
      const ext=extentAlong(root,d);
      inLaneBase.add(d.clone().multiplyScalar((ext.max+inClearance)-d.dot(inLaneBase)));
    });
    function internalLanePoint(axisValue){
      return inLaneBase.clone().add(axis.clone().multiplyScalar(axisValue))
    }
    const nudgeDir=widestHorizontalAxis(axis);
    const nudge=nudgeDir.clone().multiplyScalar(isPhone?.018:.026);
    // TOTAL uses a visibly LARGER lateral nudge (its own outer lane) than
    // the per-opening segments — otherwise, for a symmetric layout, TOTAL's
    // midpoint can land at the exact same axis position as the middle
    // segment (verified in a real-browser test: both at the same Y for an
    // evenly-spaced 4-shelf cabinet) and the two labels would sit on top
    // of each other.
    const totalNudge=nudge.clone().multiplyScalar(3.2);
    function drawClearOpening(a,b,label,nudgeVec){
      nudgeVec=nudgeVec||nudge;
      const clearMm=(b.min-a.max)*mmPerUnit;
      const p1=internalLanePoint(a.max),p2=internalLanePoint(b.min);
      const dimLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints([p1,p2]),lineMat);
      dimLine.renderOrder=11;scene.add(dimLine);chainResultObjects.push(dimLine);
      dimensionHeadPoint(p1);dimensionHeadPoint(p2);
      const sprite=chainLabelSprite(label!==undefined?label:mmText(Math.abs(clearMm)));
      sprite.position.copy(p1.clone().add(p2).multiplyScalar(.5)).add(nudgeVec.clone().multiplyScalar(2.5));
      scene.add(sprite);chainResultObjects.push(sprite)
    }
    // One dimension PER adjacent pair — each sits at its own real
    // compartment location, never stacked on a single global center line.
    for(let i=0;i<projected.length-1;i++)drawClearOpening(projected[i],projected[i+1]);
    // TOTAL is optional/additional (never a replacement for the segments
    // above): only shown when there's more than one opening, so it's
    // never visually redundant with the single segment already drawn.
    if(projected.length>2){
      const first=projected[0],last=projected[projected.length-1];
      drawClearOpening(first,last,mmText(Math.abs((last.min-first.max)*mmPerUnit)),totalNudge);
    }
    return true
  }

  // chainStyle === 'out'
  // Left/Right must be STABLE (the same physical side every time, frame
  // stays balanced no matter how the user has orbited), never derived
  // from the current camera angle -- unlike Top/Bottom (world up, already
  // stable), a camera-relative "right" would visibly shift if the user
  // orbited before pressing DONE. Instead, among the two world axes
  // orthogonal to the measurement axis, pick whichever one the CABINET's
  // own bounding box is actually wider along (its natural width
  // direction) and call the positive side "right".
  function widestHorizontalAxis(axisVec){
    const candidates=[new THREE.Vector3(1,0,0),new THREE.Vector3(0,0,1)];
    let best=null,bestSpan=-1;
    candidates.forEach(c=>{
      const dir=orthogonalTo(axisVec,c);
      if(!dir)return;
      const ext=extentAlong(root,dir),span=ext.max-ext.min;
      if(span>bestSpan){bestSpan=span;best=dir}
    });
    return best||orthogonalTo(axisVec,new THREE.Vector3(1,0,0))||new THREE.Vector3(1,0,0)
  }
  const horizPerp=widestHorizontalAxis(axis);
  const vertPerp=orthogonalTo(axis,worldUp)||new THREE.Vector3(0,1,0);
  // Depth axis for FRONT/BACK: the world horizontal axis the cabinet is
  // NARROWER along (mirrors widestHorizontalAxis's logic exactly, just
  // picking the other extreme) — stable and camera-independent for the
  // same reason widestHorizontalAxis is. Sign convention: whichever side
  // of that axis is +Z-leaning is treated as "front", consistent with
  // the same front=+Z / back=-Z convention already documented and used
  // by the Animation engine's entry-direction and back-vs-door logic.
  function narrowestHorizontalAxis(axisVec){
    const candidates=[new THREE.Vector3(1,0,0),new THREE.Vector3(0,0,1)];
    let best=null,bestSpan=Infinity;
    candidates.forEach(c=>{
      const dir=orthogonalTo(axisVec,c);
      if(!dir)return;
      const ext=extentAlong(root,dir),span=ext.max-ext.min;
      if(span<bestSpan){bestSpan=span;best=dir}
    });
    return best||orthogonalTo(axisVec,new THREE.Vector3(0,0,1))||new THREE.Vector3(0,0,1)
  }
  const depthPerp=narrowestHorizontalAxis(axis);
  if(depthPerp.dot(new THREE.Vector3(0,0,1))<0)depthPerp.negate(); // align to +Z = front
  const sideDirs={
    left:horizPerp.clone().negate(),right:horizPerp.clone(),
    top:vertPerp.clone(),bottom:vertPerp.clone().negate(),
    front:depthPerp.clone(),back:depthPerp.clone().negate()
  };
  const activeSides=chainPlacements.size?[...chainPlacements]:[chainSide];
  let perp=new THREE.Vector3();activeSides.forEach(side=>perp.add(sideDirs[side]||new THREE.Vector3()));
  if(perp.lengthSq()<1e-10)perp.copy(sideDirs[chainSide]||vertPerp);perp.normalize();
  const offsetMmInUnits=OUTSIDE_DIM_OFFSET_MM/mmPerUnit;
  // Extension lines are already anchored to each board's own REAL edge
  // vertex (facePoint, below); the offset must be measured from THAT
  // actual anchor point out to the cabinet's true outer boundary, not
  // from the boards' average centroid (lateralOrigin) — using the
  // centroid double-counted the cabinet's own half-width whenever a
  // board's edge already reached the cabinet boundary (the common case),
  // which is exactly the bug a real-browser measurement caught: Top/
  // Bottom correctly landed at 120.0mm but Left/Right landed at 420.0mm
  // for a 600mm-wide cabinet (300mm centroid-to-edge + 120mm margin).
  function offsetDistFor(dir){
    let maxBoardEdge=-Infinity;
    boardVerts.forEach(verts=>verts.forEach(v=>{const p=dir.dot(v);if(p>maxBoardEdge)maxBoardEdge=p}));
    const ext=extentAlong(root,dir),clearance=Math.max(0,ext.max-maxBoardEdge);
    return clearance+offsetMmInUnits
  }
  // For pair placements (RIGHT+FRONT, LEFT+FRONT, TOP+FRONT,
  // BOTTOM+FRONT, etc.) use one FIXED cabinet-aligned lane.  The lane's
  // cross-section is solved once from the cabinet faces and every segment
  // endpoint is then laneBase + axis * scalar.  This guarantees the full
  // dimension chain stays perfectly parallel to the furniture/stack axis,
  // regardless of which board vertex happens to be closest at each end.
  const laneBase=lateralOrigin.clone().sub(axis.clone().multiplyScalar(axis.dot(lateralOrigin)));
  activeSides.forEach(side=>{
    const d=sideDirs[side];if(!d)return;
    const ext=extentAlong(root,d);
    laneBase.add(d.clone().multiplyScalar((ext.max+offsetMmInUnits)-d.dot(laneBase)));
  });
  if(!activeSides.length){
    const d=sideDirs[chainSide]||perp,ext=extentAlong(root,d);
    laneBase.add(d.clone().multiplyScalar((ext.max+offsetMmInUnits)-d.dot(laneBase)));
  }
  function lanePoint(axisValue,extraOut=0){
    const p=laneBase.clone().add(axis.clone().multiplyScalar(axisValue));
    if(extraOut)p.add(perp.clone().multiplyScalar(extraOut));
    return p
  }
  // Extension lines anchor to the board's REAL edge vertex nearest the
  // chosen side (never an abstract "through the cabinet" centerline
  // point), so they stay short and visually attached to the actual board
  // face rather than crossing the cabinet.
  function facePoint(boardIdx,axisValue){
    const verts=boardVerts[boardIdx];
    let bestDist=Infinity;verts.forEach(v=>{const d=Math.abs(axis.dot(v)-axisValue);if(d<bestDist)bestDist=d});
    const tol=Math.max(bestDist*1.5,1e-6);
    let best=null,bestPerp=-Infinity;
    verts.forEach(v=>{if(Math.abs(axis.dot(v)-axisValue)<=tol+1e-9){const pp=perp.dot(v);if(pp>bestPerp){bestPerp=pp;best=v}}});
    return (best||verts[0]).clone()
  }
  segments.forEach(seg=>{
    const p1=facePoint(seg.fromIdx,seg.from),p2=facePoint(seg.toIdx,seg.to);
    const o1=lanePoint(seg.from),o2=lanePoint(seg.to);
    const ext1=new THREE.Line(new THREE.BufferGeometry().setFromPoints([p1,o1]),lineMat);
    const ext2=new THREE.Line(new THREE.BufferGeometry().setFromPoints([p2,o2]),lineMat);
    const dimLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints([o1,o2]),lineMat);
    [ext1,ext2,dimLine].forEach(l=>{l.renderOrder=11;scene.add(l);chainResultObjects.push(l)});
    dimensionHeadPoint(o1);dimensionHeadPoint(o2);
    const label=chainLabelSprite(mmText(Math.abs(seg.mm)));
    label.position.copy(o1.clone().add(o2).multiplyScalar(.5));
    scene.add(label);chainResultObjects.push(label)
  });
  // TOTAL: first selected boundary -> last selected boundary, measured
  // directly from the same real geometry as every segment (never the
  // displayed segment numbers summed/rounded), drawn as a separate OUTER
  // lane beyond the segment lane using the SAME uniform offset increment,
  // so it never overlaps the per-segment dimension line.
  {
    const firstB=projected[0],lastB=projected[projected.length-1];
    const totalMm=(lastB.max-firstB.min)*mmPerUnit;
    const p1=facePoint(firstB.idx,firstB.min),p2=facePoint(lastB.idx,lastB.max);
    const o1=lanePoint(firstB.min,offsetMmInUnits),o2=lanePoint(lastB.max,offsetMmInUnits);
    const ext1=new THREE.Line(new THREE.BufferGeometry().setFromPoints([p1,o1]),lineMat);
    const ext2=new THREE.Line(new THREE.BufferGeometry().setFromPoints([p2,o2]),lineMat);
    const dimLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints([o1,o2]),lineMat);
    [ext1,ext2,dimLine].forEach(l=>{l.renderOrder=11;scene.add(l);chainResultObjects.push(l)});
    dimensionHeadPoint(o1);dimensionHeadPoint(o2);
    // TOTAL is slightly more prominent than segment labels.
    const totalLabel=chainLabelSprite(mmText(Math.abs(totalMm)),1.15);
    totalLabel.position.copy(o1.clone().add(o2).multiplyScalar(.5));
    scene.add(totalLabel);chainResultObjects.push(totalLabel)
  }
  return true
}
// --- Pointer handling: tap vs drag, plus a rAF-throttled hover pass for the
// green preview (BOARD_SIZE) / green snap dot (POINT_TO_POINT). Hover is
// skipped while actively dragging so it never fights OrbitControls, and it
// never runs in IDLE (outside Dimension). --------------------------------
let press=null,dragging=false,hoverRAF=false,lastMoveEvent=null;
renderer.domElement.addEventListener('pointerdown',e=>{press={x:e.clientX,y:e.clientY};dragging=false});
renderer.domElement.addEventListener('pointerup',e=>{
  const wasDrag=dragging;press=null;dragging=false;
  if(wasDrag)return;
  // HIDE mode is checked FIRST, globally -- works regardless of which
  // panel (if any) is open or which dimension/animation mode is active,
  // matching its sidebar-level (not panel-scoped) placement.
  if(hideModeActive){
    const hit=hitsAt(e)[0];if(!hit)return;
    hideBoardByHit(hit.object);
    return;
  }
  if(mode==='idle'){
    const hit=hitsAt(e)[0];
    if(!document.getElementById('doorPanel').classList.contains('hidden')){
      if(!hit){console.log('[OE-DOOR] Tap did not hit any geometry at all (empty space, or camera angle missed everything).');return}
      toggleMotionByHit(hit.object);
      return;
    }
    if(!document.getElementById('animationPanel').classList.contains('hidden')){
      if(!hit)return;
      const part=partAt(hit.object);
      if(part){buildAssemblySteps(false);const idx=stepByLabel.get(part.id);if(idx!==undefined)jumpToAnimationStep(idx)}
    }
    return;
  }
  const hit=hitsAt(e)[0];if(!hit)return;
  if(mode==='board'){const part=partAt(hit.object);if(part)chooseBoard(part)}
  else if(mode==='chain'){const part=partAt(hit.object);if(part)chooseChainBoard(part)}
  else{const corner=snapCorner(e,hit);if(corner)addMeasurePoint(corner);else toast.textContent='Move closer to a corner.'}
});
renderer.domElement.addEventListener('pointermove',e=>{
  lastMoveEvent=e;
  if(press){if(Math.hypot(e.clientX-press.x,e.clientY-press.y)>10)dragging=true}
  if(hoverRAF)return;hoverRAF=true;
  requestAnimationFrame(()=>{hoverRAF=false;updateHover()})
});
function updateHover(){
  if(mode==='idle'||dragging||!lastMoveEvent||!root){setHover(null);hideSnapDot();return}
  const hit=hitsAt(lastMoveEvent)[0];
  if(!hit){setHover(null);hideSnapDot();return}
  if(mode==='board'||mode==='chain'){hideSnapDot();setHover(partAt(hit.object))}
  else{setHover(null);const corner=snapCorner(lastMoveEvent,hit);if(corner)showSnapDot(corner);else hideSnapDot()}
}
document.getElementById('dimension').onclick=()=>toggleMainSection('dimension');
document.getElementById('boardSize').onclick=()=>setDimensionMode('board');
// 3 POINT placement settings: each of the 3 axis PAIRS (Left/Right,
// Front/Back, Top/Bottom) is mutually exclusive -- ticking one auto-
// deselects its opposite, so at most one member of each pair is ever
// active at once (never 2 conflicting choices lit up at the same time).
// Redraws immediately if a board is already selected, so the effect is
// visible right away.
function redrawThreePointIfSelected(){
  if(manifest.fallbackWholeCabinet||!threePointParts.length)return;
  threePointGroups.forEach(g=>g.objects.forEach(o=>scene.remove(o)));
  threePointGroups=[];
  threePointParts.forEach(part=>{const objects=[];drawThreePointDimension(part,objects,false);threePointGroups.push({part,objects})});
}
const THREE_POINT_OPPOSITE={left:'right',right:'left',front:'back',back:'front',top:'bottom',bottom:'top'};
[['tpLeft','left'],['tpRight','right'],['tpFront','front'],['tpBack','back'],['tpTop','top'],['tpBottom','bottom']].forEach(([btnId,key])=>{
  document.getElementById(btnId).onclick=()=>{
    threePointSides[key]=!threePointSides[key];
    if(threePointSides[key]){
      const opposite=THREE_POINT_OPPOSITE[key];
      threePointSides[opposite]=false;
      const oppositeBtnId={left:'tpLeft',right:'tpRight',front:'tpFront',back:'tpBack',top:'tpTop',bottom:'tpBottom'}[opposite];
      document.getElementById(oppositeBtnId).classList.remove('active');
    }
    document.getElementById(btnId).classList.toggle('active',threePointSides[key]);
    redrawThreePointIfSelected();
  };
});
document.getElementById('tpOffsetInput').onchange=e=>{
  threePointOffsetMm=Number(e.target.value)||0;
  redrawThreePointIfSelected();
};
document.getElementById('tpTickSelect').onchange=e=>{
  threePointTickMode=e.target.value==='out'?'out':'in';
  redrawThreePointIfSelected();
};
document.getElementById('pointToPoint').onclick=()=>setDimensionMode('points');
document.getElementById('selectBoards').onclick=()=>setDimensionMode('chain');
// MULTI SELECT: seven placement buttons -- PRESENTATION/POSITION only
// (which real geometry gets measured stays exactly the same; see
// generateDimensionChain()). No TICK IN/TICK OUT button exists anymore;
// MIDDLE replaces the old TICK IN behavior, and LEFT/RIGHT/TOP/BOTTOM/
// FRONT/BACK together replace TICK OUT plus the old 4-way side selector.
function syncChainPlacementButtons(){
  document.getElementById('placeMiddle').classList.toggle('active',chainMiddle);
  ['Left','Right','Top','Bottom','Front','Back'].forEach(p=>document.getElementById('place'+p).classList.toggle('active',chainPlacements.has(p.toLowerCase())));
}
function redrawChainPlacement(){applyChainPlacement();syncChainPlacementButtons();if(chainParts.length>=2)generateDimensionChain()}
function toggleChainMiddle(){chainMiddle=!chainMiddle;redrawChainPlacement()}
// MULTI SELECT placement buttons are pair-capable: one choice from each
// opposite pair may be active at the same time. Example TOP + FRONT stays
// ticked together and places the dimension at the top-front corner. Clicking
// an already ticked button unticks it. Clicking its opposite swaps that axis.
const CHAIN_OPPOSITE={left:'right',right:'left',top:'bottom',bottom:'top',front:'back',back:'front'};
function toggleChainPlacement(placement){
  if(chainPlacements.has(placement))chainPlacements.delete(placement);
  else{chainPlacements.delete(CHAIN_OPPOSITE[placement]);chainPlacements.add(placement)}
  redrawChainPlacement()
}
document.getElementById('placeMiddle').onclick=()=>toggleChainMiddle();
document.getElementById('placeLeft').onclick=()=>toggleChainPlacement('left');
document.getElementById('placeRight').onclick=()=>toggleChainPlacement('right');
document.getElementById('placeTop').onclick=()=>toggleChainPlacement('top');
document.getElementById('placeBottom').onclick=()=>toggleChainPlacement('bottom');
document.getElementById('placeFront').onclick=()=>toggleChainPlacement('front');
document.getElementById('placeBack').onclick=()=>toggleChainPlacement('back');
function clearAllDimensions(){
  clearMeasure();
  clearChainResult();
  clearBoardDimObjects();
  completedPointGroups.forEach(g=>g.objects.forEach(o=>scene.remove(o)));
  completedPointGroups=[];
}
document.getElementById('clearDimensionBtn').onclick=clearAllDimensions;
document.getElementById('doneDimension').onclick=()=>{
  if(subMode==='chain'){
    const ok=generateDimensionChain();
    if(!ok){toast.textContent='⚠ Select at least 2 boards to build a chain';return}
    // Persist this chain's objects as their own completed group so a
    // LATER chain (different placement/side) never deletes or replaces
    // it — only the CLEAR button removes completed groups.
    completedDimensionGroups.push({placement:chainSide,style:chainStyle,objects:chainResultObjects});
    chainResultObjects=[];
    toast.textContent=`✓ Dimension chain created (${completedDimensionGroups.length} total)`;
    closeActiveSection();
    return
  }
  if(subMode==='points' && dimensionObjects.length){
    // DONE commits the current POINT measurement. Once committed it is
    // independent from the editor's working arrays, so opening another
    // sidebar tool or returning to DIMENSION cannot erase it. CLEAR is
    // the only command that removes committed dimensions.
    completedPointGroups.push({objects:dimensionObjects});
    dimensionObjects=[];measurePoints=[];measureTotalMm=0;hideSnapDot();
  }
  toast.textContent=subMode==='points'?`✓ Dimension done`:'✓ Board size done';
  closeActiveSection()
};
// Shared movement math for ONE motion (door/drawer), used by per-object
// tap-to-toggle below.
function applyMotionTransform(m,cabinetCenter,open){
  (motionMap.get(m.id)||[]).forEach(n=>{
    n.position.copy(n.userData.motionHome);n.quaternion.copy(n.userData.motionQuat);if(n.userData.motionScale)n.scale.copy(n.userData.motionScale);
    if(!open)return;
    const box=new THREE.Box3().setFromObject(n),center=box.getCenter(new THREE.Vector3());
    if(m.type==='drawer'){
      let dir=center.clone().sub(cabinetCenter);dir.y=0;
      if(Math.abs(dir.x)>Math.abs(dir.z))dir.set(Math.sign(dir.x)||1,0,0);else dir.set(0,0,Math.sign(dir.z)||1);
      n.position.add(dir.multiplyScalar(Math.max(box.getSize(new THREE.Vector3()).z,.45)));
    }else if(m.type==='door'){
      applyDoorAroundHinge(n,cabinetCenter,true);
    }
  });
}
// No more separate OPEN/CLOSE buttons (per explicit request -- tap-to-
// toggle on the object itself replaces them entirely, see
// toggleMotionByHit below). This is now called once, automatically, when
// the Door panel opens, so the person immediately knows if their model
// has no recognized doors/drawers rather than discovering it only after
// tapping something.
function registerRecoveredMotion(part,type,reason){
  if(!part||!part.id)return false;
  manifest.motions=manifest.motions||[];
  if(manifest.motions.some(m=>m.id===part.id))return false;
  const motion={id:part.id,type};manifest.motions.push(motion);
  const nodes=partMap.get(part.id)||nodesFor(part.id);
  motionMap.set(part.id,nodes);
  nodes.forEach(n=>{
    nodeToMotion.set(n,motion);
    if(!n.userData.motionHome)n.userData.motionHome=n.position.clone();
    if(!n.userData.motionQuat)n.userData.motionQuat=n.quaternion.clone();
    if(!n.userData.motionScale)n.userData.motionScale=n.scale.clone();
  });
  console.log('[OE-DOOR] Recovered',type,part.id,'from',reason,'| nodes:',nodes.length);
  return nodes.length>0;
}
function recoverDoorMotionsFromGeometry(){
  // Names are preferred, but many real SketchUp files use generic component
  // names. Reuse the already-tested cabinet geometry classifier as a safe
  // fallback: panels classified as FRONT/DOOR become tappable door motions.
  buildAssemblySteps(false);
  let added=0;
  (animSteps||[]).forEach(step=>{
    if(step.category==='door'&&registerRecoveredMotion(step.part,'door','geometry classification'))added++;
  });
  if(added)updateFeatureButtons();
  return added;
}
function requireDoorMotionOrWarn(){
  recoverDoorMotionsFromGeometry();
  const declared=(manifest.motions||[]).length;
  const mappedCount=(manifest.motions||[]).filter(m=>(motionMap.get(m.id)||[]).length>0).length;
  console.log('[OE-DOOR] Door panel opened |',declared,'known motion(s) |',mappedCount,'mapped | manual tap registration ENABLED');
  if(!mappedCount)toast.textContent='🚪 Tap the board you want to use as a door. It will be registered automatically.';
  else toast.textContent='🚪 Tap any door — or tap another board to register it as a door.';
  return true;
}
// Per-object tap-to-toggle: tapping a SPECIFIC door/drawer in the 3D
// view (while the Door panel is open, outside Hide mode) opens it if
// currently closed, closes it if currently open -- independent of the
// other doors/drawers, which keep whatever state they were already in.
// motionOpenState tracks each motion's own current state individually
// (the global OPEN/CLOSE buttons above also keep it in sync).
let motionOpenState=new Map();
// Manual DOOR mode: any mapped board the user taps can become a door on
// demand. This removes the old dependency on SketchUp component names or on
// the geometry classifier guessing FRONT vs BACK correctly.
function ensureDoorMotionForPart(part){
  if(!part||!part.id)return null;
  let motion=(manifest.motions||[]).find(m=>m.id===part.id);
  if(!motion){
    registerRecoveredMotion(part,'door','manual DOOR tap');
    motion=(manifest.motions||[]).find(m=>m.id===part.id)||null;
  }
  if(motion&&!(motionMap.get(motion.id)||[]).length){
    const nodes=partMap.get(part.id)||nodesFor(part.id);
    motionMap.set(part.id,nodes);
    nodes.forEach(n=>{nodeToMotion.set(n,motion);if(!n.userData.motionHome)n.userData.motionHome=n.position.clone();if(!n.userData.motionQuat)n.userData.motionQuat=n.quaternion.clone()});
  }
  return motion;
}
function applyDoorAroundHinge(node,cabinetCenter,open){
  if(!node)return;
  if(!node.userData.motionHome)node.userData.motionHome=node.position.clone();
  if(!node.userData.motionQuat)node.userData.motionQuat=node.quaternion.clone();
  if(!node.userData.motionScale)node.userData.motionScale=node.scale.clone();
  node.position.copy(node.userData.motionHome);node.quaternion.copy(node.userData.motionQuat);node.scale.copy(node.userData.motionScale);
  node.updateMatrix();node.updateMatrixWorld(true);
  if(!open)return;
  const box=new THREE.Box3().setFromObject(node),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
  // Pick the longer horizontal span as the door-width direction. The hinge
  // is the OUTER vertical edge nearest the cabinet's corresponding side.
  const alongX=size.x>=size.z;
  let hingeWorld=center.clone(),sign=1;
  if(alongX){
    const useMin=center.x<=cabinetCenter.x;
    hingeWorld.x=useMin?box.min.x:box.max.x;
    sign=useMin?-1:1;
  }else{
    const useMin=center.z<=cabinetCenter.z;
    hingeWorld.z=useMin?box.min.z:box.max.z;
    sign=useMin?1:-1;
  }
  // Rotate the ENTIRE board around that world-space hinge edge, not around
  // the node origin/centre. This is the key fix for natural cabinet doors.
  const rot=new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(0,1,0),sign*Math.PI/2);
  const t1=new THREE.Matrix4().makeTranslation(-hingeWorld.x,-hingeWorld.y,-hingeWorld.z);
  const t2=new THREE.Matrix4().makeTranslation(hingeWorld.x,hingeWorld.y,hingeWorld.z);
  const worldOpen=new THREE.Matrix4().multiplyMatrices(t2,rot).multiply(t1).multiply(node.matrixWorld);
  const parentInv=new THREE.Matrix4();
  if(node.parent){node.parent.updateMatrixWorld(true);parentInv.copy(node.parent.matrixWorld).invert()}
  else parentInv.identity();
  const localOpen=new THREE.Matrix4().multiplyMatrices(parentInv,worldOpen);
  localOpen.decompose(node.position,node.quaternion,node.scale);
  node.updateMatrix();node.updateMatrixWorld(true);
}
function toggleMotionByHit(hitObject){
  let o=hitObject,motion=null;
  while(o){if(nodeToMotion.has(o)){motion=nodeToMotion.get(o);break}o=o.parent}
  const hitPart=partAt(hitObject);
  if(!motion&&hitPart){
    // First try any declared/auto-recovered motion, then fall back to the
    // user's explicit tap: the tapped mapped board IS the door.
    recoverDoorMotionsFromGeometry();
    motion=(manifest.motions||[]).find(m=>m.id===hitPart.id)||ensureDoorMotionForPart(hitPart);
  }
  console.log('[OE-DOOR] Tap hit object:',hitObject.name||hitObject.uuid,'| resolved part:',hitPart?hitPart.id:'(none)','| resolved motion:',motion?{id:motion.id,type:motion.type}:'(none — not a door/drawer)','| manifest.motions:',(manifest.motions||[]).map(m=>m.id),'| nodeToMotion size:',nodeToMotion.size);
  if(!motion){
    if(!hitPart)console.warn('[OE-DOOR] Hit geometry could not be resolved to a mapped board.');
    else console.warn('[OE-DOOR] Could not create a door motion for tapped board',hitPart.id);
    toast.textContent='⚠ Tap a mapped board surface to use it as a door.';
    return false;
  }
  const motionNodes=motionMap.get(motion.id)||[];
  if(!motionNodes.length){
    console.warn('[OE-DOOR] Motion',motion.id,'is listed in manifest.motions but has ZERO matching 3D nodes in motionMap — this board likely failed to map to real geometry on export (see the "X/Y boards mapped" toast on load: a mismatch there means some declared boards, possibly including this one, have no corresponding 3D node).');
    return false;
  }
  const cabinetCenter=new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3());
  const nextOpen=!motionOpenState.get(motion.id);
  applyMotionTransform(motion,cabinetCenter,nextOpen);
  motionOpenState.set(motion.id,nextOpen);
  toast.textContent=nextOpen?`🚪 ${motion.id} opened`:`🚪 ${motion.id} closed`;
  console.log('[OE-DOOR] Toggled',motion.id,'to',nextOpen?'OPEN':'CLOSED','| moved',motionNodes.length,'node(s)');
  return true;
}
// HIDE is now a proper exclusive section (per explicit request, fixing a
// real reported bug: HIDE and another section like DIMENSION could both
// show as active/blue at once): opening it via toggleMainSection closes
// whatever OTHER section was active first, and opening any OTHER
// section correctly turns HIDE off too (see closeActiveSection's 'hide'
// branch above) -- exactly the same mutual-exclusion every other
// sidebar button already had. Once active, tapping ANY board anywhere
// hides it, tracked on hiddenStack (most-recent-last) so it can be
// undone one at a time via the sidebar's own BACK button, or all at
// once via UNHIDE ALL -- both independent of whether HIDE itself is
// still the active section (a board stays hidden after leaving Hide
// mode, exactly like it should).
let hideModeActive=false,hiddenStack=[];
document.getElementById('hideModeBtn').onclick=()=>toggleMainSection('hide');
function hideBoardByHit(hitObject){
  const part=partAt(hitObject);
  if(!part)return false;
  const nodes=partMap.get(part.id)||[];
  const node=nodes[0];
  if(!node||!node.visible)return false;
  node.visible=false;
  hiddenStack.push({part,node});
  toast.textContent=`👁 ${part.id} hidden`;
  return true;
}
function unhideAll(){
  if(!hiddenStack.length){toast.textContent='Nothing is hidden.';return}
  const n=hiddenStack.length;
  hiddenStack.forEach(h=>{h.node.visible=true});
  hiddenStack=[];
  toast.textContent=`👁 Unhid ${n} board${n===1?'':'s'}`;
}
document.getElementById('unhideAllBtn').onclick=unhideAll;
// Undoing ONE hide at a time via the sidebar's own ◀ BACK button: while
// the Door panel is the active section AND at least one board is
// currently hidden, BACK un-hides just the MOST RECENTLY hidden board
// instead of its normal "exit this panel" behavior -- repeatable, one
// press per board. Only once nothing is left hidden does BACK fall
// through to its normal exit-the-panel behavior. See the backBtn
// override near closeActiveSection() for the other half of this.
// Extracts an exact Label ID from a raw QR/barcode payload: a raw Label
// ID, a URL with a ?part= query param, or a small JSON payload with an
// id/label/labelId field -- parsed defensively, never guessed or matched
// loosely.
function labelIdFromScanValue(value){
  const v=String(value||'').trim();
  try{const u=new URL(v,location.href);const part=u.searchParams.get('part');if(part)return part.trim()}catch(e){}
  if(v.startsWith('{')){try{const j=JSON.parse(v);const cand=j.id||j.label||j.labelId;if(cand)return String(cand).trim()}catch(e){}}
  return v
}
let lastScannedId='';
// QR detection via jsQR sampling a hidden <canvas> each frame — works in
// EVERY browser via plain Canvas pixel data, unlike the native
// BarcodeDetector API this used to depend on (which is missing in
// Safari/iOS and Firefox entirely, and was found to be unavailable even
// in this environment's desktop Chromium — a silent, unrecoverable
// failure mode where the camera preview shows but nothing is ever
// detected, exactly matching the reported "scan reads the QR but never
// selects a board" symptom). The downstream pipeline (labelIdFromScanValue
// -> resolveAndSelectBoard -> lastScannedId debounce -> mode-aware chain
// integration) is completely unchanged — only the raw detection mechanism
// was replaced, so there is still only ONE selection system.
let scanCanvas=null,scanCtx=null,pendingScannedId='';
function ensureScanCanvas(){if(!scanCanvas){scanCanvas=document.createElement('canvas');scanCtx=scanCanvas.getContext('2d',{willReadFrequently:true})}return scanCanvas}
function scannerCameraProblem(){
  if(!window.isSecureContext&&location.hostname!=='localhost'&&location.hostname!=='127.0.0.1')return 'live';
  if(!navigator.mediaDevices||typeof navigator.mediaDevices.getUserMedia!=='function')return 'live';
  return '';
}
function showPhotoScanFallback(message){
  const video=document.getElementById('scanVideo');
  const btn=document.getElementById('scanPhotoBtn');
  video.classList.add('hidden');btn.classList.remove('hidden');
  document.getElementById('scanHelp').textContent=message||'On this phone/HTTP address, use TAKE PHOTO / SCAN QR. It opens the rear camera without requiring HTTPS.';
}
async function decodeQrImageFile(file){
  if(!file)return false;
  const help=document.getElementById('scanHelp');help.textContent='Reading QR…';
  try{
    const bmp=await createImageBitmap(file);
    const canvas=ensureScanCanvas();
    const maxSide=1800,scale=Math.min(1,maxSide/Math.max(bmp.width,bmp.height));
    canvas.width=Math.max(1,Math.round(bmp.width*scale));canvas.height=Math.max(1,Math.round(bmp.height*scale));
    scanCtx.drawImage(bmp,0,0,canvas.width,canvas.height);if(bmp.close)bmp.close();
    const imageData=scanCtx.getImageData(0,0,canvas.width,canvas.height);
    const result=jsQR(imageData.data,imageData.width,imageData.height,{inversionAttempts:'attemptBoth'});
    if(!result||!result.data){help.textContent='QR not found in photo. Move closer, keep the QR square, and try again.';return false}
    const id=labelIdFromScanValue(result.data);
    const found=await applyScannedBoard(id);
    if(found&&mode!=='chain'){stopScan();hide('scanPanel')}
    return found;
  }catch(e){console.error('[OE-QR] photo scan failed:',e);help.textContent='Could not read that photo. Try again or type the Label ID in Search.';return false}
}
async function waitForModelReady(maxMs){
  const start=performance.now();
  while(!modelReady&&performance.now()-start<(maxMs||12000))await new Promise(r=>setTimeout(r,120));
  return modelReady;
}
async function applyScannedBoard(id){
  if(!id)return false;
  const help=document.getElementById('scanHelp');
  pendingScannedId=id;
  if(!modelReady){
    help.textContent=`QR read: ${id} • loading 3D model…`;
    const ready=await waitForModelReady(12000);
    if(!ready){help.textContent=`QR read: ${id} • model is still loading. Keep this scanner open and try again.`;return false}
  }
  let found=false;
  try{found=focusBoardById(id)}catch(selErr){console.error('[OE-QR] focusBoardById THREW an error:',selErr)}
  if(found){pendingScannedId='';lastScannedId=id;help.textContent=`Found ${id} ✓`;return true}
  help.textContent=`QR read: ${id} • board not found in this project.`;
  pendingScannedId='';lastScannedId='';
  return false;
}
async function startScan(){
  show('scanPanel');
  const help=document.getElementById('scanHelp');
  help.textContent='Point the camera at an OpenEyes Label.';
  if(typeof jsQR!=='function'&&!('BarcodeDetector' in window)){help.textContent='QR scanning is unavailable in this browser. Type the Label ID in Search instead.';return}
  const camProblem=scannerCameraProblem();
  if(camProblem){showPhotoScanFallback('Live camera preview is blocked on this HTTP LAN address. Tap TAKE PHOTO / SCAN QR — the phone camera will open and the QR will still select the exact 3D board.');return}
  document.getElementById('scanVideo').classList.remove('hidden');document.getElementById('scanPhotoBtn').classList.add('hidden');
  try{
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}}});
    const video=document.getElementById('scanVideo');video.srcObject=stream;
    video.setAttribute('playsinline','');
    try{await video.play()}catch(e){/* some browsers resolve play() late */}
    // Wait for real frame dimensions before the first decode attempt.
    for(let i=0;i<200&&!(video.videoWidth>0&&video.videoHeight>0);i++){
      await new Promise(r=>setTimeout(r,50));
    }
    console.log('[OE-QR] camera ready',video.videoWidth+'x'+video.videoHeight);
    const canvas=ensureScanCanvas();
    let scanDetector=null;
    try{
      if('BarcodeDetector' in window){
        const fmts=await window.BarcodeDetector.getSupportedFormats();
        if(fmts&&fmts.indexOf('qr_code')>=0){
          scanDetector=new window.BarcodeDetector({formats:['qr_code']});
          console.log('[OE-QR] BarcodeDetector available');
        }
      }
    }catch(e){scanDetector=null}
    if(!scanDetector)console.log('[OE-QR] BarcodeDetector unavailable -> jsQR');
    let scanBusy=false,lastDecodeAt=0;
    // BarcodeDetector first, then jsQR on the SAME frame. An empty native
    // result means "this decoder did not find it", never "nothing is there".
    const decodeOneFrame=async()=>{
      if(scanDetector){
        try{
          const hits=await scanDetector.detect(video);
          if(hits&&hits.length&&hits[0].rawValue)return hits[0].rawValue;
        }catch(e){/* fall through to jsQR */}
      }
      if(typeof jsQR!=='function')return null;
      canvas.width=video.videoWidth;canvas.height=video.videoHeight;
      scanCtx.drawImage(video,0,0,canvas.width,canvas.height);
      const d=scanCtx.getImageData(0,0,canvas.width,canvas.height);
      const hit=jsQR(d.data,d.width,d.height,{inversionAttempts:'attemptBoth'});
      return hit&&hit.data?hit.data:null;
    };
    const tick=async()=>{
      if(!stream)return;
      // Real readiness for pixel capture is the frame size. A live camera
      // stream on Android commonly sits at HAVE_CURRENT_DATA (2) forever, so
      // the old readyState===4 gate decoded ZERO frames over HTTPS.
      const nowMs=Date.now();
      if(!scanBusy&&nowMs-lastDecodeAt>=100&&video.videoWidth>0&&video.videoHeight>0&&video.readyState>=2){
        scanBusy=true;lastDecodeAt=nowMs;
        try{
          const raw=await decodeOneFrame();
          const result=raw?{data:raw}:null;
          if(result&&result.data){
            console.log('[OE-QR] QR decoded:',result.data);
            const id=labelIdFromScanValue(result.data);
            console.log('[OE-QR] Label ID:',id);
            if(id&&id!==lastScannedId&&id!==pendingScannedId){
              console.log('[OE-QR] Project part lookup:',manifest.parts.find(p=>p.id===id)?'FOUND':'NOT FOUND');
              console.log('[OE-QR] 3D object found:',(partMap.get(id)||[]).length>0,(partMap.get(id)||[]).length,'node(s)');
              console.log('[OE-QR] modelReady:',modelReady,'| current mode:',mode);
              // Hold a decoded Label ID while the model/manifest is still
              // loading. The user no longer has to move the camera away and
              // rescan the same QR after loading finishes.
              applyScannedBoard(id).then(found=>{
                console.log('[OE-QR] Selection applied:',found,'mode=',mode);
                console.log('[OE-QR] Camera focus applied (cameraTween active):',!!cameraTween);
                if(found&&mode!=='chain'){console.log('[OE-QR] Closing scanner, returning to 3D');stopScan();hide('scanPanel')}
              });
            }
          }
        }catch(e){console.error('[OE-QR] detection loop error:',e)}
        finally{scanBusy=false}
      }
      requestAnimationFrame(tick)
    };
    tick()
  }catch(e){
    console.error('[OE-QR] getUserMedia failed:',e);
    const name=e&&e.name?e.name:'';
    if(name==='NotAllowedError'||name==='SecurityError'){showPhotoScanFallback('Live camera permission is blocked. Tap TAKE PHOTO / SCAN QR instead.')}
    else help.textContent=name==='NotFoundError'?'No camera was found on this device.':name==='NotReadableError'?'Camera is busy in another app. Close that app and try again.':`Camera could not start${name?` (${name})`:''}.`;
  }
}
document.getElementById('scanPhotoBtn').onclick=()=>document.getElementById('scanPhotoInput').click();
document.getElementById('scanPhotoInput').onchange=e=>{const f=e.target.files&&e.target.files[0];e.target.value='';if(f)decodeQrImageFile(f)};
function stopScan(){if(stream){stream.getTracks().forEach(x=>x.stop());stream=null}lastScannedId='';pendingScannedId=''}
document.getElementById('scan').onclick=startScan;
// ===== PHONE LINK ==========================================================
// Phone -> public HTTPS relay -> this PC. The PC only ever dials OUT, so the
// phone can be on any network at all (different Wi-Fi, mobile data) and no
// inbound port, LAN route or shared subnet is needed.
//
// Everything below is strictly additive and fully self-contained:
//   * It runs AFTER the 3D model has loaded and never blocks startup.
//   * Every network call is wrapped — a missing/offline relay only changes
//     the status chip to "Offline". Manual Search, Dimension, Door, Hide,
//     Animation and QR printing are untouched and keep working.
//   * A received Board ID goes through focusBoardById(), the exact same
//     function the manual Search box uses. No duplicated search logic, no
//     page reload, no clearing of existing dimensions.
(function(){
  // Cloud /live has no pairing route at all — stay completely inert there.
  // A MISSING RELAY is deliberately NOT an early exit any more: hiding the
  // PAIR PHONE button when the relay is unconfigured left the user with no
  // way to discover WHY scanning did nothing. The button now always shows
  // and explains itself.
  if(!pairingQrUrl)return;
  const chip=document.getElementById('phoneChip'),
        dot=chip.querySelector('.pcDot'),
        txt=chip.querySelector('.pcTxt'),
        phoneLine=document.getElementById('phoneStatus'),
        pairBtn=document.getElementById('pairPhone');
  const SESSION_STORE='oe.phonelink.pcsession';
  let sessionId='',lastSeq=0,es=null,pollAbort=null,retry=0,retryTimer=null,
      stopped=false,transport='sse',lastBoard='',phonePaired=false;

  chip.classList.remove('hidden');
  pairBtn.classList.remove('hidden');
  phoneLine.classList.remove('hidden');

  function setStatus(kind,label){
    dot.className='pcDot'+(kind?' '+kind:'');
    txt.innerHTML=`Phone Link: ${label}`+(lastBoard?` <span class="pcLast">• ${esc(lastBoard)}</span>`:'');
  }
  function setPairStatus(text){document.getElementById('pairStatus').textContent=text}
  // The SEARCH panel status the spec asks for:
  //   Phone: Not paired  ->  Phone: Paired ✓  ->  Last scan: <id> ✓
  function setPhoneLine(pairLabel,pairClass,scanHtml){
    phoneLine.innerHTML=`<b>Phone:</b> <span class="${pairClass||''}">${pairLabel}</span>`
      +(scanHtml?`<br>${scanHtml}`:'');
  }
  setPhoneLine('Not paired','waitTxt','');
  setStatus('','Starting…');

  // --- Relay not configured ------------------------------------------------
  // Everything else in the viewer keeps working; only this feature is off.
  if(!relayUrl){
    setStatus('bad','Offline');
    setPhoneLine('Relay not configured','badTxt','');
    const explain=()=>{
      show('pairPanel');
      document.getElementById('pairQrImg').classList.add('hidden');
      document.getElementById('pairSteps').innerHTML=
        '<b>Phone scanning is not set up yet.</b><br>'
        +'A printed board QR holds only the Board ID, so a phone\u2019s normal camera app '
        +'can only show it as text \u2014 it has nowhere to send it. The phone must scan '
        +'board labels from the paired OpenEyes scanner page instead.<br><br>'
        +'<b>1.</b> Deploy the relay once (see <code>README_PHONE_LINK.md</code>).<br>'
        +'<b>2.</b> Put its HTTPS address in <code>relay_url.txt</code> next to '
        +'<code>START_LOCAL_VIEWER.bat</code>.<br>'
        +'<b>3.</b> Refresh this page, then press PAIR PHONE again.';
      setPairStatus('Until then, typing a Board ID into SEARCH still works normally.');
    };
    chip.onclick=explain;pairBtn.onclick=explain;
    console.warn('[PHONE] relay not configured — set relay_url.txt or OPENEYES_RELAY_URL');
    return;
  }

  // Publishing uploads this cabinet's model + manifest to the relay once, so
  // the phone can run the 3D viewer itself. Roughly 0.2 MB for a 300-board
  // unit; the phone caches it afterwards and works on a weak signal.
  let publishedPhoneUrl='';
  async function publishToPhone(){
    const img=document.getElementById('pairQrImg');
    setPairStatus('Uploading this cabinet to the relay…');
    try{
      const r=await fetch('/local/publish/'+encodeURIComponent(projectToken),{method:'POST'});
      const j=await r.json().catch(()=>({}));
      if(!r.ok){
        img.classList.add('hidden');
        setPairStatus('Could not publish: '+(j.detail||j.error||r.status));
        return;
      }
      publishedPhoneUrl=j.phone_url||'';
      img.src='/local/phone-qr.svg?project='+encodeURIComponent(projectToken)+'&v='+encodeURIComponent(j.version||'');
      img.classList.remove('hidden');
      const kb=Math.round((j.model_bytes||0)/1024);
      setPairStatus('Ready — '+kb+' KB published. Scan the QR with the phone camera.'
        +(j.persisted?'':' (Relay stores this in memory: publish again if the relay restarts.)'));
      console.log('[PHONE] published',j.version,j.phone_url);
    }catch(e){
      img.classList.add('hidden');
      setPairStatus('Could not reach this PC to publish: '+(e&&e.message));
    }
  }
  function openPairPanel(){
    show('pairPanel');
    publishToPhone();
  }
  chip.onclick=openPairPanel;
  pairBtn.onclick=openPairPanel;

  // --- Backoff ------------------------------------------------------------
  // Reconnect forever, never reload the page, and never hammer the relay:
  // 1s, 2s, 4s, 8s, 16s, then hold at 30s.
  function scheduleRetry(reason){
    if(stopped)return;
    clearTimeout(retryTimer);
    const delay=Math.min(30000,1000*Math.pow(2,Math.min(retry,5)));
    retry++;
    setStatus('warn','Reconnecting…');
    console.warn('[PHONE] disconnected ('+reason+') — retrying in '+Math.round(delay/1000)+'s');
    retryTimer=setTimeout(connect,delay);
  }
  function onConnected(){
    retry=0;
    setStatus('ok','Connected');
    setPairStatus('Connected to the relay. Scan the QR with your phone.');
    if(!phonePaired)setPhoneLine('Not paired','waitTxt','Press PAIR PHONE, then scan the QR with the phone.');
    console.log('[PHONE] relay connected • session',sessionId.slice(0,6)+'…','• transport',transport);
  }

  // --- Board delivery -----------------------------------------------------
  function applyEvent(ev){
    if(!ev||typeof ev.seq!=='number')return;
    if(ev.seq<=lastSeq)return;            // replayed after a reconnect
    lastSeq=ev.seq;
    const id=String(ev.board_id||'').trim();
    if(!id)return;
    lastBoard=id;phonePaired=true;
    setStatus('ok','Connected');
    console.log('[PHONE] received',id);
    // FIX10 / V092: a remote phone scan must behave exactly like the user's
    // successful PC workflow: SELECT QR -> put that exact Board ID into the
    // Search field -> run SEARCH automatically.  Do not bypass Search by
    // calling focusBoardById() directly here.
    // FIX11 / V094: after the relay confirms a phone scan, mirror the
    // exact PC workflow automatically: OPEN SEARCH -> fill Board ID -> SEARCH.
    // No extra QR-selection or SEND click is required on either device.
    try{toggleMainSection('search')}catch(e){console.warn('[PHONE] could not open Search panel',e)}
    const q=document.getElementById('query');
    if(q)q.value=id;
    const runAutoSearch=()=>{
      if(!modelReady){
        setPhoneLine('Paired ✓','okTxt',`QR selected: <b>${esc(id)}</b><br><span class="waitTxt">Waiting for 3D model…</span>`);
        setTimeout(runAutoSearch,350);
        return;
      }
      console.log('[VIEWER] Searching board:',id);
      try{find()}catch(e){console.error('[BOARD] auto search threw:',e)}
      // The manifest is the authoritative Board ID store: manifest.parts[].id
      // is the same field the manual Search and the printed labels use. Exact
      // match only - selecting the wrong board is worse than finding none.
      const ok=manifest.parts.some(p=>p.id===id);
      console.log('[VIEWER] Board found:',ok);
      if(ok){
        console.log('[BOARD] auto search found + focused',id);
        setPhoneLine('Paired ✓','okTxt',`Last scan: <b>${esc(id)}</b> <span class="okTxt">✓ AUTO SEARCH</span>`);
      }else{
        console.warn('[VIEWER] Board not found:',id);
        setPhoneLine('Paired ✓','okTxt',`<span class="badTxt">Board not found:</span> <b>${esc(id)}</b>`);
      }
      // Tell the phone what actually happened, so it can show "Selected on PC"
      // rather than the much weaker "Sent to PC". Best-effort and fully
      // optional: a relay without /ack simply 404s and nothing here changes.
      reportAck(ev.seq,id,ok?'SELECTED':'NOT_FOUND');
    };
    runAutoSearch();
  }

  // --- Acknowledgement ----------------------------------------------------
  // Fire-and-forget. Never allowed to throw into the scan pipeline: if the
  // relay is an older build without /ack, the phone just falls back to
  // reporting delivery instead of selection.
  // ackSupported: null = unknown, true = relay has /ack, false = older relay.
  // Once an older relay is detected we stop calling it, so the console is not
  // flooded with one red 404 per scan for the rest of the session.
  let ackSupported=null;
  async function reportAck(seq,boardId,result){
    const relay=relayUrl;
    if(!relay||!sessionId||ackSupported===false)return;
    try{
      const r=await fetch(relay+'/api/session/'+encodeURIComponent(sessionId)+'/ack',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({seq:seq||0,board_id:boardId,result:result})
      });
      if(r.ok){
        if(ackSupported!==true)console.log('[PHONE] relay supports scan acknowledgement');
        ackSupported=true;
        console.log('[PHONE] ack sent:',result,boardId);
      }else if(r.status===404){
        ackSupported=false;
        console.log('[PHONE] relay build has no /ack endpoint — '
          +'phone will show "Sent to PC" instead of "Selected on PC". '
          +'Deploy relay 1.5.0+ to enable it. Not retrying.');
      }else{
        console.log('[PHONE] ack rejected (HTTP '+r.status+')');
      }
    }catch(e){
      console.log('[PHONE] ack unavailable:',e&&e.message);
    }
  }

  // --- Session ------------------------------------------------------------
  // Reuse the previous session id across page refreshes so a phone that is
  // already paired keeps working after F5. If the relay has since expired
  // it, a fresh one is minted automatically.
  async function ensureSession(){
    const saved=sessionStorage.getItem(SESSION_STORE)||'';
    if(saved){
      try{
        const r=await fetch(relayUrl+'/api/session/'+encodeURIComponent(saved)+'/keepalive',{method:'POST'});
        if(r.ok){sessionId=saved;return true}
      }catch(e){/* fall through to minting a new one */}
    }
    const r=await fetch(relayUrl+'/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if(!r.ok)throw new Error('relay returned '+r.status);
    const j=await r.json();
    if(!j||!j.session_id)throw new Error('relay returned no session_id');
    sessionId=j.session_id;lastSeq=0;
    sessionStorage.setItem(SESSION_STORE,sessionId);
    return true;
  }

  // --- Transport: Server-Sent Events (primary) ----------------------------
  function connectSse(){
    transport='sse';
    es=new EventSource(relayUrl+'/api/session/'+encodeURIComponent(sessionId)+'/events?after='+lastSeq);
    let opened=false;
    es.addEventListener('ready',()=>{opened=true;onConnected()});
    es.addEventListener('scan',e=>{try{applyEvent(JSON.parse(e.data))}catch(err){console.error('[PHONE] bad event',err)}});
    es.onerror=()=>{
      es.close();es=null;
      // If SSE never even opened, the network path probably buffers or
      // blocks event streams (some corporate proxies do). Fall back to
      // long polling, which is plain fetch and gets through anywhere.
      if(!opened&&retry>=2){console.warn('[PHONE] SSE unavailable — falling back to long polling');connectPoll();return}
      scheduleRetry('sse error');
    };
  }

  // --- Transport: long polling (fallback) ---------------------------------
  async function connectPoll(){
    transport='poll';
    onConnected();
    while(!stopped&&transport==='poll'){
      try{
        pollAbort=new AbortController();
        const r=await fetch(relayUrl+'/api/session/'+encodeURIComponent(sessionId)+'/poll?after='+lastSeq,
                            {signal:pollAbort.signal,cache:'no-store'});
        if(r.status===404){console.warn('[PHONE] session expired — creating a new one');sessionStorage.removeItem(SESSION_STORE);transport='sse';scheduleRetry('session expired');return}
        if(!r.ok)throw new Error('poll '+r.status);
        const j=await r.json();
        (j.events||[]).forEach(applyEvent);
        retry=0;setStatus('ok','Connected');
      }catch(e){
        if(stopped)return;
        transport='sse';           // next attempt starts back at SSE
        scheduleRetry('poll error');
        return;
      }
    }
  }

  async function connect(){
    if(stopped)return;
    clearTimeout(retryTimer);
    if(es){es.close();es=null}
    if(pollAbort){try{pollAbort.abort()}catch(e){}pollAbort=null}
    setStatus('warn',retry?'Reconnecting…':'Waiting');
    try{
      await ensureSession();
      showPairingQr();
      if(transport==='poll')connectPoll();else connectSse();
    }catch(e){
      setStatus('bad','Offline');
      setPhoneLine('Relay offline','badTxt','Manual SEARCH still works.');
      setPairStatus('Relay unreachable. The viewer still works normally — Search, Dimension, Door and Hide are unaffected.');
      console.warn('[PHONE] relay unavailable:',e&&e.message);
      scheduleRetry('session setup failed');
    }
  }

  // Keepalive so the relay does not expire an idle-but-open viewer session.
  // Its reply also tells us whether a phone has scanned the pairing QR yet,
  // which is how "Not paired" becomes "Paired ✓" before any board is scanned.
  setInterval(()=>{
    if(!sessionId||stopped)return;
    fetch(relayUrl+'/api/session/'+encodeURIComponent(sessionId)+'/keepalive',{method:'POST'})
      .then(r=>r.ok?r.json():null)
      .then(j=>{
        if(!j||!j.phone_paired||phonePaired)return;
        phonePaired=true;
        console.log('[PHONE] paired');
        setPhoneLine('Paired ✓','okTxt','Waiting for a board scan…');
        setPairStatus('Phone paired. Scan a printed board label now.');
      })
      .catch(()=>{});
  },5000);

  document.getElementById('pairRetry').onclick=()=>{retry=0;transport='sse';connect();setPairStatus('Reconnecting…')};
  document.getElementById('pairNewSession').onclick=()=>{
    // Re-upload the cabinet. Needed after editing the model, or after the
    // relay restarted and dropped its in-memory copy.
    publishToPhone();
  };
  window.addEventListener('beforeunload',()=>{stopped=true;if(es)es.close();if(pollAbort){try{pollAbort.abort()}catch(e){}}});

  // Start only once the 3D model is up, so a scan can never arrive before
  // the manifest exists. Startup itself is never gated on this.
  const boot=()=>{if(modelReady)connect();else setTimeout(boot,250)};
  setTimeout(boot,300);
})();
// ===== end PHONE LINK ======================================================
const modelLoad=new Promise((resolve,reject)=>{if(asset.toLowerCase().includes('.dae'))new ColladaLoader().load(asset,g=>resolve(g),undefined,reject);else new GLTFLoader().load(asset,g=>resolve(g),undefined,reject)});
Promise.all([fetch(manifestUrl,{cache:'no-cache'}).then(r=>r.json()),modelLoad,readColladaUnit(asset)]).then(([m,g,unitMm])=>{
  manifest=m;root=g.scene;scene.add(root);declaredMmPerUnit=unitMm;
  prepareParts();calibrateUnits();fit();applyViewInset();
  document.getElementById('fallbackBanner').classList.toggle('hidden',!manifest.fallbackWholeCabinet);
  applyViewInset();
  toast.textContent=`Ready • ${ordered.length}/${(manifest.parts||[]).length} boards mapped`;
  find();if(initialPart)selectPart(initialPart);modelReady=true
}).catch(e=>{toast.textContent='❌ 3D Preview could not load';console.error(e)});
__SW_REGISTER__
</script></body></html>'''
    for marker, value in values.items():
        page = page.replace(marker, value)
    return page
