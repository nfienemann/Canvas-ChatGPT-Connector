"""Real MCP transport and native component contract; not a ChatGPT UI claim."""

import base64
import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.file_delivery_ui import DOWNLOAD_URI
from tests.test_file_delivery import deterministic_workbook
from tests.test_file_delivery import original as original
from tests.test_mcp_contract import running as running


@pytest.mark.contract
async def test_mcp_original_tool_and_private_payload(
    running, token_factory, seeded, original, bridge, caplog
):
    _, file, data = original
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token_factory()}) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                negotiated = await session.initialize()
                assert negotiated.protocolVersion == "2025-11-25"
                catalog = {tool.name: tool for tool in (await session.list_tools()).tools}
                tool = catalog["prepare_course_file_download"]
                assert set(tool.inputSchema["required"]) == {"connection_id", "file_id"}
                assert set(tool.inputSchema["properties"]) == {
                    "connection_id",
                    "file_id",
                    "expected_source_version",
                    "expected_bytes_sha256",
                }
                assert catalog["get_course_file_download_payload"].meta["ui"]["visibility"] == [
                    "app"
                ]
                assert tool.meta["ui"]["resourceUri"] == DOWNLOAD_URI
                ui = await session.read_resource(DOWNLOAD_URI)
                assert "downloadFile" in ui.contents[0].text
                assert "uploadFile" not in ui.contents[0].text
                prepared = await session.call_tool(
                    "prepare_course_file_download", {"connection_id": seeded, "file_id": file}
                )
                assert prepared.structuredContent["status"] == "ok"
                result = prepared.structuredContent["data"]
                assert result["bytes_sha256"] == hashlib.sha256(data).hexdigest()
                payload = await session.call_tool(
                    "get_course_file_download_payload",
                    {"connection_id": seeded, "delivery_id": result["delivery_id"]},
                )
                private = payload.meta["canvas_bridge_download"]
                assert base64.b64decode(private["resource"]["resource"]["blob"]) == data
                public = json.dumps(payload.structuredContent) + "".join(
                    c.text for c in payload.content
                )
                assert private["external_url"] not in public
                assert private["resource"]["resource"]["blob"] not in public
                assert "blob" not in public
                # No authentication headers are needed for possession-based redemption.
                async with httpx.AsyncClient() as downloader:
                    output = await downloader.get(private["external_url"])
                    assert output.content == data
                    assert (
                        await downloader.get(
                            running + "/course-file-download/" + result["delivery_id"]
                        )
                    ).status_code == 403
                    assert (
                        await downloader.get(
                            running + "/course-file-download/" + result["bytes_sha256"]
                        )
                    ).status_code == 403
                caplog.set_level(logging.INFO, logger="uvicorn.access")
                logging.getLogger("uvicorn.access").info("GET %s", private["external_url"])
                assert private["external_url"] not in caplog.text
                for guards in (
                    {"expected_bytes_sha256": "0" * 64},
                    {"expected_source_version": "0" * 64},
                ):
                    failed = await session.call_tool(
                        "prepare_course_file_download",
                        {"connection_id": seeded, "file_id": file, **guards},
                    )
                    assert failed.structuredContent["data"]["reason_code"] in {
                        "SOURCE_CHANGED",
                        "INTEGRITY_MISMATCH",
                    }


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "unsupported",
        "rejected",
        "timeout",
        "denied",
        "hash",
        "changed",
        "connect",
        "large",
        "fresh",
    ],
)
def test_component_download_contract_and_byte_identity(failure):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for native component contract tests")
    source = Path("ui/page-reader/download.js").read_text(encoding="utf-8").split("\n", 1)[1]
    fixture = base64.b64encode(deterministic_workbook()).decode()
    harness = (
        r"""
import vm from "node:vm";
import assert from "node:assert/strict";
import {webcrypto,createHash} from "node:crypto";
const failure=FAILURE, bytes=Buffer.from(FIXTURE,"base64");
const elements={};
for(const key of ["title","details","download","external","fresh","canvas","status"])
 elements[key]={disabled:true,hidden:key==='external',addEventListener:(event,fn)=>elements[key][event]=fn};
const data={delivery_id:'issued',file_id:'file',course_name:'Synthetic course',filename:'Synthetic PCR Δ.xlsx',byte_size:bytes.length,bytes_sha256:createHash('sha256').update(bytes).digest('hex'),source_url:'https://canvas.fixture.invalid/course/file'};
const result={status:'ok',data};
const resource=failure==='large'?{type:'resource_link',name:data.filename,uri:'https://delivery.fixture.invalid/cap'}:{type:'resource',resource:{uri:'canvas-file://delivery/issued/Synthetic%20PCR%20%CE%94.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',blob:bytes.toString('base64')}};
const privateData={resource,external_url:'https://delivery.fixture.invalid/cap'};
const calls=[],handoffs=[],links=[];
class App {
 async connect(){if(failure==='connect')throw Error('unavailable'); this.ontoolinput({arguments:{connection_id:'mine',file_id:'file'}}); this.ontoolresult({structuredContent:result});}
 getHostCapabilities(){return failure==='unsupported'?{}:{downloadFile:{},serverTools:{}};}
 async callServerTool(request){
  calls.push(request);
  if(request.name==='prepare_course_file_download')return {structuredContent:{status:'ok',data:{...data,delivery_id:'fresh'}}};
  if(failure==='denied')return {structuredContent:{status:'permission_denied',data:{reason_code:'DELIVERY_EXPIRED'}}};
  return {structuredContent:{status:'ok',data:{...data,...(failure==='hash'?{bytes_sha256:'0'.repeat(64)}:failure==='changed'?{delivery_id:'different'}:{})}},_meta:{canvas_bridge_download:privateData}};
 }
 async downloadFile(request){
  handoffs.push(request);
  if(failure==='timeout')throw Error('request_timeout');
  if(request.contents[0].type==='resource')assert.deepEqual(Buffer.from(request.contents[0].resource.blob,'base64'),bytes);
  else assert.equal(request.contents[0].uri,privateData.external_url);
  return {isError:failure==='rejected'};
 }
 async openLink(request){links.push(request);return {};}
}
vm.runInNewContext(SOURCE,{App,window:{addEventListener(){}},document:{getElementById:key=>elements[key]},Uint8Array,atob,crypto:webcrypto,Intl,Error});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(handoffs.length,0);assert.equal(calls.length,0);assert.equal(links.length,0);
if(failure==='connect'){assert.equal(elements.download.disabled,true);process.exit(0);}
if(failure==='fresh'){
 await elements.fresh.click();assert.equal(calls[0].name,'prepare_course_file_download');assert.equal(handoffs.length,0);process.exit(0);
}
await elements.download.click();
if(failure==='unsupported'){
 assert.equal(handoffs.length,0);assert.equal(calls.length,0);assert.equal(elements.external.hidden,false);
 assert.ok(elements.status.textContent.includes('private, expiring external'));
 await elements.external.click();assert.equal(links.length,1);assert.equal(calls.length,1);
}else if(['denied','hash','changed'].includes(failure)){
 assert.equal(handoffs.length,0);assert.ok(elements.status.textContent.includes('fresh download'));
}else{
 assert.equal(calls.length,1);assert.equal(handoffs.length,1);
 if(failure==='rejected')assert.ok(elements.status.textContent.includes('not completed'));
 else if(failure==='timeout')assert.ok(elements.status.textContent.includes('outcome unknown'));
 else assert.ok(elements.status.textContent.includes('request accepted'));
}
assert.equal(elements.download.disabled,false);
""".replace("FAILURE", json.dumps(failure))
        .replace("FIXTURE", json.dumps(fixture))
        .replace("SOURCE", json.dumps(source))
    )
    run = subprocess.run(  # noqa: S603 - fixed synthetic UI harness.
        [node, "--input-type=module"],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
