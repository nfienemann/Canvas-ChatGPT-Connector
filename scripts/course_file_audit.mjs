/* Read-only public-tool audit. No Canvas HTTP, database or credential access.
 * Host injects callTool, save (atomic private checkpoint), and decodeImage.
 * Only allowlisted diagnostic fields survive into the checkpoint.
 */
import { recoveringRead } from './auth_recovery.mjs';

export class CourseFileAudit {
  constructor({ callTool, recovery, save, decodeImage, sleep, state, connection, resumableInventory = false, maxInventoryPagesPerRun = 1000 }) {
    Object.assign(this, { callTool: recovery ? recoveringRead(callTool, recovery) : callTool, save, decodeImage, connection });
    this.sleep = sleep || (ms => new Promise(resolve => setTimeout(resolve, ms)));
    this.state = state || { version: 1, courses: {}, events: [], coursesComplete: false };
    if (this.state.version !== 1) throw new Error('Unsupported checkpoint');
    if (this.state.connection && this.state.connection !== connection) throw new Error('Checkpoint connection mismatch');
    this.state.connection = connection;
    this.resumableInventory = resumableInventory;
    if (!Number.isInteger(maxInventoryPagesPerRun) || maxInventoryPagesPerRun < 1 || maxInventoryPagesPerRun > 1000) throw new Error('Invalid inventory request budget');
    this.maxInventoryPagesPerRun = maxInventoryPagesPerRun;
  }
  safe(value) {
    return typeof value === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/.test(value) ? value : null;
  }
  async flush() {
    const checkpoint = JSON.parse(JSON.stringify(this.state));
    if (this.checkpointFailure) throw new Error('Reload the checkpoint before continuing.');
    try { await this.save(checkpoint); }
    catch (error) {
      this.checkpointFailure = error?.code === 'CHECKPOINT_CONFLICT' ? 'CHECKPOINT_CONFLICT' : 'CHECKPOINT_COMMIT_UNCERTAIN';
      throw new Error('Checkpoint save failed or was interrupted. Reload the checkpoint before continuing.');
    }
    // The adapter acknowledges its committed revision on the isolated copy.
    // Retain it across no-op flushes and subsequent worker handoffs.
    if (Object.hasOwn(checkpoint, '_checkpointRevision')) {
      this.state._checkpointRevision = checkpoint._checkpointRevision;
    }
  }
  async call(tool, args, course = null, file = null) {
    if (this.checkpointFailure) throw new Error('Reload the checkpoint before continuing.');
    const allowed = ['list_courses', 'list_course_files', 'read_course_file',
      'render_course_file_page', 'render_course_slide', 'get_assignment_details', 'get_workload',
      'get_course_outline', 'audit_permission_consistency', 'get_file_extraction_status'];
    if (!allowed.includes(tool)) throw new Error('Read-only tool allowlist');
    for (let attempt = 0; attempt < 2; attempt++) {
      const startedAt = Date.now();
      let raw, result;
      try {
        raw = await this.callTool(tool, { connection_id: this.connection, ...args });
        result = raw.structuredContent || raw;
        if (!result.status) {
          for (const block of raw.content || []) {
            if (block.type !== 'text') continue;
            try { const parsed = JSON.parse(block.text); if (parsed.status) { result = parsed; break; } }
            catch { /* Never persist an unstructured transport error. */ }
          }
        }
        if (!result.status) result = { status: 'operation_uncertain', data: { reason_code: raw.isError ? 'TRANSPORT_FAILURE' : 'MALFORMED_TOOL_RESPONSE' } };
      } catch {
        result = { status: 'operation_uncertain', data: { reason_code: 'TRANSPORT_FAILURE' } };
      }
      const d = result.data || {}, m = result.meta || {};
      this.state.events.push({ tool, course: this.safe(course), file: this.safe(file),
        started_at: new Date(startedAt).toISOString(), elapsed_ms: Math.max(0, Date.now() - startedAt),
        page: args.page ?? args.slide ?? args.page_start ?? null, offset: args.offset ?? null,
        resolution: this.safe(args.resolution),
        attempt, status: this.safe(result.status), reason: this.safe(d.reason_code),
        request_id: this.safe(m.request_id), freshness: this.safe(m.freshness),
        recipient: this.safe(m.egress?.recipient_category) });
      this.state.events.at(-1).inventory_operation = this.safe(d.inventory_operation);
      this.state.events.at(-1).page_identity = this.safe(d.page_identity);
      if (typeof d.cache_hit === 'boolean') this.state.events.at(-1).cache_hit = d.cache_hit;
      if (Array.isArray(d.pipeline_events)) {
        this.state.events.at(-1).pipeline_timings = d.pipeline_events.filter(e =>
          e && ['authorization', 'source_fetch', 'pptx_conversion', 'derivative_registration', 'pdf_page_render',
            'image_response_preparation', 'image_delivery', 'model_visibility', 'visual_interpretation'].includes(e.stage) &&
          ['completed', 'failed', 'not_attempted', 'unavailable'].includes(e.result) &&
          Number.isFinite(e.duration_ms) && e.duration_ms >= 0 && e.duration_ms <= 3600000
        ).slice(0, 20).map(e => ({ stage: e.stage, result: e.result, duration_ms: e.duration_ms }));
      }
      if (['AUTH_ORIGIN_UNKNOWN', 'CLIENT_REAUTH_REQUIRED', 'UPSTREAM_THROTTLED', 'LOCAL_REQUEST_BUSY', 'UPSTREAM_CIRCUIT_OPEN', 'AUTHORIZATION_BUSY', 'RATE_LIMITED', 'OWNER_RATE_LIMITED', 'MALFORMED_TOOL_RESPONSE', 'TRANSPORT_FAILURE'].includes(d.reason_code)) {
        const delay = d.retry_after_seconds;
        this.state.hold = { reason: d.reason_code,
          retryAt: Number.isFinite(delay) && delay >= 0 ? Date.now() + delay * 1000 : null };
        await this.flush();
        return { raw, result };
      }
      await this.flush();
      if (result.status !== 'retry_later') return { raw, result };
      const retry = d.retry_after_seconds ?? d.retry_after;
      let seconds = Number(retry);
      if (!Number.isFinite(seconds) && typeof retry === 'string') seconds = (Date.parse(retry) - Date.now()) / 1000;
      if (!Number.isFinite(seconds)) seconds = 2 ** attempt;
      // Never retry earlier than Retry-After; long waits are resumable holds.
      // A timeout with unknown worker state and a legacy retry_later cannot
      // establish that replay is safe. Leave resumption to the caller.
      const eligible = d.diagnostic?.retry === 'automatic_once' &&
        d.diagnostic.operation_state === 'stopped';
      if (seconds > 60 || attempt === 1 || !eligible) {
        this.state.hold = { reason: this.safe(d.reason_code) || 'RETRY_LATER',
          retryAt: retry == null ? null : Date.now() + Math.max(0, seconds) * 1000 };
        await this.flush();
        return { raw, result };
      }
      await this.sleep(Math.max(0, seconds) * 1000);
    }
  }
  course(id) {
    if (!this.safe(id)) throw new Error('Invalid opaque course reference');
    return this.state.courses[id] ||= { inventoryComplete: false, gaps: [], files: {} };
  }
  async discover() {
    if (!this.state.discovery?.inProgress) {
      this.state.discovery = { inProgress: true, completed: [] };
      for (const c of Object.values(this.state.courses)) {
        c.inventoryComplete = false;
        c.gaps = ['not_refreshed'];
        c.inventoryResume = null;
        c.inventoryStructuralGaps = [];
        c.folderParents = {};
        c.inventoryFailures = [];
      }
      await this.flush();
    }
    const { result: r } = await this.call('list_courses', {});
    this.state.coursesComplete = r.status === 'ok' && ['live', 'synthetic'].includes(r.meta?.freshness) &&
      !r.meta?.next_cursor && (r.meta?.coverage || []).some(
      c => c.resource === 'courses' && c.state === 'complete' && c.pagination_complete === true);
    for (const c of r.data?.courses || []) if (c.selected) this.course(c.id);
    if (this.state.coursesComplete) {
      const selected = new Set((r.data?.courses || []).filter(c => c.selected).map(c => c.id));
      this.state.courses = Object.fromEntries(Object.entries(this.state.courses).filter(([id]) => selected.has(id)));
    }
    // Prior selected refs remain investigation targets after a failed listing.
    // They are never treated as current authorization evidence.
    for (const id of Object.keys(this.state.courses)) {
      if (this.state.hold) break;
      if (this.state.discovery.completed.includes(id)) continue;
      await this.inventory(id);
      if (!this.state.hold) this.state.discovery.completed.push(id);
      await this.flush();
    }
    if (!this.state.hold) this.state.discovery.inProgress = false;
    await this.flush();
  }
  async inventory(id) {
    const c = this.course(id);
    let requests = 0;
    if (!c.inventoryResume || c.inventoryResume.done) {
      c.inventoryResume = { cursor: null, seen: [], pages: [], done: false };
      c.inventoryFailures = [];
    }
    do {
      if (requests >= this.maxInventoryPagesPerRun) {
        c.inventoryComplete = false;
        this.state.hold = { reason: 'AUDIT_REQUEST_BUDGET', retryAt: Date.now() };
        await this.flush();
        return;
      }
      requests++;
      const progress = c.inventoryResume;
      const args = { course_id: id };
      if (this.resumableInventory) {
        args.inventory_mode = 'resumable';
        if (progress.cursor) args.cursor = progress.cursor;
      }
      const { result: r } = await this.call('list_course_files', args, id);
      const coverage = r.data?.coverage || {};
      c.gaps = [...(c.inventoryStructuralGaps || [])];
      if (r.meta?.next_cursor && !this.resumableInventory) c.gaps.push('public_inventory_continuation_unavailable');
      c.inventoryFailures ||= [];
      for (const [resource, value] of Object.entries(r.data?.inventory_reason_codes || {})) {
        const reason = this.safe(value.reason_code);
        if (c.inventoryFailures.some(f => f.resource === resource && f.reason === reason)) continue;
        const failure = { resource: this.safe(resource), reason,
          operation: this.safe(r.data?.inventory_operation),
          request_id: this.safe(value.request_id) || this.safe(r.meta?.request_id),
          continuation_step: progress.seen.length };
        c.inventoryFailures.push(failure);
        // The native request event may already be checkpointed. Append its
        // diagnostic annotation rather than rewriting saved request evidence.
        this.state.events.push({ ...this.state.events.at(-1),
          record_type: 'inventory_failure_annotation', inventory_failures: [failure] });
      }
      for (const resource of ['files', 'modules', 'folders', 'assignments']) {
        if (coverage[resource] !== 'complete') c.gaps.push(`${resource}_incomplete`);
      }
      if (r.status !== 'ok' || !['live', 'synthetic'].includes(r.meta?.freshness)) c.gaps.push('inventory_not_live_complete');
      c.inventoryComplete = c.gaps.length === 0;
      for (const f of r.data?.files || []) this.addFile(id, f, 'file_inventory');
      c.folderParents ||= {};
      for (const node of r.data?.folder_graph || []) {
        const child = this.safe(node.id), parent = node.parent_id == null ? null : this.safe(node.parent_id);
        if (!child || (node.parent_id != null && !parent) ||
            (Object.hasOwn(c.folderParents, child) && c.folderParents[child] !== parent)) {
          (c.inventoryStructuralGaps ||= []).push('folder_graph_invalid');
          c.inventoryComplete = false;
          continue;
        }
        c.folderParents[child] = parent;
      }
      if (this.state.hold) {
        await this.flush();
        return;
      }
      const next = r.meta?.next_cursor;
      const page = this.safe(r.data?.page_identity);
      if (this.resumableInventory && page && progress.pages.includes(page)) {
        c.inventoryComplete = false;
        c.gaps.push('inventory_continuation_invalid_or_cyclic');
        progress.done = true;
        await this.flush();
        return;
      }
      if (!this.resumableInventory || !next || !['ok', 'partial_data'].includes(r.status)) {
        // Empty folders still belong to the traversal graph. Validate each edge
        // once, even when no file path happens to enter the cyclic component.
        const checked = new Set();
        for (const start of Object.keys(c.folderParents)) {
          let folder = start; const path = new Set();
          while (folder != null && Object.hasOwn(c.folderParents, folder) && !checked.has(folder)) {
            if (path.has(folder)) {
              c.inventoryComplete = false;
              if (!c.gaps.includes('folder_cycle')) c.gaps.push('folder_cycle');
              break;
            }
            path.add(folder);
            folder = c.folderParents[folder];
          }
          for (const node of path) checked.add(node);
        }
        for (const f of Object.values(c.files)) for (const path of [...f.paths]) {
          if (!path.startsWith('folder:')) continue;
          let folder = path.slice(7); const seen = new Set();
          while (folder != null && Object.hasOwn(c.folderParents, folder)) {
            if (seen.has(folder)) { c.inventoryComplete = false; c.gaps.push('folder_cycle'); break; }
            seen.add(folder);
            if (!f.paths.includes('folder:' + folder)) f.paths.push('folder:' + folder);
            folder = c.folderParents[folder];
          }
        }
        progress.done = true;
        await this.flush();
        return;
      }
      if (typeof next !== 'string' || next.length > 4096 || !/^[a-zA-Z0-9_-]+=*$/.test(next) ||
          progress.seen.includes(next) || (page && progress.pages.includes(page))) {
        c.inventoryComplete = false;
        c.gaps.push('inventory_continuation_invalid_or_cyclic');
        progress.done = true;
        await this.flush();
        return;
      }
      if (page) progress.pages.push(page);
      progress.seen.push(next);
      progress.cursor = next;
      c.inventoryComplete = false;
      await this.flush();
    } while (true);
  }
  addFile(course, f, path) {
    const c = this.course(course);
    const stable = this.safe(f.canvas_file_id || f.file_id), ref = this.safe(f.file_id);
    if (!stable || !ref) { c.inventoryComplete = false; c.gaps.push('stable_file_identity_missing'); (c.inventoryStructuralGaps ||= []).push('stable_file_identity_missing'); return; }
    const version = this.safe(f.source_version);
    let entry = c.files[stable];
    if (entry && entry.version !== version) {
      this.state.events.push({ record_type: 'superseded_source_progress', course: this.safe(course),
        file: ref, source_version: entry.version, content_hash: entry.hash, parser: entry.parser || null,
        text_positions: [...entry.pages], decoded_positions: [...entry.rendered] });
    }
    if (!entry || entry.version !== version) entry = c.files[stable] = {
      ref, version, paths: entry?.paths || [], outcome: 'pending', next: null, seen: [], pages: [], rendered: [],
      partial: false, textDone: false, format: null, pageCount: null, hash: null,
    };
    if (!entry.paths.includes(path)) entry.paths.push(path);
    const mime = { 'application/pdf': 'pdf', 'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx', 'text/plain': 'txt', 'text/markdown': 'md' };
    const hint = mime[f.type] || /\.(pdf|pptx|docx|xlsx|txt|md)$/i.exec(f.filename || '')?.[1]?.toLowerCase();
    if (hint) entry.formatHint = hint;
    for (const folder of f.folders || []) {
      const p = this.safe(folder);
      if (p && !entry.paths.includes(`folder:${p}`)) entry.paths.push(`folder:${p}`);
    }
    for (const assignment of f.assignments || []) {
      const p = this.safe(assignment);
      if (p && !entry.paths.includes(`assignment:${p}`)) entry.paths.push(`assignment:${p}`);
    }
    for (const m of f.modules || []) {
      const p = this.safe(m.id);
      if (p && !entry.paths.includes(`module:${p}`)) entry.paths.push(`module:${p}`);
    }
  }
  classify(r) {
    const code = r.data?.reason_code || '';
    if (r.status === 'permission_denied' && ['RESOURCE_PERMISSION_DENIED',
      'MISSING_RESOURCE_CAPABILITY', 'COURSE_NOT_SELECTED', 'SELECTED_SCOPE_MISMATCH'].includes(code)) return 'denied';
    if (r.status === 'unsupported_feature' && /UNSUPPORTED|ENCRYPTED|ACTIVE_/.test(code)) return 'unsupported';
    return 'failed';
  }
  async visualAudit(course, f) {
    if (f.visualChecked || f.outcome === 'denied') return;
    const format = f.format || f.formatHint;
    if (f.outcome === 'unsupported' && !['pdf', 'pptx'].includes(format)) return;
    if (format && !['pdf', 'pptx'].includes(format)) {
      f.visualChecked = true; f.visualStatus = 'not_applicable'; await this.flush(); return;
    }
    // A text-release failure is not evidence that the separate visual gate denied.
    // With no reliable format/count yet, page one probes the actual public renderer.
    let last = f.pageCount || 1;
    f.rendered ||= [];
    for (let page = f.visualNext || 1; page <= last; page++) {
      if (f.rendered.includes(page)) continue;
      const slideReader = (f.format || f.formatHint) === 'pptx';
      const args = slideReader ? { file_id: f.ref, slide: page, resolution: 'standard' } : { file_id: f.ref, page };
      if (f.hash) args[slideReader ? 'expected_source_hash' : 'expected_hash'] = f.hash;
      const { raw, result: r } = await this.call(slideReader ? 'render_course_slide' : 'render_course_file_page', args, course, f.ref);
      if (this.state.hold) { await this.flush(); return; }
      f.visualNext = page + 1;
      if (r.status !== 'ok') {
        f.visualReason = this.safe(r.data?.reason_code) || this.safe(r.status);
        f.visualStatus = 'failed';
        if (r.status === 'unsupported_feature' && !f.pageCount) {
          f.visualNext = page;
          const { result: metadata } = await this.call('get_file_extraction_status', { file_id: f.ref }, course, f.ref);
          if (this.state.hold) { await this.flush(); return; }
          const d = metadata.data || {}, hash = this.safe(d.content_hash);
          if (metadata.status === 'ok' && hash && (!f.hash || f.hash === hash) &&
              ['pdf', 'pptx'].includes(d.format) && (!format || format === d.format) &&
              Number.isInteger(d.page_count) && d.page_count >= page && d.page_count <= 200) {
            f.hash = hash; f.pageCount = last = d.page_count; f.format = d.format;
          } else f.visualMetadataReason = this.safe(d.reason_code) || 'VISUAL_PAGE_COUNT_UNAVAILABLE';
          f.visualNext = page + 1;
        }
        if (['permission_denied', 'source_changed', 'reconnect_required'].includes(r.status) || !f.pageCount) break;
        await this.flush(); continue;
      }
      const d = r.data || {}, hash = this.safe(d.content_hash);
      if (!hash || (f.hash && f.hash !== hash) || !Number.isInteger(d.page_count) ||
          d.page_count < 1 || d.page_count > 200 || (f.pageCount && f.pageCount !== d.page_count) ||
          (d.page != null && d.page !== page) || (d.slide_number != null && d.slide_number !== page)) {
        f.visualReason = 'VISUAL_COVERAGE_INVALID'; f.visualStatus = 'failed'; break;
      }
      f.hash = hash; f.pageCount = last = d.page_count;
      if (['pdf', 'pptx'].includes(d.format)) f.format ||= d.format;
      let decoded = false;
      try { decoded = !!this.decodeImage && await this.decodeImage(raw); } catch { /* Missing proof. */ }
      if (decoded) f.rendered.push(page);
      else { f.visualReason = 'IMAGE_DECODE_UNVERIFIED'; f.visualStatus = 'partial'; }
      await this.flush();
    }
    f.visualChecked = true;
    if (f.pageCount && f.rendered.length === f.pageCount) f.visualStatus = 'complete';
    if (!f.textDone && f.rendered.length) f.outcome = 'partial';
    await this.flush();
  }
  async read(course, f, { render = true } = {}) {
    if (['fully_read', 'denied'].includes(f.outcome)) return;
    if (f.outcome === 'unsupported') { if (render) await this.visualAudit(course, f); return; }
    while (!f.textDone) {
      const args = f.next || { file_id: f.ref, offset: 0, length: 16000 };
      const marker = JSON.stringify(args);
      if (f.seen.includes(marker)) { f.outcome = 'partial'; f.reason = 'CONTINUATION_CYCLE'; break; }
      const { result: r } = await this.call('read_course_file', args, course, f.ref);
      if (!['ok', 'partial_data'].includes(r.status)) { f.outcome = this.state.hold ? 'pending' : f.pages.length ? 'partial' : this.classify(r); break; }
      const d = r.data || {};
      // Safe error envelopes may retain partial_data while releasing no source text.
      // Keep prior evidence, but never credit the error itself as a partial read.
      if (d.reason_code && typeof d.text !== 'string') {
        f.outcome = f.pages.length || f.rendered.length ? 'partial' : this.classify(r);
        f.reason = this.safe(d.reason_code) || 'READ_COVERAGE_MISSING';
        break;
      }
      if (f.parser && d.parser !== f.parser) { f.outcome = 'partial'; f.reason = 'DOCUMENT_PARSER_VERSION_CHANGED'; break; }
      f.parser = this.safe(d.parser);
      if (f.hash && d.content_hash !== f.hash) { f.outcome = 'partial'; f.reason = 'SOURCE_CHANGED'; break; }
      f.hash = this.safe(d.content_hash);
      f.format = this.safe(d.format); f.pageCount = d.page_count;
      if (!f.hash || !Number.isInteger(f.pageCount) || f.pageCount < 1 || f.pageCount > 200 || f.seen.length >= 1000) { f.outcome = 'partial'; f.reason = 'READ_COVERAGE_MISSING'; break; }
      f.seen.push(marker);
      f.readerCoverage = this.safe(d.coverage);
      if (r.status === 'partial_data' || d.coverage !== 'text_only') f.reason ||= 'READER_PARTIAL_COVERAGE';
      f.partial ||= r.status === 'partial_data' || d.coverage !== 'text_only';
      // Page metadata alone does not prove that every character window arrived.
      f.windows ||= {};
      const range = `${Number.isInteger(d.page_start) ? d.page_start : 1}:${Number.isInteger(d.page_end) ? d.page_end : f.pageCount}`;
      const end = Number.isInteger(d.offset) ? d.offset + (typeof d.text === 'string' ? Array.from(d.text).length : 0) : null;
      const prior = f.windows[range];
      const windowValid = Number.isInteger(d.offset) && d.offset >= 0 &&
        Number.isInteger(d.total_extracted_characters) && d.total_extracted_characters >= 0 &&
        typeof d.text === 'string' && d.offset === (prior?.end || 0) &&
        (!prior || prior.total === d.total_extracted_characters) &&
        end <= d.total_extracted_characters &&
        (d.next_offset == null ? end === d.total_extracted_characters : d.next_offset === end);
      if (!windowValid) { f.partial = true; f.reason = 'READ_CHARACTER_COVERAGE_GAP'; }
      f.windows[range] = { end, total: Number.isInteger(d.total_extracted_characters) ? d.total_extracted_characters : null };
      for (const p of d.page_extraction || []) if (Number.isInteger(p.page) && !f.pages.includes(p.page)) f.pages.push(p.page);
      if (d.continuation) {
        const n = d.continuation;
        if (n.file_id !== f.ref || n.expected_hash !== f.hash ||
          (n.expected_parser != null && (!f.parser || n.expected_parser !== f.parser)) ||
          !Number.isInteger(n.offset) || !Number.isInteger(n.page_start) || !Number.isInteger(n.page_end)) {
          f.outcome = 'partial'; f.reason = 'INVALID_CONTINUATION'; break;
        }
        f.next = { file_id: f.ref, expected_hash: f.hash, offset: n.offset,
          page_start: n.page_start, page_end: n.page_end, length: 16000,
          ...(n.expected_parser ? { expected_parser: f.parser } : {}) };
      } else { f.textDone = true; f.next = null; }
      await this.flush();
    }
    if (render && !f.textDone && ['failed', 'partial', 'unsupported'].includes(f.outcome)) await this.visualAudit(course, f);
    if (render && f.textDone && ['pdf', 'pptx'].includes(f.format)) await this.visualAudit(course, f);
    if (f.textDone) {
      const pagesComplete = Array.from({ length: f.pageCount }, (_, i) => i + 1).every(p => f.pages.includes(p));
      const rendersComplete = !['pdf', 'pptx'].includes(f.format) ||
        Array.from({ length: f.pageCount }, (_, i) => i + 1).every(p => f.rendered.includes(p));
      f.outcome = !f.partial && pagesComplete && rendersComplete ? 'fully_read' : 'partial';
      if (f.outcome === 'fully_read') f.reason = null;
      // Deferring visuals is an ordering choice, never evidence of completion.
      if (!render && !rendersComplete) f.outcome = 'pending';
    }
    if (this.state.hold) f.outcome = 'pending';
    await this.flush();
  }
  async run({ retryFailed = false } = {}) {
    if (this.state.hold) {
      if (this.state.hold.retryAt === null || Date.now() < this.state.hold.retryAt) return this.report();
      this.state.hold = null;
    }
    await this.discover();
    for (const [id, c] of Object.entries(this.state.courses)) for (const f of Object.values(c.files)) {
      if (this.state.hold) break;
      if (f.outcome !== 'pending' && !(retryFailed && ['failed', 'partial'].includes(f.outcome))) continue;
      if (retryFailed && ['failed', 'partial'].includes(f.outcome)) {
        for (const key of ['windows', 'parser', 'reason', 'visualReason', 'visualMetadataReason', 'visualStatus']) delete f[key];
        Object.assign(f, { outcome: 'pending', next: null, seen: [], pages: [], rendered: [],
          partial: false, textDone: false, format: null, pageCount: null, hash: null,
          visualChecked: false, visualNext: 1 });
      }
      await this.read(id, f);
    }
    for (const [id, c] of Object.entries(this.state.courses)) for (const f of Object.values(c.files)) {
      if (this.state.hold) break;
      await this.visualAudit(id, f);
    }
    return this.report();
  }
  mergeVisualCheckpoint(branch) {
    if (branch.connection !== this.state.connection) throw new Error('Visual checkpoint connection mismatch');
    let merged = 0, rejected = 0;
    for (const [course, c] of Object.entries(branch.courses || {})) {
      for (const [stable, visual] of Object.entries(c.files || {})) {
        if (!visual.textDone || !['pdf', 'pptx'].includes(visual.format) ||
            (!visual.visualChecked && !visual.rendered?.length)) continue;
        const current = this.state.courses[course]?.files[stable];
        if (!current || !current.textDone || current.outcome === 'denied' ||
            ['ref', 'version', 'hash', 'format', 'pageCount'].some(k => current[k] !== visual[k]) ||
            !current.hash || !Array.isArray(visual.rendered) ||
            visual.rendered.some(p => !Number.isInteger(p) || p < 1 || p > current.pageCount) ||
            (visual.visualNext != null && (!Number.isInteger(visual.visualNext) ||
              visual.visualNext < 1 || visual.visualNext > current.pageCount + 1))) {
          rejected++; continue;
        }
        current.rendered = [...new Set([...current.rendered, ...visual.rendered])].sort((a, b) => a - b);
        for (const key of ['visualChecked', 'visualNext', 'visualStatus', 'visualReason', 'visualMetadataReason']) {
          if (visual[key] !== undefined) current[key] = visual[key];
        }
        // Text, inventory, denial, and completion state remain owned by this audit.
        // A subsequent read() reconciles completion using both bodies of evidence.
        merged++;
      }
    }
    const events = new Set(this.state.events.map(e => JSON.stringify(e)));
    for (const event of branch.events || []) {
      const key = JSON.stringify(event);
      if (!events.has(key)) { this.state.events.push(JSON.parse(key)); events.add(key); }
    }
    for (const [key, count] of Object.entries(branch.transportResumes || {})) {
      if (!Number.isInteger(count) || count < 0 || ['__proto__', 'constructor', 'prototype'].includes(key)) continue;
      this.state.transportResumes ||= {};
      this.state.transportResumes[key] = Math.max(this.state.transportResumes[key] || 0, count);
    }
    return { merged, rejected };
  }
  report() {
    const rows = Object.entries(this.state.courses).map(([course, c]) => {
      const counts = { fully_read: 0, partial: 0, unsupported: 0, denied: 0, failed: 0, pending: 0 };
      for (const f of Object.values(c.files)) counts[f.outcome]++;
      return { course, inventoryComplete: Boolean(this.state.coursesComplete && c.inventoryComplete),
        discovered: Object.keys(c.files).length, ...counts };
    });
    return { ...(this.checkpointFailure ? { checkpoint_status: this.checkpointFailure, progress_scope: 'in_memory' } : {}),
      clean: !this.checkpointFailure && !this.state.hold && this.state.coursesComplete && rows.length > 0 && rows.every(r =>
      r.inventoryComplete && !r.partial && !r.failed && !r.pending), rows };
  }
}
