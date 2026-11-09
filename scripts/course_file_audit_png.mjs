/* Decode native RGB/RGBA PNG blocks in a JavaScript host. null requires the
 * existing full-image fallback; it never establishes image coverage. */
export function verifyNativePng(result, codec) {
  const images = (result?.content || []).filter(x => x.type === 'image');
  if (!images.length) return false;
  const allowed = new Set(['IHDR', 'IDAT', 'IEND', 'pHYs', 'sRGB', 'gAMA', 'cHRM']);
  const adler32 = bytes => {
    let a = 1, b = 0;
    for (let start = 0; start < bytes.length; start += 5552) {
      const end = Math.min(start + 5552, bytes.length);
      for (let i = start; i < end; i++) { a += bytes[i]; b += a; }
      a %= 65521; b %= 65521;
    }
    return ((b << 16) | a) >>> 0;
  };
  try {
    for (const image of images) {
      const encoded = image.data;
      if (image.mimeType !== 'image/png' || typeof encoded !== 'string' ||
          encoded.length > 24_000_000 || encoded.length % 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(encoded)) return null;
      const bytes = codec.fromBase64(encoded);
      if (!(bytes instanceof Uint8Array) || bytes.length < 57 || bytes.length > 18_000_000) return null;
      if (![137, 80, 78, 71, 13, 10, 26, 10].every((x, i) => bytes[i] === x)) return null;
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      const width = view.getUint32(16), height = view.getUint32(20);
      const channels = bytes[25] === 2 ? 3 : bytes[25] === 6 ? 4 : 0;
      if (!width || !height || width > 2401 || height > 2401 || bytes[24] !== 8 ||
          !channels || bytes[26] || bytes[27] || bytes[28]) return null;
      const parts = []; let compressedSize = 0, ended = false, chunks = 0, idatEnded = false;
      for (let offset = 8; offset < bytes.length;) {
        if (++chunks > 10000 || offset + 12 > bytes.length) return null;
        const length = view.getUint32(offset), end = offset + 12 + length;
        if (end > bytes.length) return null;
        const type = String.fromCharCode(...bytes.subarray(offset + 4, offset + 8));
        if (!allowed.has(type) || (offset === 8 && (type !== 'IHDR' || length !== 13)) ||
            (offset !== 8 && type === 'IHDR')) return null;
        if (type === 'IDAT') {
          if (idatEnded) return null;
          parts.push(bytes.subarray(offset + 8, offset + 8 + length)); compressedSize += length;
        } else if (parts.length) idatEnded = true;
        if (type === 'IEND') {
          if (length || end !== bytes.length) return null;
          ended = true; break;
        }
        offset = end;
      }
      if (!ended || compressedSize < 6) return null;
      const compressed = new Uint8Array(compressedSize); let cursor = 0;
      for (const part of parts) { compressed.set(part, cursor); cursor += part.length; }
      const rawSize = (width * channels + 1) * height;
      // A fixed output buffer prevents unbounded inflate allocation. The extra
      // byte makes an oversized decoded stream distinguishable from exact fit.
      const raw = codec.inflate(compressed, { out: new Uint8Array(rawSize + 1) });
      if (raw.length !== rawSize || adler32(raw) !== new DataView(compressed.buffer).getUint32(compressedSize - 4)) return null;
      const decoded = codec.decode(bytes, { checkCrc: true });
      if (decoded.width !== width || decoded.height !== height || decoded.depth !== 8 ||
          decoded.channels !== channels || decoded.data?.BYTES_PER_ELEMENT !== 1 ||
          decoded.data.length !== width * height * channels) return null;
    }
    return true;
  } catch { return null; }
}
