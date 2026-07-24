import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadFixtureProducts, getProducts } from '../src/deconetwork.js';
import { loadConfig } from '../src/config.js';

async function withFixture(data, fn) {
  const path = join(tmpdir(), `dn-fixture-${process.pid}-${data.__tag || 'x'}.json`);
  await writeFile(path, JSON.stringify(data), 'utf8');
  try {
    return await fn(path);
  } finally {
    await rm(path, { force: true });
  }
}

test('loadFixtureProducts reads a wrapped {products:[...]} body', async () => {
  const body = {
    __tag: 'wrapped',
    total: 1,
    products: [
      { product_id: 1, name: 'A', price: 5, url: 'u', image_url: 'i', currency: 'GBP' },
    ],
  };
  await withFixture(body, async (path) => {
    const config = loadConfig({ PRODUCT_SOURCE: 'fixture', FIXTURE_PATH: path });
    const products = await loadFixtureProducts(config);
    assert.equal(products.length, 1);
    assert.equal(products[0].id, '1');
    assert.equal(products[0].title, 'A');
  });
});

test('getProducts reads a bare array body via fixture source', async () => {
  const body = [
    { id: 'x1', name: 'One', price: 1, url: 'u', image_url: 'i' },
    { id: 'x2', name: 'Two', price: 2, url: 'u', image_url: 'i' },
  ];
  body.__tag = 'bare';
  await withFixture(body, async (path) => {
    const config = loadConfig({ PRODUCT_SOURCE: 'fixture', FIXTURE_PATH: path });
    const products = await getProducts(config);
    assert.equal(products.length, 2);
    assert.deepEqual(products.map((p) => p.id), ['x1', 'x2']);
  });
});

test('bundled sample fixture loads and normalizes cleanly', async () => {
  const config = loadConfig({
    PRODUCT_SOURCE: 'fixture',
    FIXTURE_PATH: new URL('../fixtures/deconetwork-products.sample.json', import.meta.url).pathname,
  });
  const products = await getProducts(config);
  assert.ok(products.length > 50);
  for (const p of products) {
    assert.ok(p.id, 'every product has an id');
    assert.ok(p.title, 'every product has a title');
    assert.ok(Number.isFinite(p.price), 'every product has a numeric price');
  }
});
