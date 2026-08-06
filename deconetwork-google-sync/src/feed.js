// Generates a Google Merchant Center product feed (RSS 2.0 + g: namespace).
// This is the format Merchant Center fetches on a schedule, and doubles as a
// portable artifact when the Content API path is not configured.

function xmlEscape(value) {
  if (value === undefined || value === null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function tag(name, value) {
  if (value === undefined || value === null || value === '') return '';
  return `      <${name}>${xmlEscape(value)}</${name}>\n`;
}

function itemXml(p) {
  let out = '    <item>\n';
  out += tag('g:id', p.id);
  out += tag('g:title', p.title);
  out += tag('g:description', p.description || p.title);
  out += tag('g:link', p.link);
  out += tag('g:image_link', p.imageLink);
  for (const img of p.additionalImageLinks || []) {
    out += tag('g:additional_image_link', img);
  }
  out += tag('g:availability', p.availability);
  out += tag('g:condition', p.condition || 'new');
  if (p.price !== undefined && !Number.isNaN(p.price)) {
    out += tag('g:price', `${p.price.toFixed(2)} ${p.currency}`);
  }
  out += tag('g:brand', p.brand);
  out += tag('g:gtin', p.gtin);
  out += tag('g:mpn', p.mpn);
  out += tag('g:google_product_category', p.googleProductCategory);
  out += tag('g:product_type', p.productType);
  // Declare identifier absence explicitly when we have neither gtin nor mpn+brand.
  if (!p.gtin && !(p.mpn && p.brand)) {
    out += tag('g:identifier_exists', 'no');
  }
  out += '    </item>\n';
  return out;
}

/**
 * Build a complete Google Shopping XML feed string from normalized products.
 * @param {import('./transform.js').NormalizedProduct[]} products
 * @param {object} [meta]
 * @param {string} [meta.title]
 * @param {string} [meta.link]
 * @param {string} [meta.description]
 * @param {string} [meta.updated] ISO timestamp (injected to keep this pure/testable)
 */
export function buildFeed(products, meta = {}) {
  const title = meta.title || 'DecoNetwork Product Feed';
  const link = meta.link || 'https://www.deconetwork.com';
  const description = meta.description || 'Products synced from DecoNetwork to Google Shopping';

  let xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
  xml += '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">\n';
  xml += '  <channel>\n';
  xml += tag('title', title).replace(/^ {6}/, '    ');
  xml += tag('link', link).replace(/^ {6}/, '    ');
  xml += tag('description', description).replace(/^ {6}/, '    ');
  if (meta.updated) {
    xml += `    <lastBuildDate>${xmlEscape(meta.updated)}</lastBuildDate>\n`;
  }
  for (const p of products) {
    xml += itemXml(p);
  }
  xml += '  </channel>\n';
  xml += '</rss>\n';
  return xml;
}
