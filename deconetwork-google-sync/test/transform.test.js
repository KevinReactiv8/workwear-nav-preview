import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeDecoNetworkProduct,
  validateNormalizedProduct,
  toMerchantProductInput,
  slugify,
  buildProductUrl,
} from '../src/transform.js';
import { loadConfig } from '../src/config.js';

const config = loadConfig({ CURRENCY: 'GBP', GOOGLE_FEED_LABEL: 'GB' });

test('normalizes a typical DecoNetwork product', () => {
  const raw = {
    product_id: 1001,
    sku: 'RX101',
    name: 'Pro RTX Piqué Polo Shirt',
    description: '<p>A <b>great</b> polo &amp; more.</p>',
    price: '9.99',
    currency: 'gbp',
    brand: 'Pro RTX',
    category: 'Polo Shirts',
    in_stock: true,
    url: 'https://shop.example.com/p/rx101',
    image_url: 'https://shop.example.com/img/rx101.jpg',
    images: ['https://shop.example.com/img/rx101.jpg', 'https://shop.example.com/img/rx101b.jpg'],
  };
  const p = normalizeDecoNetworkProduct(raw, config);
  assert.equal(p.id, '1001');
  assert.equal(p.title, 'Pro RTX Piqué Polo Shirt');
  assert.equal(p.description, 'A great polo & more.');
  assert.equal(p.price, 9.99);
  assert.equal(p.currency, 'GBP');
  assert.equal(p.availability, 'in stock');
  assert.equal(p.brand, 'Pro RTX');
  assert.equal(p.imageLink, 'https://shop.example.com/img/rx101.jpg');
  assert.deepEqual(p.additionalImageLinks, ['https://shop.example.com/img/rx101b.jpg']);
  assert.equal(p.productType, 'Polo Shirts');
});

test('handles alternate field names and out-of-stock', () => {
  const raw = {
    'Product ID': 55,
    'Product Code': 'ABC',
    'Product Name': 'Widget',
    retail_price: '£12.50',
    stock_status: 'Out of Stock',
    Supplier: 'Acme',
  };
  const p = normalizeDecoNetworkProduct(raw, config);
  assert.equal(p.id, '55');
  assert.equal(p.title, 'Widget');
  assert.equal(p.mpn, 'ABC');
  assert.equal(p.price, 12.5);
  assert.equal(p.availability, 'out of stock');
  assert.equal(p.brand, 'Acme');
});

test('validateNormalizedProduct reports missing required fields', () => {
  const p = normalizeDecoNetworkProduct({ name: 'No id no price' }, config);
  const problems = validateNormalizedProduct(p);
  assert.ok(problems.includes('missing id'));
  assert.ok(problems.includes('missing/invalid price'));
  assert.ok(problems.includes('missing link'));
  assert.ok(problems.includes('missing imageLink'));
});

test('toMerchantProductInput produces Merchant API v1 shape with amountMicros', () => {
  const raw = {
    sku: 'RX101',
    name: 'Polo',
    description: 'A polo',
    price: 9.99,
    brand: 'Pro RTX',
    url: 'https://shop.example.com/p/rx101',
    image_url: 'https://shop.example.com/img/rx101.jpg',
    in_stock: true,
  };
  const p = normalizeDecoNetworkProduct(raw, config);
  const input = toMerchantProductInput(p, config);
  assert.equal(input.offerId, 'RX101');
  assert.equal(input.contentLanguage, 'en');
  assert.equal(input.feedLabel, 'GB');
  const a = input.productAttributes;
  assert.equal(a.title, 'Polo');
  assert.equal(a.availability, 'IN_STOCK');
  assert.equal(a.condition, 'NEW');
  assert.equal(a.price.amountMicros, '9990000');
  assert.equal(a.price.currencyCode, 'GBP');
  assert.equal(a.brand, 'Pro RTX');
  // mpn(sku) + brand present -> identifierExists should not be forced false
  assert.equal(a.identifierExists, undefined);
});

test('declares identifierExists=false when no gtin and no mpn+brand', () => {
  const p = normalizeDecoNetworkProduct(
    { id: 'X', name: 'Nameless', price: 5, url: 'u', image_url: 'i' },
    { ...config, defaultBrand: '' }
  );
  // id maps to both id and mpn; but no brand -> identifierExists false
  p.brand = '';
  const input = toMerchantProductInput(p, config);
  assert.equal(input.productAttributes.identifierExists, false);
});

test('slugify matches DecoNetwork blank_product slugs (real examples)', () => {
  assert.equal(slugify('Roma Hoodie'), 'Roma-Hoodie');
  assert.equal(
    slugify('FW34 Steelite Lusum Safety Trainer S1P HRO Orange'),
    'FW34-Steelite-Lusum-Safety-Trainer-S1P-HRO-Orange'
  );
  // Apostrophe -> hyphen, trailing space -> trailing hyphen (no trimming).
  assert.equal(slugify("Women's"), 'Women-s');
  assert.equal(slugify('Polo Shirt '), 'Polo-Shirt-');
  assert.equal(
    slugify("POLLYFIELD Coolviz Ultra Women's Sleeved Polo Shirt "),
    'POLLYFIELD-Coolviz-Ultra-Women-s-Sleeved-Polo-Shirt-'
  );
});

test('constructs the real /blank_product/ URL when the API returns none', () => {
  const cfg = loadConfig({ DECONETWORK_API_BASE: 'https://www.workwear-direct.com' });

  const hoodie = normalizeDecoNetworkProduct(
    { product_id: 229073308, name: 'Roma Hoodie', price: 19.99, image_url: 'https://x/i.jpg' },
    cfg
  );
  assert.equal(
    hoodie.link,
    'https://www.workwear-direct.com/blank_product/229073308/Roma-Hoodie'
  );

  const trainer = normalizeDecoNetworkProduct(
    {
      product_id: 232992066,
      name: 'FW34 Steelite Lusum Safety Trainer S1P HRO Orange',
      price: 29.5,
      image_url: 'https://x/i.jpg',
    },
    cfg
  );
  assert.equal(
    trainer.link,
    'https://www.workwear-direct.com/blank_product/232992066/FW34-Steelite-Lusum-Safety-Trainer-S1P-HRO-Orange'
  );

  // Slug uses the raw (untrimmed) name, so a trailing space -> trailing hyphen,
  // and the apostrophe becomes a hyphen — matching the real store URL exactly.
  const polo = normalizeDecoNetworkProduct(
    {
      product_id: 242252641,
      name: "POLLYFIELD Coolviz Ultra Women's Sleeved Polo Shirt ",
      price: 8.5,
      image_url: 'https://x/i.jpg',
    },
    cfg
  );
  assert.equal(
    polo.link,
    'https://www.workwear-direct.com/blank_product/242252641/POLLYFIELD-Coolviz-Ultra-Women-s-Sleeved-Polo-Shirt-'
  );
  // ...but the Google title is the clean, trimmed name.
  assert.equal(polo.title, "POLLYFIELD Coolviz Ultra Women's Sleeved Polo Shirt");
});

test('prefers an API-provided URL over construction', () => {
  const cfg = loadConfig({ DECONETWORK_API_BASE: 'https://www.workwear-direct.com' });
  const p = normalizeDecoNetworkProduct(
    { product_id: 1, name: 'X', price: 1, url: 'https://custom/link', image_url: 'i' },
    cfg
  );
  assert.equal(p.link, 'https://custom/link');
});

test('buildProductUrl returns empty without base or id', () => {
  assert.equal(buildProductUrl('{base}/blank_product/{id}/{slug}', '', 5, 'X'), '');
  assert.equal(buildProductUrl('{base}/blank_product/{id}/{slug}', 'https://b', '', 'X'), '');
});

test('price micros rounds correctly', () => {
  const p = normalizeDecoNetworkProduct(
    { id: 'A', name: 'n', price: 0.1 + 0.2, url: 'u', image_url: 'i' },
    config
  );
  const input = toMerchantProductInput(p, config);
  // 0.30000000000000004 * 1e6 rounded
  assert.equal(input.productAttributes.price.amountMicros, '300000');
});
