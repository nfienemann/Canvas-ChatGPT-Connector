import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canvas_bridge.visual_ui import PAGE_URI


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "denied",
        "hash",
        "upload",
        "missing_helpers",
        "standard",
        "connect",
        "message",
        "content_image",
        "initial_no_image",
        "oversize",
        "changed",
        "missing_image",
    ],
)
@pytest.mark.parametrize("kind", ["pdf", "pptx", "pptx_slide"])
def test_T12_T13_page_reader_image_context_requires_fresh_access(failure, kind):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node runtime needed for the native UI bridge contract")
    script = Path("ui/page-reader/reader.js").read_text(encoding="utf-8").split("\n", 1)[1]
    harness = (
        r"""
import vm from "node:vm";
import assert from "node:assert/strict";
import {webcrypto, createHash} from "node:crypto";
const failure=FAILURE;
const elements={};
for(const key of ['status','read','title','page']) elements[key]={disabled:true,addEventListener:(event,fn)=>elements[key][event]=fn};
const bytes=Buffer.from('synthetic-png-test-bytes');
const imageHash=createHash('sha256').update(bytes).digest('hex');
const result={status:'ok',data:{page:1,page_count:1,render_receipt:'receipt',content_hash:'a'.repeat(64),source_version:'v1',image_hash:imageHash,rotation:0},sources:[{locator:'PDF page 1'}]};
const kind=KIND;
if(kind==='pptx'||kind==='pptx_slide') {delete result.data.render_receipt;result.data.visual_kind='pptx_picture';result.data.object_index=5;result.data.image_locator='Slide 1, object 5';}
if(kind==='pptx_slide') {result.data.visual_kind='pptx_slide';delete result.data.object_index;}
const meta={canvas_bridge_page:{png:bytes.toString('base64')}};
const calls=[],uploads=[],messages=[],states=[];
const response={structuredContent:result,_meta:meta};
if(failure==='content_image') {delete response._meta;response.content=[{type:'image',mimeType:'image/png',data:meta.canvas_bridge_page.png}]}
if(failure==='missing_image') delete response._meta;
if(failure==='oversize') meta.canvas_bridge_page.png='a'.repeat(1733337);

const api={
 toolInput:{connection_id:'mine',file_id:'selected'},toolOutput:result,
 toolResponseMetadata:{mcp_tool_result:failure==='initial_no_image'?{structuredContent:result}:response},
 callTool:async(name,args)=>{calls.push({name,args});return failure==='denied'?{structuredContent:{status:'permission_denied'}}:failure==='changed'?{structuredContent:{...result,data:{...result.data,content_hash:'c'.repeat(64)}},_meta:meta}:response},
 uploadFile:async(file,options)=>{uploads.push({file,options});if(failure==='upload') throw Error('unavailable');return {fileId:'file_owned'}},
 setWidgetState:async(state)=>{states.push(state);api.widgetState=state},
 sendFollowUpMessage:async(message)=>messages.push(message),
};
if(failure==='missing_helpers') delete api.uploadFile;
if(failure==='hash') result.data.image_hash='b'.repeat(64);
class App {
 constructor(){}
 getHostCapabilities(){return {serverTools:{},message:{text:{}},updateModelContext:failure==='standard'||failure==='message'?{image:{}}:{}}}
 async connect(){if(failure==='connect')throw Error('offline');this.ontoolinput({arguments:api.toolInput});this.ontoolresult(api.toolResponseMetadata.mcp_tool_result);}
 async callServerTool({name,arguments:args}){return api.callTool(name,args)}
 async updateModelContext(value){states.push(value)}
 async sendMessage(value){messages.push(value);return {isError:failure==='message'}}
}
const context={App,window:{openai:api,addEventListener(){}},document:{getElementById:id=>elements[id]},
 Uint8Array,crypto:webcrypto,File,atob,Error};
vm.runInNewContext(SOURCE,context);
await new Promise(resolve=>setImmediate(resolve));
if(failure==='missing_helpers'||failure==='connect') {assert.equal(elements.read.disabled,true);process.exit(0);}
await elements.read.click();
assert.equal(calls.length,1);assert.equal(calls[0].args.expected_hash,'a'.repeat(64));
assert.equal(calls[0].name,kind==='pptx_slide'?'render_course_slide':kind==='pptx'?'read_course_slide_image':'render_course_file_page');
if(kind==='pptx') {assert.equal(calls[0].args.object_index,5);assert.equal(calls[0].args.slide,1);assert.equal(elements.read.textContent,'Read image in ChatGPT');}
if(kind==='pptx_slide') {assert.equal(calls[0].args.slide,1);assert.equal(calls[0].args.object_index,undefined);assert.equal(elements.read.textContent,'Read slide in ChatGPT');}
if(failure==='standard'||failure==='message') {
 assert.equal(uploads.length,0);assert.equal(states[0].content[0].type,'image');
 assert.equal(states[0].content[0].data,meta.canvas_bridge_page.png);
 assert.equal(messages.length,1);
 assert.equal(elements.status.textContent.includes('could not'),failure==='message');
}
else if(failure && !['content_image','initial_no_image'].includes(failure)){assert.equal(messages.length,0);assert.equal(states.length,0);}
else {
 assert.equal(uploads.length,1);assert.equal(uploads[0].file.type,'image/png');
 assert.equal(uploads[0].options.library,false);
 assert.equal(states[0].imageIds[0],'file_owned');
 assert.equal(states[0].modelContent.interpretation_status,'not_yet_interpreted');
 assert.equal(messages.length,1);
 await elements.read.click();assert.equal(uploads.length,1);assert.equal(calls.length,2);
}
""".replace("FAILURE", json.dumps(failure))
        .replace("KIND", json.dumps(kind))
        .replace("SOURCE", json.dumps(script))
    )
    run = subprocess.run(  # noqa: S603 - fixed trusted unit harness with synthetic data only.
        [node, "--input-type=module"], input=harness, text=True, capture_output=True, timeout=15
    )
    assert run.returncode == 0, run.stderr


async def test_T12_reader_resource_is_static_and_has_no_external_origins(settings, bridge):
    from canvas_bridge.app import create_app

    server = create_app(settings, bridge).state.mcp
    template = list(await server.read_resource(PAGE_URI))[0]
    assert template.mime_type == "text/html;profile=mcp-app"
    assert "uploadFile" in template.content and "imageIds" in template.content
    assert "render_receipt" in template.content
    assert template.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["render_course_file_page"].meta["ui"]["resourceUri"] == PAGE_URI
    assert tools["read_course_slide_image"].meta["ui"]["resourceUri"] == PAGE_URI
    assert tools["render_course_slide"].meta["ui"]["resourceUri"] == PAGE_URI


async def test_T13_outbound_library_logs_do_not_expose_signed_urls(caplog):
    import logging

    import httpx

    from canvas_bridge.network import public_client

    caplog.set_level(logging.DEBUG)
    client = public_client()
    await client.aclose()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as mock:
        await mock.get("https://synthetic.example/file?signature=private-test-only")
    logging.getLogger("httpcore.connection").debug("private-wire-header")
    logging.getLogger("canvas_bridge").warning("safe failure type")
    assert "private-test-only" not in caplog.text
    assert "private-wire-header" not in caplog.text
    assert "safe failure type" in caplog.text
