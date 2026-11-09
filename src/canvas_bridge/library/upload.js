/* Same-origin authenticated selection. Source text never enters executable HTML. */
const style=document.createElement('style');style.textContent='[hidden]{display:none!important}button{margin:4px 4px 4px 0}button:disabled{background:#71847f;cursor:default}details{margin-top:16px}summary{cursor:pointer;font-weight:600;padding:8px 0}progress{max-width:100%}';document.head.append(style);
const $ = id => document.getElementById(id);
let receipt = null, pendingRequest = null, pendingPath = null, selectedFiles = [], stopped = false, running = false, nextCursor = null;
let activeFilters = {};
const status = (text, focus=false) => { $('status').textContent = text; if(focus)$('status').focus(); };
async function api(path, method = 'GET', body, headers = {}) {
  const r = await fetch(path, {method, credentials: 'same-origin', headers: {'X-Bridge-CSRF': libraryConfig.csrf, ...(body && !(body instanceof Blob) ? {'Content-Type': 'application/json'} : {}), ...headers}, body: body instanceof Blob ? body : body === undefined ? undefined : JSON.stringify(body)});
  const value = await r.json();
  if (!r.ok) throw new Error(`${value.reason_code}: ${value.next_action || 'Refresh the library.'}`);
  return value;
}
async function hash(blob) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))].map(x => x.toString(16).padStart(2, '0')).join('');
}
function manifest() {
  const channels = [...document.querySelectorAll('.channel:checked')].map(x => x.value);
  return {schema_version: 'library-intake-request-1', authorization_action_id: libraryConfig.action, idempotency_key: crypto.randomUUID(), transfer_mode: 'browser_bytes', files: selectedFiles.map((f,i) => ({selection_id: String(i), file_name: f.name, declared_bytes: f.size, maximum_bytes: f.size})), collection_id: $('collection').value || null, retention: $('retention').value === 'until_deleted' ? {mode:'until_deleted'} : {mode:'expires_at', expires_at:new Date($('expiry').value).toISOString()}, allow_processing:$('processing').checked, purpose:$('purpose').value, recipient_grants: channels.length ? [{recipient_profile_id:libraryConfig.profile, channels}] : []};
}
$('files').addEventListener('change', () => {
  $('selection').replaceChildren();
  for (const f of $('files').files) {const li=document.createElement('li');li.textContent=`${f.name} — ${f.size.toLocaleString()} bytes`; $('selection').append(li);}
});
async function transfer() {
  running = true; stopped = false; $('save').disabled=true; $('cancel').disabled=false; $('retry').disabled=true;
  const fields = [...$('library-upload').querySelectorAll('input,select')].map(el=>[el,el.disabled]);
  fields.forEach(([el])=>el.disabled=true);$('progress').value=0;$('library-upload').setAttribute('aria-busy','true');
  try {
    if(!receipt && pendingRequest) receipt=await api(pendingPath,'POST',pendingRequest);
    receipt = await api(`/api/library/intakes/${receipt.intake_id}`);
    const total = selectedFiles.reduce((n,f) => n+f.size,0); $('progress').max = total;
    for (const row of receipt.files) {
      if (['published','rejected','cancelled','expired','failed'].includes(row.state)) continue;
      const f=selectedFiles[Number(row.client_selection_id)];
      for(let offset=row.offset;offset<f.size;offset+=libraryConfig.chunk){
        if(stopped) break;
        const blob=f.slice(offset,offset+libraryConfig.chunk);
        const checksum=await hash(blob);
        const result=await api(`/api/library/intakes/${receipt.intake_id}/files/${row.selection_id}/chunks`,'PUT',blob,{'Upload-Offset':String(offset),'X-Chunk-SHA256':checksum});
        row.offset=result.offset;
        const transferred=receipt.files.reduce((n,x)=>n+x.offset,0);$('progress').value=transferred;status(`${transferred.toLocaleString()} of ${total.toLocaleString()} bytes transferred.`);
      }
      if(stopped) break;
      status('Validating original bytes. Extraction runs separately after storage.');
      receipt=await api(`/api/library/intakes/${receipt.intake_id}/complete`,'POST',{hashes:{[row.selection_id]:await hash(f)}});
    }
    if(stopped){receipt=await api(`/api/library/intakes/${receipt.intake_id}`);receipt=await api(`/api/library/intakes/${receipt.intake_id}`,'DELETE',{expected_revision:receipt.revision});}
    const saved=receipt.files.flatMap(x=>x.items || []);
    const outcomes=receipt.files.map(x=>`${selectedFiles[Number(x.client_selection_id)]?.name || 'File'}: ${x.state}${x.reason_code ? ' ('+x.reason_code+')' : ''}`);
    status(`${outcomes.join('; ')}. Saved IDs: ${saved.map(x=>x.document_id).join(', ') || 'none'}. Receipt: ${receipt.intake_id}. Published files remain after cancellation.`,true);
    await loadItems();
  } catch(e) {status(e.message + ` Receipt: ${receipt?.intake_id || 'not created'}. Retry checks the stored offset.`);$('status').focus();}
  finally {running=false;fields.forEach(([el,disabled])=>el.disabled=disabled);$('library-upload').removeAttribute('aria-busy');$('save').disabled=false;$('cancel').disabled=true;$('retry').disabled=!receipt && !pendingRequest;}
}
$('library-upload').addEventListener('submit', async event => {
  event.preventDefault(); if(running)return; selectedFiles=[...$('files').files];
  if(!selectedFiles.length || selectedFiles.length>20){status('Select between one and twenty files.');return;}
  try {pendingRequest=manifest();pendingPath='/api/library/intakes';receipt=null;await transfer();}catch(e){status(e.message,true);$('status').focus();}
});
$('retry').addEventListener('click',transfer);
$('cancel').addEventListener('click',()=>{stopped=true;status('Finishing the current bounded chunk, then cancelling unfinished files.');});
window.addEventListener('beforeunload',e=>{if(running){e.preventDefault();e.returnValue='';}});
function control(label, value='') {const el=document.createElement('label');el.textContent=label;const input=document.createElement('input');input.type='text';input.value=value;el.append(input);return [el,input];}
async function loadItems(append=false) {
  const query=new URLSearchParams({limit:'20',...activeFilters});
  if(append && nextCursor)query.set('cursor',nextCursor);
  const result=await api('/api/library/items?'+query.toString());
  const {quota}=await api('/api/library/status');
  $('storage-quota').textContent=`Storage: ${quota.committed_bytes.toLocaleString()} bytes used; ${quota.reserved_bytes.toLocaleString()} reserved; ${quota.maximum_bytes.toLocaleString()} allowed.`;
  if(!append)$('items').replaceChildren();
  for(const item of result.items){
    const section=document.createElement('section');section.className='card';
    const heading=document.createElement('h3');heading.textContent=item.title;section.append(heading);
    const info=document.createElement('p');info.textContent=`${item.size_bytes} bytes · ${item.processing_state} · ${item.document_id}`;section.append(info);
    if(item.processing_state==='failed' && item.sharing.allow_processing){const retryProcessing=document.createElement('button');retryProcessing.type='button';retryProcessing.textContent='Retry failed extraction with existing permissions';retryProcessing.onclick=async()=>{try{await api(`/api/library/items/${item.item_id}/retry-processing`,'POST',{expected_version_id:item.version_id,expected_revision:item.metadata_revision,expected_permission_revision:item.permission_revision});await loadItems();status('Extraction queued with the existing permissions.',true);}catch(e){status(e.message,true);}};section.append(retryProcessing);}
    const a=document.createElement('a');a.href=`/api/library/items/${item.item_id}/versions/${item.version_id}/original`;a.textContent='Download original';section.append(a);
    const controls=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Manage file';controls.append(summary);section.append(controls);
    const [titleLabel,title]=control('Title',item.title), [tagsLabel,tags]=control('Tags (comma separated)',item.tags.join(', ')), [collectionLabel,collection]=control('Collection',item.collection_id || '');controls.append(titleLabel,tagsLabel,collectionLabel);
    const update=document.createElement('button');update.textContent='Save metadata';update.type='button';update.onclick=async()=>{try{await api(`/api/library/items/${item.item_id}`,'PATCH',{expected_revision:item.metadata_revision,title:title.value,tags:tags.value.split(',').map(x=>x.trim()).filter(Boolean),collection_id:collection.value || null});await loadItems();status('Metadata saved.',true);}catch(e){status(e.message,true);}};controls.append(update);
    const revoke=document.createElement('button');revoke.type='button';revoke.textContent='Revoke all sharing and processing';revoke.onclick=async()=>{try{await api(`/api/library/items/${item.item_id}/grants`,'POST',{expected_version_id:item.version_id,expected_permission_revision:item.permission_revision,allow_processing:false,purpose:'document_reading',recipient_grants:[]});await loadItems();status('Sharing and processing revoked. Owner original download remains available.',true);}catch(e){status(e.message,true);}};controls.append(revoke);
    const grants=document.createElement('fieldset'), legend=document.createElement('legend');legend.textContent='Processing and sharing for this file';grants.append(legend);
    const processingLabel=document.createElement('label'), processing=document.createElement('input');processing.type='checkbox';processing.checked=item.sharing.allow_processing;processingLabel.append(processing,document.createTextNode(' Allow local extraction and indexing'));grants.append(processingLabel);
    const purposeLabel=document.createElement('label');purposeLabel.textContent='Purpose';const purpose=$('purpose').cloneNode(true);purpose.removeAttribute('id');purpose.disabled=false;purpose.value=item.sharing.purpose;purposeLabel.append(purpose);grants.append(purposeLabel);
    const checkboxes=[];
    for(const channel of ['metadata','text','visual','original']){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=channel;input.checked=item.sharing.channels.includes(channel);input.disabled=!libraryConfig.profile || !libraryConfig.channels.includes(channel);label.append(input,document.createTextNode(' Share '+channel+' with '+(libraryConfig.profile || 'no configured recipient')));grants.append(label);checkboxes.push(input);}
    const saveGrants=document.createElement('button');saveGrants.type='button';saveGrants.textContent='Save these processing and sharing permissions';saveGrants.onclick=async()=>{try{const channels=checkboxes.filter(x=>x.checked).map(x=>x.value);await api(`/api/library/items/${item.item_id}/grants`,'POST',{expected_version_id:item.version_id,expected_permission_revision:item.permission_revision,allow_processing:processing.checked,purpose:purpose.value,recipient_grants:channels.length?[{recipient_profile_id:libraryConfig.profile,channels}]:[]});await loadItems();status('The reviewed permissions were saved for this exact file.',true);}catch(e){status(e.message,true);}};grants.append(saveGrants);controls.append(grants);
    const replaceLabel=document.createElement('label');replaceLabel.textContent='Replacement file (retains at most five versions; superseded versions expire within 30 days)';const replacement=document.createElement('input');replacement.type='file';replacement.accept='.pdf,.docx,.pptx,.xlsx,.txt,.md,.png,.jpg,.jpeg';replaceLabel.append(replacement);controls.append(replaceLabel);
    const replaceConsent=document.createElement('label'),replaceCheck=document.createElement('input');replaceCheck.type='checkbox';replaceConsent.append(replaceCheck,document.createTextNode(' I have permission to save this replacement with the retention and sharing choices shown above. Existing rights can only narrow during replacement.'));controls.append(replaceConsent);
    const replaceButton=document.createElement('button');replaceButton.type='button';replaceButton.textContent='Save replacement version';replaceButton.onclick=async()=>{if(running)return;if(!replacement.files[0]||!replaceCheck.checked){status('Select the replacement file and its permission checkbox.');return;}try{selectedFiles=[replacement.files[0]];const value=manifest();value.allow_processing=processing.checked;value.purpose=purpose.value;const channels=checkboxes.filter(x=>x.checked).map(x=>x.value);value.recipient_grants=channels.length?[{recipient_profile_id:libraryConfig.profile,channels}]:[];pendingPath=`/api/library/items/${item.item_id}/versions`;pendingRequest={expected_version_id:item.version_id,expected_revision:item.metadata_revision,expected_permission_revision:item.permission_revision,selection:value};receipt=null;await transfer();}catch(e){status(e.message,true);}};controls.append(replaceButton);
    const exportButton=document.createElement('button');exportButton.type='button';exportButton.textContent='Export file and manifest';exportButton.onclick=async()=>{try{const out=await api('/api/library/exports','POST',{versions:[item.version_id],idempotency_key:crypto.randomUUID()});location.assign(`/api/library/exports/${out.export_id}`);}catch(e){status(e.message,true);}};controls.append(exportButton);
    const confirm=document.createElement('label'), check=document.createElement('input');check.type='checkbox';confirm.append(check,document.createTextNode(' I want to delete this file and all its versions from Bridge.'));controls.append(confirm);
    const remove=document.createElement('button');remove.type='button';remove.textContent='Delete file';remove.className='danger';remove.onclick=async()=>{if(!check.checked){status('Select the deletion checkbox for this file first.');return;}try{const out=await api(`/api/library/items/${item.item_id}`,'DELETE',{expected_version_id:item.version_id,expected_revision:item.metadata_revision,expected_permission_revision:item.permission_revision});status(`Access ${out.access}; active store ${out.active_store}; backup expiry ${out.backup_expiry}.`,true);await loadItems();}catch(e){status(e.message,true);}};controls.append(remove);
    $('items').append(section);
  }
  nextCursor=result.next_cursor;$('more').hidden=!nextCursor;
  const count=$('items').children.length;$('list-status').textContent=`${count} file${count===1?'':'s'} shown${nextCursor ? '; more available' : ''}.`;
}
$('library-filter').addEventListener('submit',event=>{event.preventDefault();activeFilters={};for(const key of ['query','tag','collection']){const value=$('filter-'+key).value.trim();if(value)activeFilters[key]=value;}loadItems().catch(e=>status(e.message,true));});
$('clear-filter').addEventListener('click',()=>{activeFilters={};$('library-filter').reset();loadItems().catch(e=>status(e.message,true));});
$('more').addEventListener('click',()=>loadItems(true).catch(e=>status(e.message)));
loadItems().catch(e=>status(e.message));
