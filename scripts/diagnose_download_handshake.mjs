// Synthetic investigation only. No network, real files, credentials, or live host.
// Executes the unchanged shipped widget with the real pinned MCP Apps AppBridge.
import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { AppBridge } from "../ui/page-reader/node_modules/@modelcontextprotocol/ext-apps/dist/src/app-bridge.js";
import { build } from "../ui/page-reader/node_modules/esbuild/lib/main.js";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../ui/page-reader/", import.meta.url));
const bundle = await readFile(new URL("../src/canvas_bridge/assets/original-download.js", import.meta.url), "utf8");
const rebuilt = await build({
  absWorkingDir: root, entryPoints: ["download.js"], bundle: true, minify: true,
  format: "iife", target: "es2022", legalComments: "eof", write: false,
});
assert.equal(rebuilt.outputFiles[0].text, bundle, "Shipped bundle differs from source/pinned SDK");
console.log("PASS: shipped widget matches in-memory build; no asset written.");

async function probe(mode) {
  const supported = mode !== "absent";
  const elements = Object.fromEntries(
    ["title", "details", "download", "external", "fresh", "canvas", "status"].map(id => [id, {
      disabled: true, hidden: id === "external", textContent: "",
      addEventListener(event, fn) { this[event] = fn; },
    }]),
  );
  const bytes = Buffer.from("Synthetic original file\n");
  const data = {
    delivery_id: "synthetic-delivery", file_id: "synthetic-file",
    course_name: "Synthetic course", filename: "synthetic.txt",
    byte_size: bytes.length, bytes_sha256: createHash("sha256").update(bytes).digest("hex"),
    source_url: "https://canvas.fixture.invalid/file",
  };
  const external = "https://delivery.fixture.invalid/synthetic-capability";
  const resource = mode === "linked"
    ? { type: "resource_link", uri: external, name: data.filename, mimeType: "text/plain", size: bytes.length }
    : { type: "resource", resource: { uri: "canvas-file://delivery/synthetic/synthetic.txt", mimeType: "text/plain", blob: bytes.toString("base64") } };
  const calls = [], downloads = [], links = [], wire = [];
  const listeners = new Set();
  let transport;
  const parent = { postMessage(message) {
    wire.push(message);
    queueMicrotask(() => transport.onmessage?.(message));
  } };
  const window = {
    parent, innerWidth: 640,
    addEventListener(name, fn) { if (name === "message") listeners.add(fn); },
    removeEventListener(name, fn) { if (name === "message") listeners.delete(fn); },
  };
  transport = {
    async start() {}, async close() {},
    async send(message) {
      queueMicrotask(() => {
        for (const fn of listeners) fn({ data: message, source: parent, origin: "https://host.fixture.invalid" });
      });
    },
  };
  const host = new AppBridge(null, { name: "Synthetic diagnostic host", version: "1.0.0" }, {
    serverTools: {}, openLinks: {}, ...(supported ? { downloadFile: {} } : {}),
  });
  host.oncalltool = async params => {
    calls.push(params);
    assert.equal(params.name, "get_course_file_download_payload");
    return { content: [], structuredContent: { status: "ok", data },
      _meta: { canvas_bridge_download: { resource, external_url: external } } };
  };
  host.onopenlink = async params => { links.push(params); return {}; };
  if (supported) host.ondownloadfile = async params => {
    downloads.push(params);
    if (mode === "linked") assert.equal(params.contents[0].uri, external);
    else assert.deepEqual(Buffer.from(params.contents[0].resource.blob, "base64"), bytes);
    return mode === "rejected" ? { isError: true } : {};
  };
  let initialized;
  const ready = new Promise(resolve => { initialized = resolve; });
  host.oninitialized = async () => {
    await host.sendToolInput({ arguments: { connection_id: "synthetic-owner", file_id: data.file_id } });
    await host.sendToolResult({ content: [], structuredContent: { status: "ok", data } });
    initialized();
  };
  await host.connect(transport);
  const document = {
    getElementById: id => elements[id], body: {},
    documentElement: { style: {}, getBoundingClientRect: () => ({ height: 200 }) },
  };
  vm.runInNewContext(bundle, {
    window, document, console: { ...console, debug() {} }, crypto: webcrypto, Uint8Array, atob,
    URL, URLSearchParams, TextEncoder, TextDecoder, AbortController,
    setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
    requestAnimationFrame: fn => { queueMicrotask(fn); return 1; },
    ResizeObserver: class { observe() {} disconnect() {} },
  }, { filename: "unchanged-original-download.js" });
  let timer;
  try {
    await Promise.race([ready, new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error("Synthetic handshake timed out")), 3000);
    })]);
  } finally { clearTimeout(timer); }
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements.download.disabled, false);
  assert.equal(calls.length, 0);
  assert.equal(downloads.length, 0);
  assert.equal(links.length, 0);
  const init = wire.find(message => message.method === "ui/initialize");
  assert.ok(init);
  assert.deepEqual(JSON.parse(JSON.stringify(init.params.appCapabilities)), {});
  await elements.download.click();
  if (!supported) {
    assert.equal(calls.length, 0);
    assert.equal(downloads.length, 0);
    assert.equal(wire.some(message => message.method === "ui/download-file"), false);
    assert.equal(elements.external.hidden, false);
    assert.match(elements.status.textContent, /This client does not offer an in-chat download/);
    await elements.external.click();
    assert.equal(calls.length, 1);
    assert.equal(links.length, 1);
    assert.equal(links[0].url, external);
  } else {
    assert.equal(calls.length, 1);
    assert.equal(downloads.length, 1);
    assert.equal(links.length, 0);
    assert.ok(wire.some(message => message.method === "ui/download-file"));
    assert.match(elements.status.textContent, mode === "rejected" ? /not completed/ : /request accepted by the host/);
  }
  console.log(JSON.stringify({ mode, protocol: init.params.protocolVersion,
    payloadCalls: calls.length, hostDownloadCalls: downloads.length, externalCalls: links.length,
    result: "PASS; synthetic host only" }));
  await host.close();
}

for (const mode of ["absent", "embedded", "linked", "rejected"]) await probe(mode);
