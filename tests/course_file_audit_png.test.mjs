import test from 'node:test';
import assert from 'node:assert/strict';
import { deflateSync } from 'node:zlib';
import { decodeNativeImages, decodePngPixels } from '../scripts/audit-png-runtime/index.mjs';

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data = Buffer.alloc(0)) {
  const body = Buffer.concat([Buffer.from(type), data]);
  const size = Buffer.alloc(4), crc = Buffer.alloc(4);
  size.writeUInt32BE(data.length); crc.writeUInt32BE(crc32(body));
  return Buffer.concat([size, body, crc]);
}
function paeth(a, b, c) {
  const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}
function fixture(channels = 3, mutate = {}) {
  const width = 3, height = 5, stride = width * channels;
  const pixels = Buffer.from(Array.from({ length: stride * height }, (_, i) => (i * 47 + 19) % 256));
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = y;
    for (let x = 0; x < stride; x++) {
      const value = pixels[y * stride + x];
      const left = x >= channels ? pixels[y * stride + x - channels] : 0;
      const up = y ? pixels[(y - 1) * stride + x] : 0;
      const corner = y && x >= channels ? pixels[(y - 1) * stride + x - channels] : 0;
      raw[y * (stride + 1) + x + 1] = (value - [0, left, up, Math.floor((left + up) / 2), paeth(left, up, corner)][y]) & 255;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(mutate.width || width); header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = channels === 3 ? 2 : 6;
  if (mutate.filter) raw[0] = 5;
  const compressed = deflateSync(mutate.extra ? Buffer.concat([raw, Buffer.from([0])]) : raw);
  if (mutate.adler) compressed[compressed.length - 1] ^= 1;
  const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header),
    ...(mutate.metadata ? [chunk('tEXt', Buffer.from('Title\0Synthetic fixture'))] : []),
    chunk('IDAT', compressed), chunk('IEND')]);
  return { png, pixels };
}
const response = png => ({ content: [{ type: 'image', mimeType: 'image/png', data: png.toString('base64') }] });

for (const channels of [3, 4]) test(`real codec decodes every PNG row filter with ${channels} channels`, () => {
  const { png, pixels } = fixture(channels);
  assert.deepEqual(Buffer.from(decodePngPixels(png, { checkCrc: true }).data), pixels);
  assert.equal(decodeNativeImages(response(png)), true);
});
for (const [name, mutation] of Object.entries({ adler: { adler: true }, extra: { extra: true }, filter: { filter: true }, dimensions: { width: 2402 }, metadata: { metadata: true } })) {
  test(`${name} cannot establish fast-path coverage`, () => assert.equal(decodeNativeImages(response(fixture(3, mutation).png)), null));
}
test('bad chunk CRC and truncation require fallback, never successful coverage', () => {
  const { png } = fixture();
  const broken = Buffer.from(png); broken[broken.length - 1] ^= 1;
  assert.equal(decodeNativeImages(response(broken)), null);
  assert.equal(decodeNativeImages(response(png.subarray(0, -4))), null);
});
test('missing images and malformed base64 cannot count as a decoded page', () => {
  assert.equal(decodeNativeImages({ content: [] }), false);
  const raw = response(fixture().png); raw.content[0].data += '!';
  assert.equal(decodeNativeImages(raw), null);
});
test('every returned image block must decode', () => {
  const raw = response(fixture().png); raw.content.push({ type: 'image', mimeType: 'image/png', data: 'AAAA' });
  assert.equal(decodeNativeImages(raw), null);
});
