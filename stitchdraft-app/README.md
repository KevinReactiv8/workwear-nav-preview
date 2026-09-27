# StitchDraft Studio (private beta)

Hosted web app wrapping the digitizing engine: partners log in with an
access code, upload artwork, get a sewn preview + production .DST, and
record an approve/send-back verdict per job — which is the pilot's
acceptance-rate metric, shown live on the studio page.

The engine runs entirely server-side; licensees never receive code.
Each tenant's uploads, drafts and verdicts live in an isolated folder
under `data/<tenant>/`.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Log in with the demo code `DEMO-2026`.

## Access codes (tenants)

Codes are **never committed**. Set them in the `STITCHDRAFT_TENANTS`
environment variable (Render dashboard → Environment), either as JSON or
as a comma list:

```
STITCHDRAFT_TENANTS={"PILOT-XXXXXX": "Pilot Digitizer", "SHOP-YYYYYY": "Some Shop"}
STITCHDRAFT_TENANTS=PILOT-XXXXXX=Pilot Digitizer,SHOP-YYYYYY=Some Shop
```

For local development a gitignored `tenants.json` works too; with neither,
the demo code `DEMO-2026` is enabled. Sessions are tied to the code they
were made with — change a partner's code and their old logins stop working,
while their job history (keyed by partner name) is kept.

## Where jobs are stored

`STITCHDRAFT_DATA` (default `./data`) holds every tenant's uploads, drafts,
verdicts and corrected files. **It must be a persistent disk** — on
Render's free plan the filesystem is wiped on every deploy/restart. Use a
paid instance with a disk mounted at `/var/data` (see `render.yaml`).

## Deploy (pilot-grade)

Any small Linux host works (the engine is CPU-only):

1. Provision a VPS (1–2 vCPU is plenty) or a service like Render/Railway.
2. `git clone` this repo, `cd stitchdraft-app`, `pip install -r requirements.txt`.
3. Install poppler for PDF input: `apt install poppler-utils` (optional).
4. Set a stable secret: `export STITCHDRAFT_SECRET=<long random string>`,
   the access codes (`STITCHDRAFT_TENANTS`) and a persistent `STITCHDRAFT_DATA`.
5. Run behind HTTPS (Caddy makes this one line: `caddy reverse-proxy
   --from app.stitchdraft.co.uk --to localhost:8000`).
6. Point `app` subdomain DNS at the server.

## Notes

- Uploads limited to 15 MB; PNG/JPG/WEBP/PDF only. PDF input needs
  `pdftocairo` (poppler) on the host — without it PDF uploads are refused
  with a message.
- "Send back" records reasons, notes and an optional corrected file per
  job; the studio page tallies reasons. Artwork with gradients/photos is
  flagged on the job page and worksheet.
- Each job has a printable production worksheet (`/job/<id>/worksheet`).
- The engine runs in a subprocess with a 5-minute timeout so a bad file
  can't take the app down.
- `data/` holds customer artwork — back it up and keep it off any public
  bucket. It is the licensee's property (see the isolation guarantee).
