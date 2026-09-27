"""
StitchDraft Studio — private-beta web app.

Upload artwork -> the engine digitizes it server-side -> sewn preview,
stitch stats, .DST download, a printable production worksheet, and an
approve/send-back verdict per job. Send-backs record WHY (and optionally
the corrected file), so every rejection becomes a training pair.

Tenancy: access codes map to isolated per-tenant job folders. Codes come
from the STITCHDRAFT_TENANTS environment variable (never from git). The
engine code never leaves the server.

Config (environment):
  STITCHDRAFT_TENANTS  access codes: JSON {"CODE": "Partner"} or
                       CODE=Partner,CODE2=Partner 2
  STITCHDRAFT_SECRET   cookie-signing secret (long random string)
  STITCHDRAFT_DATA     where jobs live — point at a persistent disk
                       (e.g. /var/data on Render); defaults to ./data

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

BASE = Path(__file__).parent
DATA = Path(os.environ.get("STITCHDRAFT_DATA") or BASE / "data")
DATA.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BASE / "engine"))

SECRET = os.environ.get("STITCHDRAFT_SECRET") or (DATA / ".secret")
if isinstance(SECRET, Path):
    if not SECRET.exists():
        SECRET.write_text(secrets.token_hex(32))
    SECRET = SECRET.read_text().strip()


def load_tenants():
    """Access codes: env var first (production), then a local gitignored
    tenants.json (development), then a demo code so a fresh checkout runs."""
    raw = os.environ.get("STITCHDRAFT_TENANTS", "").strip()
    if raw:
        if raw.startswith("{"):
            t = json.loads(raw)
        else:
            t = dict(p.split("=", 1) for p in raw.split(",") if "=" in p)
    elif (BASE / "tenants.json").exists():
        t = json.loads((BASE / "tenants.json").read_text())
    else:
        t = {"DEMO-2026": "Demo Shop"}
    return {k.strip().upper(): v.strip() for k, v in t.items()}


TENANTS = load_tenants()
# HTTPS-only session cookie in production (Render sets RENDER=true); plain
# http on localhost for development would otherwise never keep a login
SECURE_COOKIES = bool(os.environ.get("RENDER") or os.environ.get("STITCHDRAFT_SECURE_COOKIES"))

MAX_UPLOAD_MB = 15
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
CORRECTED_EXT = {".dst", ".emb", ".exp", ".pes", ".jef", ".vp3", ".pdf",
                 ".png", ".jpg", ".jpeg"}
STITCHES_PER_MIN = 800   # worksheet run-time estimate: typical commercial head
SECS_PER_COLOUR = 20     # thread change + restart, per colour after the first

# Why a draft was sent back — the pilot's improvement signal. Keys are
# stored; labels are shown. Add to the end, never rename a key.
REASONS = {
    "small_text": "Small text / fine detail",
    "density": "Density — too heavy or too light",
    "direction": "Fill or satin direction",
    "pull": "Shape distortion / pull compensation",
    "trims": "Too many trims or jumps",
    "underlay": "Underlay",
    "colours": "Wrong colours or colour order",
    "missing": "Parts missing or dropped",
    "artwork": "Artwork unsuitable (gradient, photo, too complex)",
    "other": "Other",
}

# One engine run at a time: the host has a hard memory ceiling, and two
# concurrent digitize jobs would double the peak. Extra requests queue here.
ENGINE_SEM = asyncio.Semaphore(1)
# jobs.json is read-modify-write; serialize so two requests can't lose an edit
JOBS_LOCK = threading.Lock()

# Keep the numeric libraries single-threaded in the engine subprocess —
# thread pools in numpy/scipy/opencv cost real memory and help nothing
# for one job at a time.
ENGINE_ENV = {**os.environ,
              "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
              "MKL_NUM_THREADS": "1", "OPENCV_OPENCL_RUNTIME": "disabled"}

app = FastAPI(title="StitchDraft Studio")
esc = html.escape


# ---------------------------------------------------------------- auth
def sign(value: str) -> str:
    return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def session_value(tenant: str, code: str) -> str:
    # the signature covers the access code, so changing a partner's code
    # logs out every session made with the old one
    return f"{tenant}|{sign(tenant + '|' + code)}"


def current_tenant(request: Request):
    raw = request.cookies.get("sd_session", "")
    if "|" not in raw:
        return None
    name, _ = raw.rsplit("|", 1)
    for code, tenant in TENANTS.items():
        if tenant == name and hmac.compare_digest(session_value(tenant, code), raw):
            return tenant
    return None


def tenant_dir(tenant: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", tenant.lower()).strip("-")
    d = DATA / slug
    d.mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------- style
STYLE = """
<style>
  :root { --fabric:#2e353b; --fabric-deep:#272d32; --panel:#3a4147; --panel-2:#444d54;
    --thread:#ece5d8; --thread-dim:#b9c0c5; --steel:#98a3ab; --accent:#ef7c1a; --accent-soft:#f5a15c;
    --stitch-rule: repeating-linear-gradient(90deg, var(--accent) 0 14px, transparent 14px 24px);
    --sans:"Avenir Next",Avenir,"Century Gothic",Futura,"Segoe UI",system-ui,sans-serif;
    --mono:ui-monospace,"SF Mono",Consolas,Menlo,monospace; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--fabric); color:var(--thread);
    font-family:-apple-system,"Segoe UI",system-ui,sans-serif; line-height:1.55; }
  .wrap { max-width:960px; margin:0 auto; padding:0 1.5rem 4rem; }
  header { border-bottom:1px solid #454e55; background:var(--fabric-deep); }
  .bar { max-width:960px; margin:0 auto; padding:.9rem 1.5rem; display:flex;
    justify-content:space-between; align-items:center; }
  .logo { font-family:var(--sans); font-weight:700; font-size:1.2rem; color:var(--thread);
    text-decoration:none; }
  .logo b { color:var(--accent); }
  .logo::after { content:""; display:block; height:3px; background:var(--stitch-rule); margin-top:2px; }
  .tenant { font-family:var(--mono); font-size:.78rem; color:var(--steel); }
  .tenant a { color:var(--accent-soft); }
  h1 { font-family:var(--sans); font-size:1.7rem; margin:2.2rem 0 .4rem; }
  h2 { font-family:var(--sans); font-size:1.15rem; margin:2rem 0 .8rem; }
  .muted { color:var(--steel); font-size:.92rem; }
  .card { background:var(--panel); padding:1.5rem; margin-top:1.4rem; }
  label { display:block; font-family:var(--mono); font-size:.75rem; letter-spacing:.15em;
    text-transform:uppercase; color:var(--steel); margin:1rem 0 .35rem; }
  input[type=text], input[type=password], input[type=number], input[type=file], select, textarea {
    width:100%; max-width:420px; background:var(--fabric-deep); color:var(--thread);
    border:1px solid var(--panel-2); padding:.65rem .8rem; font-size:1rem; font-family:inherit; }
  textarea { max-width:100%; min-height:4.5rem; }
  input:focus, select:focus, textarea:focus { outline:2px solid var(--accent); }
  .btn { font-family:var(--sans); font-weight:600; background:var(--accent); color:var(--fabric-deep);
    border:0; padding:.75rem 1.5rem; font-size:1rem; cursor:pointer; text-decoration:none;
    display:inline-block; margin-top:1.2rem; }
  .btn:hover { background:var(--accent-soft); }
  .btn.ghost { background:transparent; color:var(--thread); border:1px solid var(--panel-2); }
  .btn.ok { background:#3f9e63; color:#fff; }
  .btn.small { padding:.45rem .9rem; font-size:.9rem; }
  .stats { display:flex; gap:1.5rem; flex-wrap:wrap; margin:.8rem 0; font-family:var(--mono);
    font-size:.85rem; color:var(--thread-dim); }
  .stats b { color:var(--accent); font-size:1.15rem; display:block; }
  .compare { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
  @media (max-width:640px) { .compare { grid-template-columns:1fr; } }
  .compare figure { margin:0; }
  .compare figcaption { font-family:var(--mono); font-size:.72rem; letter-spacing:.12em;
    text-transform:uppercase; color:var(--steel); margin-bottom:.35rem; }
  img.preview { width:100%; background:var(--fabric-deep); padding:1rem; display:block; }
  img.art { background:#fff; }
  table { border-collapse:collapse; width:100%; margin-top:1rem; font-size:.92rem; }
  th { font-family:var(--mono); font-size:.7rem; letter-spacing:.12em; text-transform:uppercase;
    color:var(--steel); text-align:left; padding:.5rem .8rem .5rem 0;
    border-bottom:1px solid var(--panel-2); }
  td { padding:.55rem .8rem .55rem 0; border-bottom:1px solid #414a51; }
  td a { color:var(--accent-soft); }
  .pill { font-family:var(--mono); font-size:.72rem; padding:.15rem .55rem; }
  .pill.approved { background:#2e5b41; color:#c9f0d6; }
  .pill.rejected { background:#5b2e2e; color:#f0c9c9; }
  .pill.pending { background:var(--panel-2); color:var(--thread-dim); }
  .err { background:#5b2e2e; color:#f0c9c9; padding:.8rem 1rem; margin-top:1rem; }
  .warn { background:#5b4a2e; color:#f5e2c0; padding:.8rem 1rem; margin-top:1rem; }
  .inline { display:flex; gap:.6rem; align-items:end; flex-wrap:wrap; }
  .inline input { width:7rem; }
  details summary { cursor:pointer; }
</style>
"""


def page(body: str, tenant=None) -> HTMLResponse:
    who = (f'<span class="tenant">{esc(tenant)} &middot; <a href="/logout">log out</a></span>'
           if tenant else "")
    return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>StitchDraft Studio</title>{STYLE}</head><body>
<header><div class="bar"><a class="logo" href="/studio">Stitch<b>Draft</b> Studio</a>{who}</div></header>
<div class="wrap">{body}</div></body></html>""")


def error_page(msg: str, tenant, back="/studio") -> HTMLResponse:
    return page(f'<div class="err">{esc(msg)}</div>'
                f'<a class="btn ghost" href="{back}">Back</a>', tenant)


# ---------------------------------------------------------------- jobs store
def jobs_file(tenant) -> Path:
    return tenant_dir(tenant) / "jobs.json"


def load_jobs(tenant):
    f = jobs_file(tenant)
    return json.loads(f.read_text()) if f.exists() else []


def update_jobs(tenant, fn):
    """Read-modify-write jobs.json under a lock, written atomically (temp
    file + rename) so a crash mid-write can't corrupt the job history."""
    with JOBS_LOCK:
        jobs = load_jobs(tenant)
        result = fn(jobs)
        f = jobs_file(tenant)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs, indent=2))
        os.replace(tmp, f)
        return result


def get_job(tenant, job_id):
    return next((j for j in load_jobs(tenant) if j["id"] == job_id), None)


def job_threads(tenant, j):
    """Thread sequence for a job — stored since the engine reports it; for
    older jobs, recovered from the colour-separated SVG."""
    if j.get("threads"):
        return j["threads"]
    svg = tenant_dir(tenant) / j["id"] / "draft.svg"
    if svg.exists():
        return re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg.read_text())
    return []


# ---------------------------------------------------------------- engine
class EngineError(Exception):
    pass


def run_engine(src, jdir, width):
    return subprocess.run(
        [sys.executable, str(BASE / "engine" / "digitize_pro.py"),
         str(src), str(jdir / "draft.dst"), str(width)],
        capture_output=True, text=True, timeout=300, cwd=str(BASE / "engine"),
        env=ENGINE_ENV)


def rasterize_pdf(src, jdir):
    # 300 DPI keeps an A4 page around 2500px — plenty for contour
    # tracing, and half the memory of 600 DPI in every later stage
    r = subprocess.run(
        ["pdftocairo", "-png", "-transp", "-r", "300",
         "-singlefile", str(src), str(jdir / "input_pdf")],
        capture_output=True, text=True, timeout=120)
    out = jdir / "input_pdf.png"
    if r.returncode != 0 or not out.exists():
        raise EngineError("the PDF could not be read — try exporting it as PNG")
    return out


async def digitize_into(tenant, name, src, width):
    """Run the engine on src (already saved in its job folder) and record
    the job. Returns the job id; raises EngineError with a user message."""
    jdir = src.parent
    art = src
    try:
        # engine work (PDF rasterizing included — it's memory-hungry too)
        # is serialized and off the event loop so the site stays
        # responsive while a job stitches; the subprocess means a bad file
        # can't take the app down
        async with ENGINE_SEM:
            if src.suffix == ".pdf":
                if not shutil.which("pdftocairo"):
                    raise EngineError("PDF support is not enabled on this server — upload PNG or JPG")
                art = await asyncio.to_thread(rasterize_pdf, src, jdir)
            r = await asyncio.to_thread(run_engine, art, jdir, width)
    except subprocess.TimeoutExpired:
        raise EngineError("the engine timed out — the artwork may be too detailed or a photo")
    if r.returncode != 0 or not (jdir / "draft.dst").exists():
        last = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "engine error"
        raise EngineError(last)

    import pyembroidery as pe
    p = pe.read(str(jdir / "draft.dst"))
    n_st = sum(1 for s in p.stitches if s[2] == pe.STITCH)
    n_tr = sum(1 for s in p.stitches if s[2] == pe.TRIM)
    xs = [s[0] for s in p.stitches]; ys = [s[1] for s in p.stitches]
    out = r.stdout or ""
    threads = next((ln.split("THREADS", 1)[1].strip().split(",")
                    for ln in out.splitlines() if "THREADS" in ln), [])
    job = {"id": jdir.name, "name": name, "stitches": n_st,
           "colours": len(threads) or sum(1 for s in p.stitches if s[2] == pe.COLOR_CHANGE),
           "trims": n_tr,
           "size": f"{(max(xs)-min(xs))/10:.0f}×{(max(ys)-min(ys))/10:.0f}mm",
           "width_mm": width, "created": int(time.time()), "verdict": None,
           "input": art.name, "threads": threads,
           "warnings": "dropped" in out, "gradient": "GRADIENT:" in out}
    update_jobs(tenant, lambda jobs: jobs.append(job))
    return job["id"]


async def read_capped(upload: UploadFile, limit_mb=MAX_UPLOAD_MB):
    """Read an upload in chunks, giving up as soon as it passes the limit —
    never hold an oversized file in memory."""
    buf, limit = bytearray(), limit_mb * 1024 * 1024
    while chunk := await upload.read(1 << 20):
        buf += chunk
        if len(buf) > limit:
            return None
    return bytes(buf)


def new_job_dir(tenant) -> Path:
    jdir = tenant_dir(tenant) / uuid.uuid4().hex[:12]
    jdir.mkdir()
    return jdir


# ---------------------------------------------------------------- routes
@app.get("/", response_class=HTMLResponse)
def login_form(request: Request):
    if current_tenant(request):
        return RedirectResponse("/studio")
    return page("""
      <h1>Private beta</h1>
      <p class="muted">Enter the access code from your StitchDraft agreement.</p>
      <div class="card"><form method="post" action="/login">
        <label>Access code</label>
        <input type="password" name="code" autofocus autocomplete="off">
        <br><button class="btn">Enter the studio</button>
      </form></div>""")


@app.post("/login")
def login(code: str = Form(...)):
    code = code.strip().upper()
    tenant = TENANTS.get(code)
    if not tenant:
        time.sleep(1)  # slow brute force
        return error_page("Unknown access code. Check your agreement or contact "
                          "info@stitchdraft.co.uk.", None, back="/")
    resp = RedirectResponse("/studio", status_code=303)
    resp.set_cookie("sd_session", session_value(tenant, code), httponly=True,
                    secure=SECURE_COOKIES, max_age=60 * 60 * 24 * 14, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("sd_session")
    return resp


@app.get("/studio", response_class=HTMLResponse)
def studio(request: Request):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/")
    jobs = load_jobs(tenant)
    n = len(jobs)
    approved = sum(1 for j in jobs if j.get("verdict") == "approved")
    decided = sum(1 for j in jobs if j.get("verdict") in ("approved", "rejected"))
    rate = f"{100 * approved / decided:.0f}%" if decided else "—"
    reasons = {}
    for j in jobs:
        for r in j.get("reasons", []):
            reasons[r] = reasons.get(r, 0) + 1
    reason_line = ""
    if reasons:
        top = sorted(reasons.items(), key=lambda kv: -kv[1])
        reason_line = ('<p class="muted">Send-back reasons: ' + " &middot; ".join(
            f"{esc(REASONS.get(k, k))} <b>{v}</b>" for k, v in top) + "</p>")
    rows = "".join(
        f'<tr><td><a href="/job/{j["id"]}">{esc(j["name"])}</a>'
        f'{" ⚠" if j.get("gradient") else ""}</td>'
        f'<td>{datetime.fromtimestamp(j["created"], timezone.utc):%d %b}</td>'
        f'<td>{j["stitches"]:,}</td><td>{esc(j["size"])}</td>'
        f'<td><span class="pill {j.get("verdict") or "pending"}">{j.get("verdict") or "pending"}</span></td></tr>'
        for j in reversed(jobs))
    return page(f"""
      <h1>New job</h1>
      <p class="muted">Upload flat logo artwork (PNG, JPG, WEBP or vector PDF). The engine drafts a
      production .DST in your calibrated style — nothing is billed unless you approve it.</p>
      <div class="card"><form method="post" action="/digitize" enctype="multipart/form-data">
        <label>Artwork file</label>
        <input type="file" name="art" accept=".png,.jpg,.jpeg,.webp,.pdf" required>
        <label>Target width (mm)</label>
        <input type="number" name="width" value="100" min="20" max="300" step="1">
        <br><button class="btn">Digitize</button>
      </form></div>
      <h2>Jobs ({n}) &middot; acceptance rate {rate}</h2>
      {reason_line}
      <table><tr><th>Design</th><th>Date</th><th>Stitches</th><th>Size</th><th>Verdict</th></tr>{rows}</table>
      """, tenant)


@app.post("/digitize")
async def digitize_route(request: Request, art: UploadFile = File(...),
                         width: float = Form(100.0)):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/", status_code=303)
    ext = Path(art.filename or "art.png").suffix.lower()
    if ext not in ALLOWED_EXT:
        return error_page("Unsupported file type — send PNG, JPG, WEBP or PDF.", tenant)
    blob = await read_capped(art)
    if blob is None:
        return error_page(f"File too large (limit {MAX_UPLOAD_MB} MB).", tenant)

    jdir = new_job_dir(tenant)
    src = jdir / ("input" + ext)
    src.write_bytes(blob)
    name = re.sub(r"[^\w\- .]", "", Path(art.filename or "design").stem)[:48] or "design"
    width = max(20.0, min(300.0, float(width)))
    try:
        job_id = await digitize_into(tenant, name, src, width)
    except EngineError as e:
        shutil.rmtree(jdir, ignore_errors=True)
        return error_page(f"Could not digitize this artwork: {e}. Flat logo art works "
                          "best — photos and gradients need a human digitizer.", tenant)
    return RedirectResponse(f"/job/{job_id}", status_code=303)


@app.post("/job/{job_id}/resize")
async def resize_route(request: Request, job_id: str, width: float = Form(...)):
    """Re-digitize the same artwork at a new size — a new job, so the
    original draft and its verdict stay as they were."""
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/", status_code=303)
    j = get_job(tenant, job_id)
    if not j:
        return error_page("Job not found.", tenant)
    old = tenant_dir(tenant) / job_id
    src_old = next((p for p in old.glob("input.*")), None)
    if not src_old:
        return error_page("The original artwork for this job is no longer stored.", tenant)
    width = max(20.0, min(300.0, float(width)))
    jdir = new_job_dir(tenant)
    src = jdir / src_old.name
    shutil.copy(src_old, src)
    base = re.sub(r" @\d+mm$", "", j["name"])
    try:
        new_id = await digitize_into(tenant, f"{base} @{width:.0f}mm", src, width)
    except EngineError as e:
        shutil.rmtree(jdir, ignore_errors=True)
        return error_page(f"Could not digitize at {width:.0f}mm: {e}.", tenant,
                          back=f"/job/{job_id}")
    return RedirectResponse(f"/job/{new_id}", status_code=303)


def verdict_block(j) -> str:
    jid, verdict = j["id"], j.get("verdict")
    if verdict == "approved":
        return '<p><span class="pill approved">approved</span></p>'
    if verdict == "rejected":
        labels = ", ".join(esc(REASONS.get(r, r)) for r in j.get("reasons", [])) or "no reason given"
        note = f'<p class="muted">“{esc(j["note"])}”</p>' if j.get("note") else ""
        fix = (f'<p><a class="btn ghost small" href="/job/{jid}/corrected">Download the corrected file '
               f'you sent ({esc(j["corrected"])})</a></p>' if j.get("corrected") else "")
        return (f'<p><span class="pill rejected">sent back</span> '
                f'<span class="muted">{labels}</span></p>{note}{fix}')
    boxes = "".join(
        f'<label style="text-transform:none;letter-spacing:0;font-family:inherit;font-size:.95rem;'
        f'color:var(--thread);margin:.3rem 0"><input type="checkbox" name="reasons" value="{k}"> {v}</label>'
        for k, v in REASONS.items())
    return f"""
      <form method="post" action="/job/{jid}/verdict" style="display:inline">
        <button class="btn ok" name="v" value="approved">Approve for production</button>
      </form>
      <details class="card"><summary><b>Send back</b> — tell us what to fix</summary>
        <form method="post" action="/job/{jid}/verdict" enctype="multipart/form-data">
          <input type="hidden" name="v" value="rejected">
          <label>What was wrong? (tick all that apply)</label>{boxes}
          <label>Notes</label>
          <textarea name="note" placeholder="e.g. 4mm lettering needs to be satin, not fill"></textarea>
          <label>Your corrected file (optional — .DST/.EMB/.PES/PDF, max {MAX_UPLOAD_MB} MB)</label>
          <input type="file" name="corrected">
          <br><button class="btn ghost">Send back</button>
        </form>
      </details>"""


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/")
    j = get_job(tenant, job_id)
    if not j:
        return error_page("Job not found.", tenant)
    warn = ""
    if j.get("gradient"):
        warn += ('<div class="warn">⚠ This artwork has gradients, shading or photographic areas. '
                 'Embroidery sews flat colour, so this draft flattens them — treat it as a '
                 'starting point and route the job to a human digitizer.</div>')
    if j.get("warnings"):
        warn += ('<p class="muted">⚠ Some details were below the 1mm needle limit and were dropped — '
                 'consider a larger size or expert touch-up.</p>')
    name = esc(j["name"])
    return page(f"""
      <h1>{name}</h1>
      <div class="stats">
        <span><b>{j["stitches"]:,}</b>stitches</span>
        <span><b>{j["colours"]}</b>colours</span>
        <span><b>{j["trims"]}</b>trims</span>
        <span><b>{esc(j["size"])}</b>sewn size</span>
      </div>
      {warn}
      <div class="compare">
        <figure><figcaption>Your artwork</figcaption>
          <img class="preview art" src="/job/{job_id}/input" alt="Original artwork for {name}"></figure>
        <figure><figcaption>Sewn preview</figcaption>
          <img class="preview" src="/job/{job_id}/preview.png" alt="Sewn preview of {name}"></figure>
      </div>
      <div style="margin-top:1.4rem">
        <a class="btn" href="/job/{job_id}/draft.dst">Download .DST</a>
        <a class="btn" href="/job/{job_id}/draft.svg">Download .SVG</a>
        <a class="btn ghost" href="/job/{job_id}/worksheet" target="_blank">Production worksheet</a>
        <a class="btn ghost" href="/studio">New job</a>
      </div>
      <form class="inline" method="post" action="/job/{job_id}/resize">
        <div><label>Try another width (mm)</label>
        <input type="number" name="width" value="{j.get("width_mm", 100):.0f}" min="20" max="300" step="1"></div>
        <button class="btn ghost small">Re-digitize</button>
      </form>
      <h2>Verdict</h2>
      {verdict_block(j)}
      <p class="muted" style="margin-top:1.6rem">To edit in Wilcom: import the
      .SVG — the artwork pre-vectorized, colour-separated and at final size —
      and digitize native objects over it (clean first-generation .EMB, no
      stitch conversion). The .DST is the stitch-plan reference and the direct
      machine file for jobs that need no editing.</p>""", tenant)


@app.post("/job/{job_id}/verdict")
async def set_verdict(request: Request, job_id: str):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    v = form.get("v")
    if v not in ("approved", "rejected"):
        return RedirectResponse(f"/job/{job_id}", status_code=303)
    fields = {"verdict": v, "verdict_at": int(time.time())}
    if v == "rejected":
        fields["reasons"] = [r for r in form.getlist("reasons") if r in REASONS]
        fields["note"] = str(form.get("note") or "").strip()[:2000]
        up = form.get("corrected")
        if up is not None and getattr(up, "filename", ""):
            ext = Path(up.filename).suffix.lower()
            if ext not in CORRECTED_EXT:
                return error_page("Corrected file type not recognised — send .DST, .EMB, "
                                  ".PES, .EXP, .JEF, .VP3, PDF, PNG or JPG.", tenant,
                                  back=f"/job/{job_id}")
            blob = await read_capped(up)
            if blob is None:
                return error_page(f"Corrected file too large (limit {MAX_UPLOAD_MB} MB).",
                                  tenant, back=f"/job/{job_id}")
            (tenant_dir(tenant) / job_id / ("corrected" + ext)).write_bytes(blob)
            fields["corrected"] = re.sub(r"[^\w\- .]", "", up.filename)[:80] or "corrected" + ext

    def apply(jobs):
        for j in jobs:
            if j["id"] == job_id and not j.get("verdict"):
                j.update(fields)
    update_jobs(tenant, apply)
    return RedirectResponse(f"/job/{job_id}", status_code=303)


def job_file(request, job_id, filename):
    """Resolve a file inside the signed-in tenant's job folder, or None."""
    tenant = current_tenant(request)
    if not tenant:
        return None, None, None
    j = get_job(tenant, job_id)
    if not j:
        return tenant, None, None
    f = tenant_dir(tenant) / job_id / filename if filename else None
    return tenant, j, f


@app.get("/job/{job_id}/draft.dst")
def download_dst(request: Request, job_id: str):
    tenant, j, f = job_file(request, job_id, "draft.dst")
    if not j:
        return RedirectResponse("/")
    return FileResponse(f, filename=f"{j['name']}.dst", media_type="application/octet-stream")


@app.get("/job/{job_id}/draft.svg")
def download_svg(request: Request, job_id: str):
    tenant, j, f = job_file(request, job_id, "draft.svg")
    if not j:
        return RedirectResponse("/")
    if not f.exists():
        return RedirectResponse(f"/job/{job_id}")
    return FileResponse(f, filename=f"{j['name']}.svg", media_type="image/svg+xml")


@app.get("/job/{job_id}/preview.png")
def preview_png(request: Request, job_id: str):
    tenant, j, f = job_file(request, job_id, "draft_preview.png")
    if not j:
        return RedirectResponse("/")
    return FileResponse(f, media_type="image/png")


@app.get("/job/{job_id}/input")
def input_image(request: Request, job_id: str):
    tenant, j, _ = job_file(request, job_id, None)
    if not j:
        return RedirectResponse("/")
    jdir = tenant_dir(tenant) / job_id
    # the rasterized PDF if there is one (browsers can't <img> a PDF)
    f = jdir / j["input"] if j.get("input") else None
    if not f or not f.exists():
        f = next((p for p in [jdir / "input_pdf.png", *jdir.glob("input.*")]
                  if p.exists() and p.suffix != ".pdf"), None)
    if not f:
        return RedirectResponse(f"/job/{job_id}/preview.png")
    return FileResponse(f)


@app.get("/job/{job_id}/corrected")
def corrected_file(request: Request, job_id: str):
    tenant, j, _ = job_file(request, job_id, None)
    if not j or not j.get("corrected"):
        return RedirectResponse("/")
    f = next((tenant_dir(tenant) / job_id).glob("corrected.*"), None)
    if not f:
        return RedirectResponse(f"/job/{job_id}")
    return FileResponse(f, filename=j["corrected"], media_type="application/octet-stream")


@app.get("/job/{job_id}/worksheet", response_class=HTMLResponse)
def worksheet(request: Request, job_id: str):
    """Printable production worksheet — what an embroidery shop expects to
    travel with every file: size, counts, run time and the colour stops."""
    tenant, j, _ = job_file(request, job_id, None)
    if not j:
        return RedirectResponse("/")
    threads = job_threads(tenant, j)
    stops = "".join(
        f'<tr><td>{i}</td><td><span class="sw" style="background:{esc(c)}"></span></td>'
        f'<td class="mono">{esc(c.upper())}</td><td class="fill"></td><td class="fill"></td></tr>'
        for i, c in enumerate(threads, 1)) or \
        '<tr><td colspan="5">Colour sequence not recorded for this job.</td></tr>'
    changes = max(len(threads) - 1, 0)
    minutes = j["stitches"] / STITCHES_PER_MIN + changes * SECS_PER_COLOUR / 60
    made = datetime.fromtimestamp(j["created"], timezone.utc)
    name = esc(j["name"])
    return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Worksheet — {name}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family:-apple-system,"Segoe UI",system-ui,sans-serif; color:#1d2226;
    background:#fff; margin:0; padding:1.5rem; }}
  .sheet {{ max-width:190mm; margin:0 auto; }}
  h1 {{ font-size:1.4rem; margin:0 0 .2rem; }}
  .sub {{ color:#5b646b; font-size:.9rem; margin-bottom:1rem; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1.2rem; align-items:start; }}
  @media (max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} }}
  img {{ width:100%; border:1px solid #d5dadd; background:#2e353b; }}
  table {{ border-collapse:collapse; width:100%; font-size:.9rem; }}
  th, td {{ border:1px solid #c9cfd3; padding:.4rem .5rem; text-align:left; }}
  th {{ background:#f1f3f4; font-size:.75rem; text-transform:uppercase; letter-spacing:.06em; }}
  .kv td:first-child {{ color:#5b646b; width:45%; }}
  .mono {{ font-family:ui-monospace,Consolas,monospace; }}
  .sw {{ display:inline-block; width:1.6rem; height:1.1rem; border:1px solid #888; vertical-align:middle; }}
  td.fill {{ min-width:5rem; }}
  .foot {{ color:#5b646b; font-size:.78rem; margin-top:1rem; }}
  .print {{ margin:1rem 0; padding:.6rem 1.2rem; font-size:1rem; cursor:pointer; }}
  @media print {{ .print {{ display:none; }} body {{ padding:0; }} }}
</style></head><body><div class="sheet">
  <button class="print" onclick="window.print()">Print worksheet</button>
  <h1>{name}</h1>
  <div class="sub">{esc(tenant)} &middot; job {esc(job_id)} &middot; drafted {made:%d %b %Y}</div>
  <div class="grid">
    <img src="/job/{job_id}/preview.png" alt="Sewn preview">
    <table class="kv">
      <tr><td>Sewn size</td><td>{esc(j["size"])}</td></tr>
      <tr><td>Stitches</td><td>{j["stitches"]:,}</td></tr>
      <tr><td>Colours / stops</td><td>{len(threads) or j["colours"]}</td></tr>
      <tr><td>Trims</td><td>{j["trims"]}</td></tr>
      <tr><td>Est. run time</td><td>~{minutes:.0f} min per head
        <br><small>at {STITCHES_PER_MIN} spm + {SECS_PER_COLOUR}s per colour change</small></td></tr>
      <tr><td>File</td><td class="mono">{name}.dst</td></tr>
      <tr><td>Fabric / garment</td><td class="fill"></td></tr>
      <tr><td>Backing</td><td class="fill"></td></tr>
    </table>
  </div>
  <h2 style="font-size:1rem;margin:1.4rem 0 .5rem">Colour sequence</h2>
  <table><tr><th>Stop</th><th>Colour</th><th>Artwork colour</th><th>Thread brand &amp; code</th><th>Needle</th></tr>
  {stops}</table>
  <p class="foot">Artwork colours are taken from the supplied file — match each to your
  thread chart before running. {"⚠ Artwork contains gradients: this draft flattens them." if j.get("gradient") else ""}</p>
</div></body></html>""")
