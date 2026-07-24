# DecoNetwork → Google Shopping Sync

Extracts your product catalogue from a **DecoNetwork** store and syncs it into
**Google Shopping** (Google Merchant Center) via the **Merchant API**. Built to
run unattended **every 24 hours** and to finish cleanly — bad individual
products are skipped, transient network errors are retried, and a missing
configuration causes a graceful skip rather than a crash.

---

## How it works

```
DecoNetwork API ──> normalize ──> validate ──> ┌─ Merchant API (productInputs:insert)
 (manage_products/find)                        └─ XML feed (RSS 2.0 + g: namespace)
```

1. **Extract** — pages through `POST /api/json/manage_products/find` (100/page,
   offset paging), authenticated with your DecoNetwork username + password.
2. **Normalize** — maps DecoNetwork's product fields into a stable internal
   shape, tolerant of field-name variations across accounts.
3. **Validate** — drops products missing required Google fields (id, title,
   description, link, image, price) with a warning; never fails the whole run
   for one bad product.
4. **Sync** — depending on `SYNC_MODE`:
   - `api` — upserts each product to Google via the Merchant API
     (`accounts.productInputs.insert`, prices as `amountMicros`).
   - `feed` — writes a Google Merchant Center XML feed to disk for a scheduled
     fetch data source to pull.
   - `both` — does both.

## Why it "runs every 24 hours with no errors"

- **Retries with backoff** on transient HTTP/network errors (429, 5xx,
  `ECONNRESET`, timeouts).
- **Per-product isolation** — one product failing to push doesn't stop the rest.
- **Validation** filters invalid products before they reach Google.
- **Graceful skip** — if credentials aren't configured yet, the run logs a
  warning and exits 0 (set `STRICT=true` to fail instead).
- **Systemic-failure detection** — if *every* product push fails (e.g. bad
  credentials), the run exits non-zero so you're alerted.
- **Tested** — `npm test` covers transform, feed, retry, config, and the full
  sync orchestration.

---

## Quick start (local)

```bash
cd deconetwork-google-sync
npm install

# Preview with bundled sample data — no credentials needed:
PRODUCT_SOURCE=fixture SYNC_MODE=both DRY_RUN=true npm run sync
cat output/google-shopping-feed.xml

# Run the tests:
npm test
```

Then copy `.env.example` to `.env`, fill in your credentials, and run
`npm run sync`.

---

## Configuration

All configuration is via environment variables (see `.env.example`).

| Variable | Required | Description |
|---|---|---|
| `DECONETWORK_API_BASE` | for live source | `https://<store>.deconetwork.com` |
| `DECONETWORK_USERNAME` | for live source | DecoNetwork account username |
| `DECONETWORK_PASSWORD` | for live source | DecoNetwork account password |
| `GOOGLE_MERCHANT_ID` | for `api` mode | Merchant Center account id |
| `GOOGLE_DATA_SOURCE_ID` | for `api` mode | API-type data source id |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | for `api` mode | Service-account key JSON (inline) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | alt. | Path to the key file instead of inline |
| `GOOGLE_FEED_LABEL` | | Target grouping, usually the country code (default `GB`) |
| `GOOGLE_CONTENT_LANGUAGE` | | Default `en` |
| `SYNC_MODE` | | `api` \| `feed` \| `both` (default `api`) |
| `DRY_RUN` | | `true` to skip writing to Google |
| `PRODUCT_SOURCE` | | `deconetwork` \| `fixture` |
| `CURRENCY` | | Default `GBP` |
| `STRICT` | | `true` to fail instead of skipping on problems |

### Getting the credentials

**DecoNetwork** — the Product Management API requires an Enterprise plan with
admin access. Use your account username and password. There is a live API
Console in the DecoNetwork admin that shows the exact request/response JSON.

**Google Merchant Center**
1. Create a **service account** in Google Cloud and download its JSON key.
2. In Merchant Center, add the service-account email as a user with product
   permissions.
3. Create an **API data source** (Data sources → Add → API) and note its id →
   `GOOGLE_DATA_SOURCE_ID`.
4. The API scope used is `https://www.googleapis.com/auth/content`.

---

## Scheduling (every 24 hours)

### Option A — GitHub Actions (included)

`.github/workflows/deconetwork-google-sync.yml` runs daily at 03:00 UTC and can
be triggered manually. Add the credentials as **repository secrets**
(`DECONETWORK_API_BASE`, `DECONETWORK_USERNAME`, `DECONETWORK_PASSWORD`,
`GOOGLE_MERCHANT_ID`, `GOOGLE_DATA_SOURCE_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`).
Until they're set, the job runs against the bundled sample data and stays green.

### Option B — cron on a server

```cron
0 3 * * * cd /path/to/deconetwork-google-sync && /usr/bin/node index.js >> sync.log 2>&1
```

---

## Notes on field mapping

DecoNetwork's exact product JSON keys vary and its full field reference is
gated. The normalizer therefore accepts many candidate names (e.g.
`product_id`/`sku`/`Product Code`, `name`/`Product Name`, `price`/`retail_price`,
`image_url`/`images[]`). If your account uses a key we don't recognise, add it
to the candidate lists in `src/transform.js` — the run is already validated to
catch anything that didn't map.
