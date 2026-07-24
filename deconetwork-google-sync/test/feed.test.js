import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildFeed } from '../src/feed.js';

const sampleProduct = {
  id: 'RX101',
  title: 'Pro RTX Polo & Tee',
  description: 'A "great" polo <special>',
  link: 'https://shop.example.com/p/rx101?a=1&b=2',
  imageLink: 'https://shop.example.com/img/rx101.jpg',
  additionalImageLinks: ['https://shop.example.com/img/rx101b.jpg'],
  price: 9.99,
  currency: 'GBP',
  availability: 'in stock',
  condition: 'new',
  brand: 'Pro RTX',
  mpn: 'RX101',
  productType: 'Polo Shirts',
};

test('buildFeed produces a valid RSS feed with the g: namespace', () => {
  const xml = buildFeed([sampleProduct], { updated: '2026-07-24T00:00:00Z' });
  assert.ok(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>'));
  assert.ok(xml.includes('xmlns:g="http://base.google.com/ns/1.0"'));
  assert.ok(xml.includes('<g:id>RX101</g:id>'));
  assert.ok(xml.includes('<g:price>9.99 GBP</g:price>'));
  assert.ok(xml.includes('<g:availability>in stock</g:availability>'));
  assert.ok(xml.includes('<g:condition>new</g:condition>'));
  assert.ok(xml.includes('<g:additional_image_link>'));
  assert.ok(xml.includes('<lastBuildDate>2026-07-24T00:00:00Z</lastBuildDate>'));
});

test('buildFeed escapes special XML characters', () => {
  const xml = buildFeed([sampleProduct]);
  assert.ok(xml.includes('Pro RTX Polo &amp; Tee'));
  assert.ok(xml.includes('a=1&amp;b=2'));
  assert.ok(xml.includes('&quot;great&quot;'));
  assert.ok(xml.includes('&lt;special&gt;'));
  // Ensure no raw unescaped ampersand slipped through
  assert.equal(/&(?!amp;|lt;|gt;|quot;|apos;)/.test(xml), false);
});

test('buildFeed declares identifier_exists=no when no gtin/mpn+brand', () => {
  const noId = { ...sampleProduct, mpn: undefined, brand: undefined };
  const xml = buildFeed([noId]);
  assert.ok(xml.includes('<g:identifier_exists>no</g:identifier_exists>'));
});

test('buildFeed handles an empty product list', () => {
  const xml = buildFeed([]);
  assert.ok(xml.includes('<channel>'));
  assert.ok(!xml.includes('<item>'));
});
