import test from 'node:test';
import assert from 'node:assert/strict';
import { courseImageUrl } from '../src/safeUrls.ts';

test('observed Bilibili CDN images use HTTPS without changing path or signed query', () => {
  assert.equal(courseImageUrl('http://i2.hdslb.com/bfs/archive/observed.jpg?x=1'), 'https://i2.hdslb.com/bfs/archive/observed.jpg?x=1');
  assert.equal(courseImageUrl('https://i0.hdslb.com/bfs/archive/observed.jpg'), 'https://i0.hdslb.com/bfs/archive/observed.jpg');
});

test('unrecognized HTTP images fall back without weakening the HTTPS image policy', () => {
  assert.equal(courseImageUrl('http://images.example.org/cover.png'), undefined);
  assert.equal(courseImageUrl('http://i2.hdslb.com.evil.example/cover.png'), undefined);
  assert.equal(courseImageUrl('http://i2.hdslb.com:8080/cover.png'), undefined);
});

test('safe HTTPS image references remain unchanged', () => {
  assert.equal(courseImageUrl('https://images.example.org/cover.png?signature=observed'), 'https://images.example.org/cover.png?signature=observed');
});

test('image safety rejects private addresses, credentials, executable schemes and absent references', () => {
  for (const value of ['https://127.1/cover', 'https://user:pass@example.org/cover', 'javascript:alert(1)', null, undefined, '']) assert.equal(courseImageUrl(value), undefined);
});
