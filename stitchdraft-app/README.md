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

## Tenants

Edit `tenants.json` — one access code per partner:

```json
{
  "DEMO-2026": "Demo Shop",
  "XXXX-XXXX": "Partner Name"
}
```

Restart the app after editing. Give each partner their own code so their
jobs stay in their own tenant folder.

## Deploy (pilot-grade)

Any small Linux host works (the engine is CPU-only):

1. Provision a VPS (1–2 vCPU is plenty) or a service like Render/Railway.
2. `git clone` this repo, `cd stitchdraft-app`, `pip install -r requirements.txt`.
3. Install poppler for PDF input: `apt install poppler-utils` (optional).
4. Set a stable secret: `export STITCHDRAFT_SECRET=<long random string>`.
5. Run behind HTTPS (Caddy makes this one line: `caddy reverse-proxy
   --from app.stitchdraft.co.uk --to localhost:8000`).
6. Point `app` subdomain DNS at the server.

## Notes

- Uploads limited to 15 MB; PNG/JPG/WEBP/PDF only.
- The engine runs in a subprocess with a 5-minute timeout so a bad file
  can't take the app down.
- `data/` holds customer artwork — back it up and keep it off any public
  bucket. It is the licensee's property (see the isolation guarantee).
