// Transforms between three shapes:
//   raw DecoNetwork product  ->  normalized product  ->  Google product resource
//
// The normalized product is our stable internal contract. It insulates the
// Google side from DecoNetwork field-naming quirks and vice-versa.

/** @typedef {Object} NormalizedProduct
 * @property {string} id
 * @property {string} title
 * @property {string} description
 * @property {string} link
 * @property {string} imageLink
 * @property {string[]} additionalImageLinks
 * @property {number} price
 * @property {string} currency
 * @property {string} availability  'in stock' | 'out of stock' | 'preorder'
 * @property {string} condition
 * @property {string} brand
 * @property {string} [gtin]
 * @property {string} [mpn]
 * @property {string} [googleProductCategory]
 * @property {string} [productType]
 */

// Pull the first defined, non-empty value from a list of candidate keys.
function pick(obj, keys) {
  for (const key of keys) {
    const value = getPath(obj, key);
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return undefined;
}

// Supports dotted paths like "prices.retail".
function getPath(obj, path) {
  return path.split('.').reduce((acc, part) => (acc == null ? acc : acc[part]), obj);
}

function toNumber(value) {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  // strip currency symbols / thousands separators
  const cleaned = String(value).replace(/[^0-9.\-]/g, '');
  const n = Number.parseFloat(cleaned);
  return Number.isFinite(n) ? n : undefined;
}

function firstArray(...candidates) {
  for (const c of candidates) {
    if (Array.isArray(c) && c.length) return c;
  }
  return [];
}

function normalizeAvailability(raw) {
  if (raw === undefined || raw === null) return 'in stock';
  if (typeof raw === 'boolean') return raw ? 'in stock' : 'out of stock';
  const s = String(raw).toLowerCase();
  if (/(out.?of.?stock|unavailable|sold.?out|discontinued|inactive|0)/.test(s)) return 'out of stock';
  if (/(preorder|pre-order|backorder)/.test(s)) return 'preorder';
  return 'in stock';
}

// Extract an image URL from a value that may be a string, {url}, {src}, etc.
function imageUrl(value) {
  if (!value) return undefined;
  if (typeof value === 'string') return value;
  return pick(value, ['url', 'src', 'link', 'image', 'href', 'large', 'original']);
}

/**
 * Map a raw DecoNetwork product object into the normalized shape.
 * Tolerant of field-name variation across DecoNetwork API versions.
 * @param {object} raw
 * @param {import('./config.js').loadConfig extends any ? any : any} config
 * @returns {NormalizedProduct}
 */
export function normalizeDecoNetworkProduct(raw, config) {
  const id = String(
    pick(raw, [
      'id', 'product_id', 'productId', 'ProductID', 'Product ID',
      'sku', 'code', 'product_code', 'productCode', 'Product Code',
    ]) ?? ''
  ).trim();

  // Keep the raw name for URL slugging (DecoNetwork slugs the stored name
  // verbatim, incl. trailing spaces); use the trimmed name as the Google title.
  const rawTitle = String(
    pick(raw, [
      'name', 'title', 'product_name', 'productName', 'Product Name', 'item_name',
    ]) ?? ''
  );
  const title = rawTitle.trim();

  const descriptionRaw = pick(raw, [
    'description', 'long_description', 'short_description', 'summary', 'details',
  ]);
  const description = stripHtml(String(descriptionRaw ?? title)).trim();

  // Prefer a URL the API hands back; otherwise construct DecoNetwork's
  // non-standard /blank_product/<id>/<slug> product URL from the id + name.
  const numericId = pick(raw, [
    'product_id', 'productId', 'ProductID', 'Product ID', 'id',
  ]);
  let link = String(
    pick(raw, ['url', 'link', 'product_url', 'productUrl', 'permalink', 'store_url']) ?? ''
  ).trim();
  if (!link) {
    link = buildProductUrl(
      config.deconetwork?.productUrlPattern,
      config.deconetwork?.baseUrl,
      numericId,
      rawTitle
    );
  }

  const imagesArr = firstArray(
    raw.images, raw.image_urls, raw.imageUrls, raw.media, raw.photos
  ).map(imageUrl).filter(Boolean);

  const singleImage = imageUrl(
    pick(raw, ['image', 'image_url', 'imageUrl', 'thumbnail', 'main_image', 'primary_image'])
  );
  const allImages = [...new Set([singleImage, ...imagesArr].filter(Boolean))];

  const price = toNumber(
    pick(raw, [
      'price', 'retail_price', 'retailPrice', 'base_price', 'basePrice',
      'sale_price', 'prices.retail', 'prices.base', 'default_price',
    ])
  );

  const currency = String(
    pick(raw, ['currency', 'currency_code', 'currencyCode']) ?? config.currency
  ).toUpperCase();

  const availability = normalizeAvailability(
    pick(raw, ['availability', 'in_stock', 'inStock', 'stock_status', 'status', 'active'])
  );

  const brand = String(
    pick(raw, ['brand', 'manufacturer', 'vendor', 'supplier', 'Supplier']) ?? config.defaultBrand ?? ''
  ).trim();

  const gtin = pick(raw, ['gtin', 'barcode', 'ean', 'upc']);
  const mpn = pick(raw, ['mpn', 'sku', 'code', 'product_code', 'productCode', 'Product Code', 'manufacturer_code']);

  const productType = normalizeCategory(
    pick(raw, ['category', 'categories', 'category_path', 'product_type', 'productType'])
  );

  const modifiedAt = pick(raw, [
    'date_modified', 'dateModified', 'Date Modified', 'modified', 'modified_at',
    'modifiedAt', 'updated_at', 'updatedAt', 'last_modified', 'lastModified',
  ]);

  return {
    id,
    title,
    description,
    link,
    imageLink: allImages[0] || '',
    additionalImageLinks: allImages.slice(1, 11), // Google allows up to 10 extra
    price,
    currency,
    availability,
    condition: config.defaultCondition || 'new',
    brand,
    gtin: gtin ? String(gtin).trim() : undefined,
    mpn: mpn ? String(mpn).trim() : undefined,
    googleProductCategory: mapGoogleCategory(
      `${productType || ''} ${title}`,
      config.google?.categoryMap,
      config.google?.defaultProductCategory
    ),
    productType,
    modifiedAt: modifiedAt ? String(modifiedAt) : undefined,
  };
}

/**
 * Choose a Google product-category path for a product by matching its
 * category/title text against a rules list (first keyword hit wins). Falls
 * back to `fallback` when nothing matches or no map is provided.
 * @param {string} text
 * @param {{rules?: Array<{keywords: string[], category: string}>}} [map]
 * @param {string} [fallback]
 */
export function mapGoogleCategory(text, map, fallback) {
  const rules = map?.rules;
  if (!Array.isArray(rules) || !rules.length) return fallback;
  const haystack = String(text || '').toLowerCase();
  for (const rule of rules) {
    if (!rule || !Array.isArray(rule.keywords)) continue;
    if (rule.keywords.some((kw) => kw && haystack.includes(String(kw).toLowerCase()))) {
      return rule.category;
    }
  }
  return fallback;
}

function normalizeCategory(value) {
  if (!value) return undefined;
  if (Array.isArray(value)) {
    return value
      .map((v) => (typeof v === 'string' ? v : pick(v, ['name', 'title', 'label'])))
      .filter(Boolean)
      .join(' > ');
  }
  if (typeof value === 'object') return pick(value, ['name', 'title', 'label']);
  return String(value);
}

// Slugify a product name the way DecoNetwork builds its /blank_product/ URLs.
// Reverse-engineered from real store URLs: every non-alphanumeric character
// (spaces, apostrophes, punctuation) becomes a single hyphen, with NO trimming
// of leading/trailing hyphens and NO collapsing of runs — i.e. the classic
// PHP `preg_replace('/[^a-zA-Z0-9]/', '-', $name)`. Verified against:
//   "Roma Hoodie" -> "Roma-Hoodie"
//   "FW34 Steelite Lusum Safety Trainer S1P HRO Orange"
//        -> "FW34-Steelite-Lusum-Safety-Trainer-S1P-HRO-Orange"
//   "POLLYFIELD Coolviz Ultra Women's Sleeved Polo Shirt "  (trailing space)
//        -> "POLLYFIELD-Coolviz-Ultra-Women-s-Sleeved-Polo-Shirt-"
// Note: this ASCII rule maps accented letters to hyphens too (unverified — no
// accented example seen). The slug is cosmetic: DecoNetwork resolves the page
// by the numeric id, so a near-miss still redirects to the canonical page.
export function slugify(name) {
  return String(name || '').replace(/[^A-Za-z0-9]/g, '-');
}

// Build a DecoNetwork product URL from a pattern with {base} {id} {slug}.
// Returns '' when we lack the base URL or a product id.
export function buildProductUrl(pattern, base, id, title) {
  if (!pattern || !base || id === undefined || id === null || id === '') return '';
  return pattern
    .replace('{base}', String(base).replace(/\/+$/, ''))
    .replace('{id}', String(id))
    .replace('{slug}', slugify(title));
}

function stripHtml(s) {
  return s
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ');
}

/**
 * Validate a normalized product against Google Shopping's minimum required
 * fields. Returns an array of problem strings (empty = valid).
 */
export function validateNormalizedProduct(p) {
  const problems = [];
  if (!p.id) problems.push('missing id');
  if (!p.title) problems.push('missing title');
  if (!p.description) problems.push('missing description');
  if (!p.link) problems.push('missing link');
  if (!p.imageLink) problems.push('missing imageLink');
  if (p.price === undefined || Number.isNaN(p.price)) problems.push('missing/invalid price');
  if (!p.currency) problems.push('missing currency');
  return problems;
}

// Google Merchant API availability/condition are UPPER_SNAKE enums.
const AVAILABILITY_ENUM = {
  'in stock': 'IN_STOCK',
  'out of stock': 'OUT_OF_STOCK',
  preorder: 'PREORDER',
  backorder: 'BACKORDER',
};
const CONDITION_ENUM = { new: 'NEW', refurbished: 'REFURBISHED', used: 'USED' };

/**
 * Map a normalized product into a Google Merchant API v1 `productInput`
 * (the body of accounts.productInputs.insert). Prices use `amountMicros`
 * (millionths of a currency unit) per the Merchant API spec.
 */
export function toMerchantProductInput(p, config) {
  const attributes = {
    title: truncate(p.title, 150),
    description: truncate(p.description || p.title, 5000),
    link: p.link,
    imageLink: p.imageLink,
    availability: AVAILABILITY_ENUM[p.availability] || 'IN_STOCK',
    condition: CONDITION_ENUM[(p.condition || 'new').toLowerCase()] || 'NEW',
    price: {
      amountMicros: String(Math.round(p.price * 1_000_000)),
      currencyCode: p.currency,
    },
  };

  if (p.additionalImageLinks?.length) attributes.additionalImageLinks = p.additionalImageLinks;
  if (p.brand) attributes.brand = p.brand;
  if (p.gtin) attributes.gtin = [p.gtin]; // repeated string in v1
  if (p.mpn) attributes.mpn = p.mpn;
  if (p.googleProductCategory) attributes.googleProductCategory = p.googleProductCategory;
  if (p.productType) attributes.productTypes = [p.productType];

  // Declare identifier absence explicitly when we have neither gtin nor mpn+brand.
  if (!p.gtin && !(p.mpn && p.brand)) {
    attributes.identifierExists = false;
  }

  return {
    offerId: p.id,
    contentLanguage: config.google.contentLanguage,
    feedLabel: config.google.feedLabel,
    productAttributes: attributes,
  };
}

function truncate(s, max) {
  if (!s) return s;
  return s.length > max ? s.slice(0, max - 1).trimEnd() + '…' : s;
}
