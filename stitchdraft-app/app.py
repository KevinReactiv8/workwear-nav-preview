"""
StitchDraft Studio — private-beta web app.

Upload artwork -> the engine digitizes it server-side -> sewn preview,
stitch stats, .DST download, and an approve/send-back verdict per job
(the pilot's acceptance-rate metric, captured from day one).

Tenancy: access codes in tenants.json map to isolated per-tenant job
folders. The engine code never leaves the server.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
sys.path.insert(0, str(BASE / "engine"))

SECRET = os.environ.get("STITCHDRAFT_SECRET") or (DATA / ".secret")
if isinstance(SECRET, Path):
    if not SECRET.exists():
        SECRET.write_text(secrets.token_hex(32))
    SECRET = SECRET.read_text().strip()

TENANTS_FILE = BASE / "tenants.json"
if not TENANTS_FILE.exists():
    TENANTS_FILE.write_text(json.dumps({"DEMO-2026": "Demo Shop"}, indent=2))
TENANTS = json.loads(TENANTS_FILE.read_text())

MAX_UPLOAD_MB = 15
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}

app = FastAPI(title="StitchDraft Studio")


# ---------------------------------------------------------------- auth
def sign(value: str) -> str:
    return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def current_tenant(request: Request):
    raw = request.cookies.get("sd_session", "")
    if "|" not in raw:
        return None
    name, sig = raw.rsplit("|", 1)
    if hmac.compare_digest(sign(name), sig) and name in TENANTS.values():
        return name
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
  input[type=text], input[type=password], input[type=number], input[type=file] {
    width:100%; max-width:420px; background:var(--fabric-deep); color:var(--thread);
    border:1px solid var(--panel-2); padding:.65rem .8rem; font-size:1rem; }
  input:focus { outline:2px solid var(--accent); }
  .btn { font-family:var(--sans); font-weight:600; background:var(--accent); color:var(--fabric-deep);
    border:0; padding:.75rem 1.5rem; font-size:1rem; cursor:pointer; text-decoration:none;
    display:inline-block; margin-top:1.2rem; }
  .btn:hover { background:var(--accent-soft); }
  .btn.ghost { background:transparent; color:var(--thread); border:1px solid var(--panel-2); }
  .btn.ok { background:#3f9e63; color:#fff; }
  .stats { display:flex; gap:1.5rem; flex-wrap:wrap; margin:.8rem 0; font-family:var(--mono);
    font-size:.85rem; color:var(--thread-dim); }
  .stats b { color:var(--accent); font-size:1.15rem; display:block; }
  img.preview { width:100%; background:var(--fabric-deep); padding:1rem; }
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
</style>
"""


def page(body: str, tenant=None) -> HTMLResponse:
    who = (f'<span class="tenant">{tenant} &middot; <a href="/logout">log out</a></span>'
           if tenant else "")
    return HTMLResponse(f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>StitchDraft Studio</title>{STYLE}</head><body>
<header><div class="bar"><a class="logo" href="/studio">Stitch<b>Draft</b> Studio</a>{who}</div></header>
<div class="wrap">{body}</div></body></html>""")


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
    tenant = TENANTS.get(code.strip().upper())
    if not tenant:
        time.sleep(1)  # slow brute force
        return page('<div class="err">Unknown access code. Check your agreement or contact info@stitchdraft.co.uk.</div>'
                    '<a class="btn ghost" href="/">Try again</a>')
    resp = RedirectResponse("/studio", status_code=303)
    resp.set_cookie("sd_session", f"{tenant}|{sign(tenant)}", httponly=True,
                    max_age=60 * 60 * 24 * 14, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("sd_session")
    return resp


def load_jobs(tenant):
    f = tenant_dir(tenant) / "jobs.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_jobs(tenant, jobs):
    (tenant_dir(tenant) / "jobs.json").write_text(json.dumps(jobs, indent=2))


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
    rows = "".join(
        f'<tr><td><a href="/job/{j["id"]}">{j["name"]}</a></td>'
        f'<td>{j["stitches"]:,}</td><td>{j["size"]}</td>'
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
      <table><tr><th>Design</th><th>Stitches</th><th>Size</th><th>Verdict</th></tr>{rows}</table>
      """, tenant)


@app.post("/digitize")
async def digitize_route(request: Request, art: UploadFile = File(...),
                         width: float = Form(100.0)):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/")
    ext = Path(art.filename or "art.png").suffix.lower()
    if ext not in ALLOWED_EXT:
        return page('<div class="err">Unsupported file type — send PNG, JPG, WEBP or PDF.</div>'
                    '<a class="btn ghost" href="/studio">Back</a>', tenant)
    blob = await art.read()
    if len(blob) > MAX_UPLOAD_MB * 1024 * 1024:
        return page(f'<div class="err">File too large (limit {MAX_UPLOAD_MB} MB).</div>'
                    '<a class="btn ghost" href="/studio">Back</a>', tenant)

    job_id = uuid.uuid4().hex[:12]
    jdir = tenant_dir(tenant) / job_id
    jdir.mkdir()
    src = jdir / ("input" + ext)
    src.write_bytes(blob)

    if ext == ".pdf":  # rasterize vector input at high resolution
        if not shutil.which("pdftocairo"):
            return page('<div class="err">PDF support is not enabled on this server — upload PNG or JPG.</div>'
                        '<a class="btn ghost" href="/studio">Back</a>', tenant)
        subprocess.run(["pdftocairo", "-png", "-transp", "-r", "600",
                        "-singlefile", str(src), str(jdir / "input_pdf")], check=True)
        src = jdir / "input_pdf.png"

    width = max(20.0, min(300.0, float(width)))
    try:
        # run the engine in a subprocess so a bad file can't take the app down
        r = subprocess.run(
            [sys.executable, str(BASE / "engine" / "digitize_pro.py"),
             str(src), str(jdir / "draft.dst"), str(width)],
            capture_output=True, text=True, timeout=300, cwd=str(BASE / "engine"))
        if r.returncode != 0 or not (jdir / "draft.dst").exists():
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "engine error")
    except Exception as e:
        return page(f'<div class="err">Could not digitize this artwork: {e}. '
                    'Flat logo art works best — photos and gradients need a human digitizer.</div>'
                    '<a class="btn ghost" href="/studio">Back</a>', tenant)

    import pyembroidery as pe
    p = pe.read(str(jdir / "draft.dst"))
    n_st = sum(1 for s in p.stitches if s[2] == pe.STITCH)
    n_cc = sum(1 for s in p.stitches if s[2] == pe.COLOR_CHANGE) + 1
    n_tr = sum(1 for s in p.stitches if s[2] == pe.TRIM)
    xs = [s[0] for s in p.stitches]; ys = [s[1] for s in p.stitches]
    size = f"{(max(xs)-min(xs))/10:.0f}×{(max(ys)-min(ys))/10:.0f}mm"

    name = re.sub(r"[^\w\- .]", "", Path(art.filename or "design").stem)[:48] or "design"
    jobs = load_jobs(tenant)
    jobs.append({"id": job_id, "name": name, "stitches": n_st, "colours": n_cc,
                 "trims": n_tr, "size": size, "width_mm": width,
                 "created": int(time.time()), "verdict": None,
                 "warnings": "dropped" in (r.stdout or "")})
    save_jobs(tenant, jobs)
    return RedirectResponse(f"/job/{job_id}", status_code=303)


def get_job(tenant, job_id):
    return next((j for j in load_jobs(tenant) if j["id"] == job_id), None)


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/")
    j = get_job(tenant, job_id)
    if not j:
        return page('<div class="err">Job not found.</div><a class="btn ghost" href="/studio">Back</a>', tenant)
    warn = ('<p class="muted">⚠ Some details were below the 1mm needle limit and were dropped — '
            'consider a larger size or expert touch-up.</p>' if j.get("warnings") else "")
    verdict = j.get("verdict")
    verdict_ui = (f'<span class="pill {verdict}">{verdict}</span>' if verdict else f"""
        <form method="post" action="/job/{job_id}/verdict" style="display:inline">
          <button class="btn ok" name="v" value="approved">Approve for production</button>
          <button class="btn ghost" name="v" value="rejected">Send back</button>
        </form>""")
    return page(f"""
      <h1>{j["name"]}</h1>
      <div class="stats">
        <span><b>{j["stitches"]:,}</b>stitches</span>
        <span><b>{j["colours"]}</b>colours</span>
        <span><b>{j["trims"]}</b>trims</span>
        <span><b>{j["size"]}</b>sewn size</span>
      </div>
      <img class="preview" src="/job/{job_id}/preview.png" alt="Sewn preview of {j['name']}">
      {warn}
      <div style="margin-top:1.4rem">
        <a class="btn" href="/job/{job_id}/draft.dst">Download .DST</a>
        {verdict_ui}
        <a class="btn ghost" href="/studio">New job</a>
      </div>""", tenant)


@app.post("/job/{job_id}/verdict")
def set_verdict(request: Request, job_id: str, v: str = Form(...)):
    tenant = current_tenant(request)
    if not tenant:
        return RedirectResponse("/")
    if v in ("approved", "rejected"):
        jobs = load_jobs(tenant)
        for j in jobs:
            if j["id"] == job_id and not j.get("verdict"):
                j["verdict"] = v
                j["verdict_at"] = int(time.time())
        save_jobs(tenant, jobs)
    return RedirectResponse(f"/job/{job_id}", status_code=303)


@app.get("/job/{job_id}/draft.dst")
def download_dst(request: Request, job_id: str):
    tenant = current_tenant(request)
    if not tenant or not get_job(tenant, job_id):
        return RedirectResponse("/")
    j = get_job(tenant, job_id)
    return FileResponse(tenant_dir(tenant) / job_id / "draft.dst",
                        filename=f"{j['name']}.dst", media_type="application/octet-stream")


@app.get("/job/{job_id}/preview.png")
def preview_png(request: Request, job_id: str):
    tenant = current_tenant(request)
    if not tenant or not get_job(tenant, job_id):
        return RedirectResponse("/")
    return FileResponse(tenant_dir(tenant) / job_id / "draft_preview.png",
                        media_type="image/png")
