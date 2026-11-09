import test from 'node:test';
import assert from 'node:assert/strict';
import { CourseFileAudit } from '../scripts/course_file_audit.mjs';

function make(callTool, options = {}) {
  let saved;
  const audit = new CourseFileAudit({ callTool, connection: 'synthetic',
    save: async value => { saved = value; }, sleep: async () => {}, ...options });
  return { audit, saved: () => saved };
}
const listing = { status: 'ok', data: { files: [
  { canvas_file_id: '1', file_id: 'opaque', source_version: 'v1' },
  { canvas_file_id: '1', file_id: 'opaque', source_version: 'v1', modules: [{ id: 'm1' }] },
] }, meta: { freshness: 'live' } };
const read = { status: 'ok', data: { format: 'xlsx', content_hash: 'hash', page_count: 2,
  offset: 0, total_extracted_characters: 21, next_offset: null,
  coverage: 'text_only', page_extraction: [{ page: 1 }, { page: 2 }], continuation: null,
  text: 'SECRET COURSE CONTENT', url: 'https://example.invalid/?token=secret' }, meta: {} };

for (const freshness of ['not_refreshed', 'cached', undefined, 'live', 'synthetic']) {
  test(`course inventory completeness requires refreshed course enumeration: ${freshness}`, async () => {
    const { audit } = make(async tool => tool === 'list_courses'
      ? { status: 'ok', data: { courses: [{ id: 'c', selected: true }] }, meta: {
        freshness, coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }],
      } }
      : { status: 'ok', data: { files: [], coverage: {
        files: 'complete', folders: 'complete', modules: 'complete', assignments: 'complete',
      } }, meta: { freshness: 'live' } });
    await audit.discover();
    const complete = ['live', 'synthetic'].includes(freshness);
    assert.equal(audit.state.coursesComplete, complete);
    assert.equal(audit.report().rows[0].inventoryComplete, complete);
    assert.equal(audit.report().clean, complete);
  });
}

function visualBranchFixture() {
  const { audit } = make(async () => { throw new Error('Completed evidence must not replay native reads'); });
  audit.addFile('c', { file_id: 'opaque', canvas_file_id: '1', source_version: 'v1' }, 'inventory');
  const f = audit.course('c').files['1'];
  Object.assign(f, { textDone: true, format: 'pdf', hash: 'hash', pageCount: 2, pages: [1, 2], rendered: [1] });
  const branch = structuredClone(audit.state);
  Object.assign(branch.courses.c.files['1'], { rendered: [1, 2], visualChecked: true, visualNext: 3, visualStatus: 'complete' });
  branch.events.push({ tool: 'render_course_file_page', course: 'c', file: 'opaque', page: 2, request_id: 'synthetic' });
  return { audit, f, branch };
}

test('visual checkpoint merge preserves text and inventory and reconciles without replay', async () => {
  const { audit, f, branch } = visualBranchFixture();
  branch.courses.c.inventoryComplete = true;
  branch.courses.c.files['1'].outcome = 'fully_read';
  assert.deepEqual(audit.mergeVisualCheckpoint(branch), { merged: 1, rejected: 0 });
  assert.equal(f.outcome, 'pending');
  assert.equal(audit.course('c').inventoryComplete, false);
  assert.deepEqual(f.rendered, [1, 2]);
  audit.mergeVisualCheckpoint(branch);
  assert.equal(audit.state.events.length, 1);
  await audit.read('c', f);
  assert.equal(f.outcome, 'fully_read');
});

for (const key of ['ref', 'version', 'hash', 'format', 'pageCount']) {
  test(`visual merge rejects changed ${key}`, () => {
    const { audit, f, branch } = visualBranchFixture();
    f[key] = key === 'pageCount' ? 3 : 'changed';
    assert.deepEqual(audit.mergeVisualCheckpoint(branch), { merged: 0, rejected: 1 });
    assert.deepEqual(f.rendered, [1]);
  });
}

test('visual merge cannot replace a current denial or reader partial flag', async () => {
  const { audit, f, branch } = visualBranchFixture();
  f.outcome = 'denied';
  assert.equal(audit.mergeVisualCheckpoint(branch).rejected, 1);
  assert.equal(f.outcome, 'denied');
  f.outcome = 'pending'; f.partial = true;
  audit.mergeVisualCheckpoint(branch);
  await audit.read('c', f);
  assert.equal(f.outcome, 'partial');
});

test('visual merge rejects foreign connections and invalid page evidence', () => {
  const { audit, f, branch } = visualBranchFixture();
  branch.connection = 'foreign';
  assert.throws(() => audit.mergeVisualCheckpoint(branch), /connection mismatch/);
  branch.connection = audit.state.connection;
  branch.courses.c.files['1'].rendered.push(3);
  assert.equal(audit.mergeVisualCheckpoint(branch).rejected, 1);
  assert.deepEqual(f.rendered, [1]);
});

test('visual checkpoint reconciliation cannot reset bounded transport retry counts', () => {
  const { audit, branch } = visualBranchFixture();
  audit.state.transportResumes = { 'f:1': 2 };
  branch.transportResumes = { 'f:1': 1, 'f:2': 1 };
  audit.mergeVisualCheckpoint(branch);
  assert.deepEqual(audit.state.transportResumes, { 'f:1': 2, 'f:2': 1 });
});

test('partial reader coverage retains a content-free diagnostic reason', async () => {
  const { audit, saved } = make(async () => ({ ...read, status: 'partial_data', data: { ...read.data, coverage: 'partial' } }));
  audit.addFile('c', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
  const f = audit.course('c').files['1'];
  await audit.read('c', f);
  assert.equal(f.outcome, 'partial');
  assert.equal(f.reason, 'READER_PARTIAL_COVERAGE');
  assert.equal(f.readerCoverage, 'partial');
  assert.ok(!JSON.stringify(saved()).includes('SECRET COURSE CONTENT'));
});

for (const priorCoverage of [false, true]) {
  test(`content-free partial_data errors preserve only actual prior coverage: ${priorCoverage}`, async () => {
    const { audit } = make(async () => ({ status: 'partial_data',
      data: { reason_code: 'EGRESS_ERROR_REDACTED' }, meta: { request_id: 'synthetic-error' } }));
    audit.addFile('c', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
    const f = audit.course('c').files['1'];
    if (priorCoverage) Object.assign(f, { hash: 'prior-hash', pages: [1],
      windows: { '1:2': { end: 10, total: 20 } } });
    await audit.read('c', f, { render: false });
    assert.equal(f.outcome, priorCoverage ? 'partial' : 'failed');
    assert.equal(f.reason, 'EGRESS_ERROR_REDACTED');
    assert.equal(f.textDone, false);
    if (priorCoverage) assert.equal(f.hash, 'prior-hash');
    assert.equal(audit.state.events.at(-1).request_id, 'synthetic-error');
  });
}

test('native timing diagnostics retain only bounded numeric stages, never source resources', async () => {
  const { audit } = make(async () => ({ status: 'ok', data: { cache_hit: true, pipeline_events: [
    { stage: 'pptx_conversion', result: 'completed', duration_ms: 12, resources: { title: 'PRIVATE SOURCE TEXT' } },
    { stage: 'PRIVATE SOURCE TEXT', result: 'completed', duration_ms: 1 },
    { stage: 'source_fetch', result: 'PRIVATE SOURCE TEXT', duration_ms: 1 },
    { stage: 'source_fetch', result: 'completed', duration_ms: Infinity },
  ] } }));
  await audit.call('render_course_slide', { file_id: 'opaque', slide: 7, resolution: 'standard' }, 'c', 'opaque');
  const event = audit.state.events[0];
  assert.equal(event.cache_hit, true);
  assert.deepEqual(event.pipeline_timings, [{ stage: 'pptx_conversion', result: 'completed', duration_ms: 12 }]);
  assert.equal(event.page, 7);
  assert.ok(Number.isFinite(Date.parse(event.started_at)) && event.elapsed_ms >= 0);
  assert.ok(!JSON.stringify(audit.state).includes('PRIVATE SOURCE TEXT'));
});

test('PPTX uses the public standard slide reader with original-source identity and decoded coverage', async () => {
  const renders = [], decoded = [];
  const { audit } = make(async (tool, args) => {
    if (tool === 'read_course_file') return { ...read, data: { ...read.data, format: 'pptx' } };
    assert.equal(tool, 'render_course_slide');
    renders.push(args);
    return { status: 'ok', data: { format: 'pptx', content_hash: 'hash', page_count: 2,
      page: args.slide, slide_number: args.slide } };
  }, { decodeImage: async raw => { decoded.push(raw.data.slide_number); return true; } });
  audit.addFile('c', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
  const f = audit.course('c').files['1'];
  await audit.read('c', f);
  assert.deepEqual(renders, [1, 2].map(slide => ({ connection_id: 'synthetic', file_id: 'opaque',
    slide, resolution: 'standard', expected_source_hash: 'hash' })));
  assert.deepEqual(decoded, [1, 2]);
  assert.equal(f.outcome, 'fully_read');
  assert.deepEqual(audit.state.events.filter(e => e.tool === 'render_course_slide').map(e => [e.page, e.resolution]),
    [[1, 'standard'], [2, 'standard']]);
});

for (const problem of ['denied', 'wrong_slide']) {
  test(`standard slide reader cannot establish coverage for ${problem}`, async () => {
    let rendered = 0;
    const { audit } = make(async (tool, args) => {
      if (tool === 'read_course_file') return { ...read, data: { ...read.data, format: 'pptx' } };
      assert.equal(tool, 'render_course_slide'); rendered++;
      return problem === 'denied'
        ? { status: 'permission_denied', data: { reason_code: 'RESOURCE_PERMISSION_DENIED' } }
        : { status: 'ok', data: { content_hash: 'hash', page_count: 2, page: args.slide, slide_number: 99 } };
    }, { decodeImage: async () => { throw new Error('Invalid evidence must not reach decoding'); } });
    audit.addFile('c', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
    const f = audit.course('c').files['1'];
    await audit.read('c', f);
    assert.equal(rendered, 1);
    assert.deepEqual(f.rendered, []);
    assert.equal(f.outcome, 'partial');
    assert.equal(f.visualReason, problem === 'denied' ? 'RESOURCE_PERMISSION_DENIED' : 'VISUAL_COVERAGE_INVALID');
  });
}

test('text-first phase remains pending until every native visual page decodes', async () => {
  const calls = [];
  const { audit } = make(async (tool, args) => {
    calls.push(tool);
    if (tool === 'read_course_file') return { ...read, data: { ...read.data, format: 'pdf' } };
    return { status: 'ok', data: { format: 'pdf', page: args.page, page_count: 2, content_hash: 'hash' } };
  }, { decodeImage: async () => true });
  audit.addFile('c', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
  const f = audit.course('c').files['1'];
  await audit.read('c', f, { render: false });
  assert.equal(f.outcome, 'pending');
  assert.equal(f.textDone, true);
  assert.deepEqual(calls, ['read_course_file']);
  assert.equal(audit.report().clean, false);
  await audit.read('c', f);
  assert.equal(f.outcome, 'fully_read');
  assert.deepEqual(f.rendered, [1, 2]);
  assert.deepEqual(calls, ['read_course_file', 'render_course_file_page', 'render_course_file_page']);
});

test('cumulative inventory failures retain their first operation and request ID', async () => {
  let n = 0;
  const { audit } = make(async () => {
    n++;
    return { status: 'partial_data', data: { files: [],
      inventory_operation: n === 1 ? 'files' : 'modules',
      inventory_reason_codes: { files: { reason_code: 'RESOURCE_PERMISSION_DENIED' } }
    }, meta: { request_id: 'request' + n, freshness: 'live', next_cursor: n === 1 ? 'cursor1' : null } };
  }, { resumableInventory: true });
  audit.course('course').inventoryFailures = [{ resource: 'files', reason: 'RESOURCE_PERMISSION_DENIED', request_id: 'old-request' }];
  await audit.inventory('course');
  assert.equal(n, 2);
  assert.deepEqual(audit.course('course').inventoryFailures, [{ resource: 'files',
    reason: 'RESOURCE_PERMISSION_DENIED', operation: 'files', request_id: 'request1', continuation_step: 0 }]);
  const annotations = audit.state.events.filter(e => e.record_type === 'inventory_failure_annotation');
  assert.equal(annotations.length, 1);
  assert.equal(annotations[0].request_id, 'request1');
  assert.equal(annotations[0].inventory_failures.length, 1);
  assert.ok(audit.state.events.filter(e => !e.record_type).every(e => e.inventory_failures === undefined));
});

test('text denial still exercises every independently authorized visual page and decodes images', async () => {
  const calls = [];
  const { audit } = make(async (tool, args) => {
    calls.push([tool, args.page]);
    if (tool === 'read_course_file') return { status: 'permission_denied', data: { reason_code: 'EGRESS_GOVERNANCE_MISSING' } };
    return { status: 'ok', data: { format: 'pdf', page: args.page, page_count: 3, content_hash: 'hash' }, testPage: args.page };
  }, { decodeImage: async raw => raw.testPage !== 2 });
  audit.addFile('course', { file_id: 'opaque', canvas_file_id: '1', type: 'application/pdf' }, 'inventory');
  const f = audit.course('course').files['1'];
  await audit.read('course', f);
  assert.deepEqual(calls, [['read_course_file', undefined], ['render_course_file_page', 1], ['render_course_file_page', 2], ['render_course_file_page', 3]]);
  assert.deepEqual(f.rendered, [1, 3]);
  assert.equal(f.visualStatus, 'partial');
  assert.equal(f.outcome, 'partial');
  assert.equal(f.textDone, false);
});

test('a page-specific visual failure does not skip later pages', async () => {
  const pages = [];
  const { audit } = make(async (tool, args) => {
    pages.push(args.page);
    if (args.page === 2) return { status: 'unsupported_feature', data: { reason_code: 'RENDER_PAGE_DIMENSIONS' } };
    return { status: 'ok', data: { format: 'pdf', page: args.page, page_count: 3, content_hash: 'hash' } };
  }, { decodeImage: async () => true });
  audit.addFile('course', { file_id: 'opaque', canvas_file_id: '1', type: 'application/pdf' }, 'inventory');
  const f = audit.course('course').files['1']; f.outcome = 'failed';
  await audit.visualAudit('course', f);
  assert.deepEqual(pages, [1, 2, 3]);
  assert.deepEqual(f.rendered, [1, 3]);
  assert.equal(f.outcome, 'partial');
});

test('visual permission denial stays blocked and never grants text coverage', async () => {
  const { audit } = make(async () => ({ status: 'permission_denied', data: { reason_code: 'EGRESS_GOVERNANCE_MISSING' } }));
  audit.addFile('course', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
  const f = audit.course('course').files['1']; f.outcome = 'failed';
  await audit.visualAudit('course', f);
  assert.equal(f.visualReason, 'EGRESS_GOVERNANCE_MISSING');
  assert.equal(f.outcome, 'failed');
  assert.deepEqual(f.rendered, []);
});

test('page-one render failure uses public metadata to continue later known pages', async () => {
  const calls = [];
  const { audit } = make(async (tool, args) => {
    calls.push([tool, args.page]);
    if (tool === 'get_file_extraction_status') return { status: 'ok', data: { format: 'pdf', page_count: 3, content_hash: 'hash' } };
    if (args.page === 1) return { status: 'unsupported_feature', data: { reason_code: 'RENDER_PAGE_DIMENSIONS' } };
    return { status: 'ok', data: { format: 'pdf', page: args.page, page_count: 3, content_hash: 'hash' } };
  }, { decodeImage: async () => true });
  audit.addFile('course', { file_id: 'opaque', canvas_file_id: '1', type: 'application/pdf' }, 'inventory');
  const f = audit.course('course').files['1']; f.outcome = 'failed';
  await audit.visualAudit('course', f);
  assert.deepEqual(calls, [['render_course_file_page', 1], ['get_file_extraction_status', undefined], ['render_course_file_page', 2], ['render_course_file_page', 3]]);
  assert.deepEqual(f.rendered, [2, 3]);
  assert.equal(f.outcome, 'partial');
});

test('interrupted discovery resumes after completed courses and retains provenance across versions', async () => {
  let saved, interrupted = false;
  const calls = [];
  const callTool = async (tool, args) => {
    if (tool === 'list_courses') return { status: 'ok', data: { courses: ['a', 'b'].map(id => ({ id, selected: true })) }, meta: { freshness: 'live', coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }] } };
    calls.push(args.course_id);
    return listing;
  };
  const { audit } = make(callTool, { save: async value => {
    saved = value;
    if (!interrupted && value.discovery?.completed.includes('a')) { interrupted = true; throw new Error('interrupt'); }
  } });
  await assert.rejects(audit.discover(), /interrupt/);
  const resumed = make(callTool, { state: saved }).audit;
  await resumed.discover();
  assert.deepEqual(calls, ['a', 'b']);
  resumed.addFile('a', { file_id: 'opaque', canvas_file_id: '1', source_version: 'v2', assignments: ['assignment1'], folders: ['folder1'] }, 'refresh');
  assert.deepEqual(resumed.course('a').files['1'].paths, ['file_inventory', 'module:m1', 'refresh', 'folder:folder1', 'assignment:assignment1']);
  assert.equal(resumed.course('a').files['1'].outcome, 'pending');
});

test('missing inventory branches never become empty or complete; stable ID dedup', async () => {
  const { audit } = make(async () => listing);
  await audit.inventory('course');
  assert.equal(Object.keys(audit.course('course').files).length, 1);
  assert.equal(audit.course('course').inventoryComplete, false);
  assert.ok(audit.course('course').gaps.includes('folders_incomplete'));
  assert.deepEqual(audit.course('course').files['1'].paths, ['file_inventory', 'module:m1']);
  assert.equal(audit.report().clean, false);
});
test('a continuation contradicts a complete flag and cannot silently disappear', async () => {
  const { audit } = make(async () => ({ ...listing,
    data: { ...listing.data, coverage: Object.fromEntries(['files', 'modules', 'folders', 'assignments'].map(k => [k, 'complete'])) },
    meta: { freshness: 'live', next_cursor: 'opaque-continuation' },
  }));
  await audit.inventory('course');
  assert.equal(audit.course('course').inventoryComplete, false);
  assert.ok(audit.course('course').gaps.includes('public_inventory_continuation_unavailable'));
});
test('public inventory pages checkpoint and resume without restarting earlier pages', async () => {
  let saved, stop = true; const calls = [];
  const coverage = Object.fromEntries(['files', 'modules', 'folders', 'assignments'].map(k => [k, 'complete']));
  const callTool = async (tool, args) => {
    calls.push(args.cursor || 'start');
    assert.equal(args.inventory_mode, 'resumable');
    const last = args.cursor === 'cursor2';
    return { status: last ? 'ok' : 'partial_data', meta: { freshness: 'live', next_cursor: last ? null : args.cursor ? 'cursor2' : 'cursor1' },
      data: { coverage: last ? coverage : { files: 'complete' }, page_identity: args.cursor || 'page0',
        files: args.cursor === 'cursor1' ? [] : [{ file_id: last ? 'two' : 'one', canvas_file_id: last ? '2' : '1', source_version: 'v1', folders: ['child'] }],
        folder_graph: args.cursor === 'cursor1' ? [{ id: 'child', parent_id: 'root' }, { id: 'root', parent_id: null }] : [],
      } };
  };
  const { audit } = make(callTool, { resumableInventory: true, save: async value => {
    saved = value;
    if (stop && value.courses.c?.inventoryResume?.cursor === 'cursor1') { stop = false; throw new Error('interruption'); }
  } });
  await assert.rejects(audit.inventory('c'), /interrupted/);
  const resumed = make(callTool, { state: saved, resumableInventory: true }).audit;
  await resumed.inventory('c');
  assert.deepEqual(calls, ['start', 'cursor1', 'cursor2']);
  assert.equal(resumed.course('c').inventoryComplete, true);
  assert.equal(Object.keys(resumed.course('c').files).length, 2);
  assert.ok(resumed.course('c').files['1'].paths.includes('folder:root'));
});

test('repeated terminal page identity cannot establish complete inventory', async () => {
  const coverage = Object.fromEntries(['files', 'modules', 'folders', 'assignments'].map(k => [k, 'complete']));
  let calls = 0;
  const { audit } = make(async () => ({ status: 'ok', meta: { freshness: 'live', next_cursor: ++calls === 1 ? 'cursor1' : null }, data: { files: [], coverage, page_identity: 'same' } }), { resumableInventory: true });
  await audit.inventory('c');
  assert.equal(audit.course('c').inventoryComplete, false);
  assert.ok(audit.course('c').gaps.includes('inventory_continuation_invalid_or_cyclic'));
});
test('sheet coverage and checkpoint omit contents, titles and URLs', async () => {
  const { audit, saved } = make(async () => read);
  audit.addFile('c', { canvas_file_id: '1', file_id: 'opaque', source_version: 'v1' }, 'assignment:a');
  await audit.read('c', audit.course('c').files['1']);
  assert.equal(audit.course('c').files['1'].outcome, 'fully_read');
  assert.doesNotMatch(JSON.stringify(saved()), /SECRET|https:|token=|"text":|sheet_name/);
});
test('one accessible sheet missing cannot count as fully read', async () => {
  const { audit } = make(async () => ({ ...read, data: { ...read.data, page_extraction: [{ page: 1 }] } }));
  audit.addFile('c', { canvas_file_id: '1', file_id: 'opaque' }, 'files');
  await audit.read('c', audit.course('c').files['1']);
  assert.equal(audit.course('c').files['1'].outcome, 'partial');
});
test('page-one success and a repeating continuation fail closed', async () => {
  const { audit } = make(async () => ({ ...read, data: { ...read.data,
    continuation: { file_id: 'opaque', expected_hash: 'hash', offset: 10, page_start: 1, page_end: 2 } } }));
  audit.addFile('c', { canvas_file_id: '1', file_id: 'opaque' }, 'files');
  await audit.read('c', audit.course('c').files['1']);
  assert.equal(audit.course('c').files['1'].reason, 'CONTINUATION_CYCLE');
});
test('visual success requires actual image decode for every page', async () => {
  let renders = 0;
  const { audit } = make(async tool => tool === 'read_course_file'
    ? { ...read, data: { ...read.data, format: 'pdf' } }
    : (renders++, { status: 'ok', data: { content_hash: 'hash', page: renders, page_count: 2 } }), { decodeImage: async () => false });
  audit.addFile('c', { canvas_file_id: '1', file_id: 'opaque' }, 'files');
  await audit.read('c', audit.course('c').files['1']);
  assert.equal(renders, 2);
  assert.equal(audit.course('c').files['1'].outcome, 'partial');
});
test('Retry-After exceeding wait budget causes a hold, never an early retry', async () => {
  let calls = 0;
  const { audit } = make(async () => (calls++, { status: 'retry_later', data: { retry_after_seconds: 180 } }));
  await audit.call('list_courses', {});
  assert.equal(calls, 1);
  assert.ok(audit.state.hold.retryAt > Date.now());
});
test('missing governance is a failure to establish permission, not a legitimate file denial', async () => {
  const { audit } = make(async () => ({}));
  for (const reason_code of ['EGRESS_GOVERNANCE_MISSING', 'EGRESS_CLASSIFICATION_UNKNOWN', 'STALE_SCOPE_SNAPSHOT']) {
    assert.equal(audit.classify({ status: 'permission_denied', data: { reason_code } }), 'failed');
  }
});

test('interruption resumes at saved continuation instead of reading page one again', async () => {
  let calls = 0;
  const { audit, saved } = make(async () => {
    calls++;
    if (calls > 1) return { status: 'permission_denied', data: { reason_code: 'EGRESS_GOVERNANCE_MISSING' } };
    return { ...read, data: { ...read.data, text: read.data.text.slice(0, 10), next_offset: 10, continuation:
      { file_id: 'opaque', expected_hash: 'hash', offset: 10, page_start: 1, page_end: 2 } } };
  });
  audit.addFile('c', { canvas_file_id: '1', file_id: 'opaque' }, 'files');
  await audit.read('c', audit.course('c').files['1']);
  let resumedOffset;
  const { audit: resumed } = make(async (tool, args) => {
    resumedOffset = args.offset;
    return { ...read, data: { ...read.data, offset: 10, text: read.data.text.slice(10) } };
  }, { state: saved() });
  await resumed.read('c', resumed.course('c').files['1']);
  assert.equal(resumedOffset, 10);
  assert.equal(resumed.course('c').files['1'].outcome, 'fully_read');
});

test('denied inventory never makes discovered file count equal a known course total', async () => {
  const { audit } = make(async () => ({ status: 'permission_denied', data: { reason_code: 'EGRESS_GOVERNANCE_MISSING' } }));
  await audit.inventory('c');
  assert.deepEqual(audit.report().rows[0], { course: 'c', inventoryComplete: false,
    discovered: 0, fully_read: 0, partial: 0, unsupported: 0, denied: 0, failed: 0, pending: 0 });
  assert.equal(audit.report().clean, false);
});

test('shared upstream throttling stops the entire sweep without probing later courses', async () => {
  let calls = 0;
  const { audit } = make(async () => (calls++, { status: 'partial_data',
    data: { reason_code: 'UPSTREAM_THROTTLED', retry_after_seconds: 3600 } }));
  audit.course('a'); audit.course('b');
  await audit.run();
  await audit.run();
  assert.equal(calls, 1);
  assert.ok(audit.state.hold.retryAt > Date.now());
  assert.equal(audit.report().clean, false);
});

test('text-only MCP envelopes retain reason codes and malformed responses halt', async () => {
  const { audit } = make(async () => ({ content: [{ type: 'text', text: JSON.stringify({
    status: 'retry_later', data: { reason_code: 'UPSTREAM_THROTTLED', retry_after_seconds: 99 },
    meta: { request_id: 'request1' }
  }) }] }));
  await audit.call('list_courses', {});
  assert.equal(audit.state.events[0].reason, 'UPSTREAM_THROTTLED');
  assert.equal(audit.state.events[0].request_id, 'request1');
  const { audit: malformed } = make(async () => ({ content: [{ type: 'text', text: 'private unstructured error' }] }));
  await malformed.call('list_courses', {});
  assert.equal(malformed.state.hold.reason, 'MALFORMED_TOOL_RESPONSE');
  assert.doesNotMatch(JSON.stringify(malformed.state), /private unstructured error/);
});

test('all page labels with an omitted text continuation still mean partial reading', async () => {
  const { audit } = make(async () => ({ ...read, data: { ...read.data, text: 'short' } }));
  audit.addFile('c', { canvas_file_id: '1', file_id: 'opaque' }, 'files');
  await audit.read('c', audit.course('c').files['1']);
  assert.equal(audit.course('c').files['1'].outcome, 'partial');
  assert.equal(audit.course('c').files['1'].reason, 'READ_CHARACTER_COVERAGE_GAP');
});

test('checkpoint connection binding prevents cross-account reuse', () => {
  assert.throws(() => make(async () => ({}), { state: {
    version: 1, connection: 'different', courses: {}, events: [],
  } }), /connection mismatch/);
});

test('fresh selected-course listing removes withdrawn course results', async () => {
  const { audit } = make(async () => ({ status: 'ok', data: { courses: [] }, meta: {
    freshness: 'live',
    coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }],
  } }));
  audit.course('withdrawn');
  await audit.discover();
  assert.deepEqual(audit.report().rows, []);
  assert.equal(audit.report().clean, false);
});

test('resume preserves completed failed attempts until explicit retry is requested', async () => {
  let reads = 0, visuals = 0;
  const { audit } = make(async tool => {
    if (tool === 'list_courses') return { status: 'ok', data: { courses: [{ id: 'c', selected: true }] }, meta: {
      coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }],
    } };
    if (tool === 'list_course_files') return listing;
    if (tool === 'render_course_file_page') {
      visuals++;
      return { status: 'permission_denied', data: { reason_code: 'EGRESS_GOVERNANCE_MISSING' } };
    }
    reads++; return read;
  });
  audit.addFile('c', listing.data.files[0], 'files');
  audit.course('c').files['1'].outcome = 'failed';
  await audit.run();
  assert.equal(reads, 0);
  assert.equal(visuals, 1);
  await audit.run({ retryFailed: true });
  assert.equal(reads, 1);
  assert.equal(visuals, 1);
});

test('explicit retry replaces old partial coverage with fresh complete evidence', async () => {
  let reads = 0;
  const { audit } = make(async tool => {
    if (tool === 'list_courses') return { status: 'ok', data: { courses: [{ id: 'c', selected: true }] }, meta: { freshness: 'live', coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }] } };
    if (tool === 'list_course_files') return listing;
    reads++;
    return reads === 1 ? { ...read, status: 'partial_data' } : read;
  });
  await audit.run();
  assert.equal(audit.course('c').files['1'].outcome, 'partial');
  await audit.run({ retryFailed: true });
  assert.equal(reads, 2);
  assert.equal(audit.course('c').files['1'].outcome, 'fully_read');
});

test('explicit failed-file retry rechecks its previously denied visual route', async () => {
  let visuals = 0;
  const denied = { status: 'permission_denied', data: { reason_code: 'EGRESS_GOVERNANCE_MISSING' } };
  const { audit } = make(async tool => {
    if (tool === 'list_courses') return { status: 'ok', data: { courses: [{ id: 'c', selected: true }] }, meta: { freshness: 'live', coverage: [{ resource: 'courses', state: 'complete', pagination_complete: true }] } };
    if (tool === 'list_course_files') return listing;
    if (tool === 'read_course_file') return denied;
    visuals++;
    return visuals === 1 ? denied : { status: 'ok', data: { format: 'pdf', page: 1, page_count: 1, content_hash: 'hash' } };
  }, { decodeImage: async () => true });
  await audit.run();
  assert.equal(audit.course('c').files['1'].outcome, 'failed');
  await audit.run({ retryFailed: true });
  assert.equal(visuals, 2);
  assert.equal(audit.course('c').files['1'].visualStatus, 'complete');
  assert.equal(audit.course('c').files['1'].outcome, 'partial');
});

test('decoded pixels with the wrong source hash cannot establish complete reading', async () => {
  const { audit } = make(async tool => tool === 'read_course_file'
    ? { status: 'ok', data: { format: 'pdf', content_hash: 'expected', page_count: 1,
      offset: 0, total_extracted_characters: 1, next_offset: null, text: 'x',
      coverage: 'text_only', page_extraction: [{ page: 1 }] } }
    : { status: 'ok', data: { content_hash: 'different', page: 1, page_count: 1 } },
  { decodeImage: async () => true });
  audit.addFile('course', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
  const f = audit.course('course').files['1'];
  await audit.read('course', f);
  assert.equal(f.outcome, 'partial');
  assert.deepEqual(f.rendered, []);
});

test('unique inventory continuations exhaust a resumable per-run request budget', async () => {
  let calls = 0;
  const { audit } = make(async () => {
    calls++;
    if (calls > 3) throw new Error('unbounded crawl');
    return { status: 'partial_data', data: { files: [] },
      meta: { freshness: 'live', next_cursor: 'cursor' + calls } };
  }, { resumableInventory: true, maxInventoryPagesPerRun: 2 });
  await audit.inventory('course');
  assert.equal(calls, 2);
  assert.equal(audit.state.hold.reason, 'AUDIT_REQUEST_BUDGET');
  assert.equal(audit.course('course').inventoryResume.cursor, 'cursor2');
  assert.equal(audit.course('course').inventoryResume.done, false);
  assert.equal(audit.course('course').inventoryComplete, false);
});

test('inventory budget continuation resumes without replaying earlier pages', async () => {
  const cursors = [];
  const { audit, saved } = make(async (tool, args) => {
    cursors.push(args.cursor || null);
    return { status: 'partial_data', data: { files: [] }, meta: { freshness: 'live', next_cursor: 'cursor1' } };
  }, { resumableInventory: true, maxInventoryPagesPerRun: 1 });
  await audit.inventory('course');
  const state = saved();
  state.hold = null;
  const resumed = make(async (tool, args) => {
    cursors.push(args.cursor);
    return { status: 'ok', data: { files: [], coverage: { files: 'complete', folders: 'complete', modules: 'complete', assignments: 'complete' } }, meta: { freshness: 'live' } };
  }, { state, resumableInventory: true, maxInventoryPagesPerRun: 1 }).audit;
  await resumed.inventory('course');
  assert.deepEqual(cursors, [null, 'cursor1']);
  assert.equal(resumed.course('course').inventoryComplete, true);
});

for (const mismatch of [{ page: 2 }, { page_count: 2 }, { content_hash: null }]) {
  test('successful text read still validates rendered identity ' + JSON.stringify(mismatch), async () => {
    const { audit } = make(async tool => tool === 'read_course_file'
      ? { status: 'ok', data: { format: 'pdf', content_hash: 'hash', page_count: 1,
        offset: 0, total_extracted_characters: 1, next_offset: null, text: 'x',
        coverage: 'text_only', page_extraction: [{ page: 1 }] } }
      : { status: 'ok', data: { content_hash: 'hash', page: 1, page_count: 1, ...mismatch } },
    { decodeImage: async () => true });
    audit.addFile('course', { file_id: 'opaque', canvas_file_id: '1' }, 'inventory');
    const f = audit.course('course').files['1'];
    await audit.read('course', f);
    assert.equal(f.outcome, 'partial');
    assert.deepEqual(f.rendered, []);
  });
}

test('empty cyclic folder branches cannot establish complete discovery', async () => {
  const { audit } = make(async () => ({ status: 'ok',
    data: { files: [], coverage: { files: 'complete', folders: 'complete', modules: 'complete', assignments: 'complete' },
      folder_graph: [{ id: 'a', parent_id: 'b' }, { id: 'b', parent_id: 'a' }] },
    meta: { freshness: 'live' } }));
  await audit.inventory('course');
  assert.equal(audit.course('course').inventoryComplete, false);
  assert.ok(audit.course('course').gaps.includes('folder_cycle'));
});

for (const reason of ['LOCAL_REQUEST_BUSY', 'UPSTREAM_CIRCUIT_OPEN', 'AUTHORIZATION_BUSY']) {
  test('shared busy diagnostic halts the sweep: ' + reason, async () => {
    let calls = 0;
    const { audit } = make(async () => (calls++, { status: 'retry_later', data: { reason_code: reason } }));
    await audit.call('list_courses', {});
    assert.equal(calls, 1);
    assert.equal(audit.state.hold.reason, reason);
    assert.equal(audit.report().clean, false);
  });
}

test('native MCP error envelopes are transport failures, not successful empty results', async () => {
  const { audit, saved } = make(async () => ({ isError: true, content: [{ type: 'text', text: 'PRIVATE provider transport details' }] }));
  await audit.call('list_course_files', { course_id: 'course' });
  assert.equal(audit.state.hold.reason, 'TRANSPORT_FAILURE');
  assert.equal(audit.state.events.at(-1).reason, 'TRANSPORT_FAILURE');
  assert.equal(JSON.stringify(saved()).includes('PRIVATE'), false);
});
