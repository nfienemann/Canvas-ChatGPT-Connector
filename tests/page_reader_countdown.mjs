import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const source = readFileSync("ui/page-reader/reader.js", "utf8").split("\n").slice(1).join("\n");
const bytes = Buffer.from("synthetic-authorized-image");
const png = bytes.toString("base64");
const hash = createHash("sha256").update(bytes).digest("hex");
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; }

async function mount(options = {}) {
  let now = 0, nextTimer = 0, observer, app;
  const timers = new Map(), windowEvents = {}, documentEvents = {};
  const elements = {};
  for (const id of ["status", "read", "title", "page", "description", "notice", "cancel", "actions", "countdown-note"]) {
    elements[id] = {id, disabled: true, hidden: true, complete: options.loaded !== false,
      naturalWidth: options.loaded === false ? 0 : 1,
      addEventListener(event, fn) { this[event] = fn; }};
  }
  const result = {status: "ok", data: {format: options.format || "pdf", page: 1, page_count: 3,
    render_receipt: "synthetic-receipt", content_hash: "a".repeat(64), image_hash: hash,
    rotation: 0, resolution: "standard", source_version: "v1"}, sources: [{locator: "PDF page 1"}]};
  if (options.format === "pptx") {
    Object.assign(result.data, {page: 2, source_slide: 2, source_locator: "Slide 2", source_content_hash: "a".repeat(64)});
    result.sources = [{locator: "Slide 2"}];
  }
  let response = {structuredContent: result, _meta: {canvas_bridge_page: {png}}};
  const calls = [], contexts = [], messages = [], uploads = [], states = [];
  const api = {
    toolInput: {connection_id: "synthetic-owner", file_id: "synthetic-file"},
    toolResponseMetadata: {mcp_tool_result: response},
    widgetState: options.saved || {privateContent: {unrelated: "preserved"}},
    setWidgetState(state) { if (options.stateFails) throw Error("state unavailable"); states.push(structuredClone(state)); this.widgetState = state; },
    async uploadFile(file, args) {uploads.push({file, args}); return {fileId: "synthetic-owned-upload"};},
    async sendFollowUpMessage(value) {messages.push(value);},
  };
  if (options.noState) delete api.setWidgetState;
  const doc = {visibilityState: "visible", getElementById: id => elements[id],
    addEventListener: (event, fn) => {documentEvents[event] = fn;}};
  class App {
    constructor() {app = this;}
    getHostCapabilities() {return options.unsupported ? {} : {serverTools: {}, message: {text: {}}, updateModelContext: options.fallback ? {} : {image: {}}};}
    async connect() {this.ontoolinput({arguments: api.toolInput}); this.ontoolresult(response);}
    async callServerTool(request) {
      calls.push(structuredClone(request));
      if (options.refreshGate) await options.refreshGate.promise;
      if (options.denied) return {structuredContent: {status: "permission_denied"}};
      if (options.changed) return {structuredContent: {...result, data: {...result.data, content_hash: "b".repeat(64)}}};
      return options.refreshResponse || response;
    }
    async updateModelContext(value) {contexts.push(structuredClone(value));}
    async sendMessage(value) {messages.push(structuredClone(value)); return {isError: !!options.messageFails};}
  }
  class IntersectionObserver {
    constructor(callback) {observer = callback;}
    observe() {}
  }
  const win = {openai: api, addEventListener: (event, fn) => {windowEvents[event] = fn;}};
  vm.runInNewContext(source, {App, window: win, document: doc, IntersectionObserver,
    Uint8Array, File, atob, Error, performance: {now: () => now},
    crypto: {subtle: {async digest(_, value) {
      if(options.digestGate) await options.digestGate.promise;
      return Uint8Array.from(createHash("sha256").update(value).digest()).buffer;
    }}},
    setInterval: fn => {timers.set(++nextTimer, fn); return nextTimer;},
    clearInterval: id => timers.delete(id),
  });
  await flush();
  const visible = (value = true) => observer([
    {target: elements.page, isIntersecting: value, intersectionRatio: value ? 1 : 0},
    {target: elements.actions, isIntersecting: value, intersectionRatio: value ? 1 : 0},
  ]);
  visible(options.visible !== false);
  return {elements, api, calls, contexts, messages, uploads, states, result, timers,
    async advance(ms, step = 250) {while(ms > 0) {const elapsed = Math.min(ms, step); now += elapsed; ms -= elapsed; for (const fn of [...timers.values()]) fn(); await flush();}},
    visible,
    visibility(value) {doc.visibilityState = value; documentEvents.visibilitychange();},
    globals() {windowEvents["openai:set_globals"]();},
    unload() {windowEvents.pagehide();},
    load() {elements.page.complete = true; elements.page.naturalWidth = 1; elements.page.load();},
    replace(page) {
      response = structuredClone(response);response.structuredContent.data.page = page;
      response.structuredContent.data.render_receipt = "new-synthetic-receipt";
      api.toolResponseMetadata = {mcp_tool_result: response};app.ontoolresult(response);
    },
  };
}

const scenario = process.argv[2];
if (["pdf", "pptx", "fallback"].includes(scenario)) {
  const h = await mount({format: scenario === "pptx" ? "pptx" : "pdf", fallback: scenario === "fallback"});
  assert.match(h.elements.read.textContent, /\(30s\)$/);
  await h.advance(29000);assert.match(h.elements.read.textContent, /\(1s\)$/);assert.equal(h.calls.length, 0);
  await h.advance(1000);assert.equal(h.calls.length, 1);assert.equal(h.messages.length, 1);
  assert.equal(h.calls[0].arguments.connection_id, "synthetic-owner");
  assert.equal(h.calls[0].arguments.expected_hash || h.calls[0].arguments.expected_source_hash, "a".repeat(64));
  if(scenario === "pptx") {assert.equal(h.calls[0].name, "render_course_slide");assert.equal(h.calls[0].arguments.slide, 2);}
  if(scenario === "fallback") {
    assert.deepEqual(Buffer.from(await h.uploads[0].file.arrayBuffer()), bytes);
    assert.equal(h.uploads[0].args.library, false);assert.deepEqual(Array.from(h.api.widgetState.imageIds), ["synthetic-owned-upload"]);
  } else assert.deepEqual(h.contexts[0].content[0], {type: "image", data: png, mimeType: "image/png"});
  assert.equal(h.api.widgetState.privateContent.unrelated, "preserved");
  assert.equal(h.api.widgetState.privateContent.readerAutoSend.phase, "sent");
  await h.advance(60000);h.globals();await h.advance(60000);assert.equal(h.messages.length, 1);
  const remount = await mount({saved: h.api.widgetState, format: scenario === "pptx" ? "pptx" : "pdf"});await remount.advance(60000);assert.equal(remount.calls.length, 0);
} else if(scenario === "cancel") {
  const h = await mount();await h.advance(10000);h.elements.cancel.click();await h.advance(60000);
  assert.equal(h.calls.length, 0);assert.equal(h.messages.length, 0);assert.equal(h.elements.cancel.hidden, true);
  assert.match(h.elements.status.textContent, /canceled/);h.globals();await h.advance(60000);assert.equal(h.calls.length, 0);
  const remount = await mount({saved: h.api.widgetState});await remount.advance(60000);assert.equal(remount.calls.length, 0);
  await remount.elements.read.click();await flush();assert.equal(remount.messages.length, 1);
} else if(scenario === "manual") {
  const h = await mount();await h.advance(12000);await h.elements.read.click();await flush();
  await h.advance(60000);assert.equal(h.messages.length, 1);assert.equal(h.calls.length, 1);
  assert.equal(h.timers.size, 0);
} else if(scenario === "visibility") {
  const h = await mount({visible: false});await h.advance(60000);assert.equal(h.calls.length, 0);
  h.visible();await h.advance(15000);h.visible(false);await h.advance(60000);
  assert.match(h.elements.read.textContent, /\(15s\)$/);
  h.visible();h.visibility("hidden");await h.advance(60000);assert.equal(h.calls.length, 0);
  h.visibility("visible");await h.advance(14000);assert.equal(h.calls.length, 0);await h.advance(1000);assert.equal(h.messages.length, 1);
} else if(scenario === "suspend") {
  const h = await mount();await h.advance(3600000, 3600000);assert.equal(h.calls.length, 0);
  assert.match(h.elements.read.textContent, /\(29s\)$/);
  h.unload();await h.advance(60000);assert.equal(h.calls.length, 0);
} else if(scenario === "loading") {
  const h = await mount({loaded: false});await h.advance(60000);assert.equal(h.calls.length, 0);
  h.load();await h.advance(29000);assert.equal(h.calls.length, 0);await h.advance(1000);assert.equal(h.messages.length, 1);
  const cancelled = await mount({loaded: false});cancelled.elements.cancel.click();cancelled.load();await cancelled.advance(60000);assert.equal(cancelled.calls.length, 0);
} else if(["denied", "changed", "messageFails"].includes(scenario)) {
  const h = await mount({[scenario]: true});await h.advance(30000);assert.equal(h.calls.length, 1);
  if(scenario !== "messageFails") {assert.equal(h.messages.length, 0);assert.equal(h.contexts.length, 0);}
  assert.match(h.elements.status.textContent, /could not be added safely/);
  h.globals();await h.advance(60000);assert.equal(h.calls.length, 1);
} else if(["cancel_refresh", "cancel_digest"].includes(scenario)) {
  const gate = deferred(), h = await mount({[scenario === "cancel_refresh" ? "refreshGate" : "digestGate"]: gate});
  await h.advance(30000);assert.equal(h.calls.length, 1);assert.equal(h.elements.cancel.hidden, false);
  h.elements.cancel.click();gate.resolve();await flush();
  assert.equal(h.elements.cancel.hidden, true);assert.equal(h.messages.length, 0);assert.equal(h.contexts.length, 0);assert.equal(h.uploads.length, 0);
  assert.equal(h.api.widgetState.privateContent.readerAutoSend.phase, "cancelled");
} else if(scenario === "new_preview") {
  const h = await mount();await h.advance(15000);h.replace(3);await h.advance(15000);
  assert.equal(h.calls.length, 0);await h.advance(15000);assert.equal(h.calls.length, 1);assert.equal(h.calls[0].arguments.page, 3);
} else if(scenario === "globals") {
  const h = await mount();for(let i = 0; i < 6; i++) {h.globals();await h.advance(5000);}
  assert.equal(h.messages.length, 1);assert.equal(h.calls.length, 1);
} else if(["noState", "stateFails", "unsupported"].includes(scenario)) {
  const h = await mount({[scenario]: true});await h.advance(60000);assert.equal(h.calls.length, 0);
  if(scenario !== "unsupported") {await h.elements.read.click();await flush();assert.equal(h.messages.length, 1);}
} else {throw Error(`Unknown scenario: ${scenario}`);}
console.log(`PASS ${scenario}`);
