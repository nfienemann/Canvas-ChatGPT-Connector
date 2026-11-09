import { decode } from 'fast-png';
import { unzlibSync } from 'fflate';
import { verifyNativePng } from '../course_file_audit_png.mjs';

export { decode as decodePngPixels };

export function decodeNativeImages(result) {
  return verifyNativePng(result, {
    decode,
    inflate: unzlibSync,
    fromBase64: value => typeof Uint8Array.fromBase64 === 'function'
      ? Uint8Array.fromBase64(value, { lastChunkHandling: 'strict' })
      : new Uint8Array(Buffer.from(value, 'base64')),
  });
}
