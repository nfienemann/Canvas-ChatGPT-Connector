import { App } from "@modelcontextprotocol/ext-apps";

const app = new App({ name: "Canvas original download", version: "1.0.0" }, {});
const element = id => document.getElementById(id);
let input, current, connected = false, busy = false;
function envelope(value) {
  if (!value) return null;
  if (value.mcp_tool_result) return envelope(value.mcp_tool_result);
  const result = value.structuredContent ?? (value.status ? value : null);
  return result ? { result, privateData: value._meta?.canvas_bridge_download } : null;
}
function display(message) {
  const data = current?.result?.data;
  const ready = connected && !busy && data?.delivery_id && input?.connection_id;
  element("download").disabled = !ready;
  element("external").disabled = !ready;
  element("fresh").disabled = busy || !connected || !input?.file_id;
  element("canvas").disabled = busy || !connected || !data?.source_url;
  if (data) {
    element("title").textContent = data.filename;
    element("details").textContent = `${data.course_name} · ${new Intl.NumberFormat().format(data.byte_size)} bytes · Original file`;
  }
  if (message) element("status").textContent = message;
}
function accept(value) {
  const found = envelope(value);
  if (found?.result?.status === "ok" && found.result.data?.delivery_id) current = found;
}
function globals() {
  input ??= window.openai?.toolInput;
  if (!current) accept(window.openai?.toolOutput);
  display();
}
async function payload() {
  let response;
  try {
    response = await app.callServerTool({name:"get_course_file_download_payload", arguments:{
      connection_id:input.connection_id, delivery_id:current.result.data.delivery_id,
    }});
  } catch { throw Error("The file is unavailable right now. Get a fresh download or open it in Canvas."); }
  const found = envelope(response);
  if (!found || found.result.status !== "ok" || !found.privateData?.resource) {
    const code = found?.result?.data?.reason_code;
    throw Error(code === "SOURCE_CHANGED" ? "The source changed. Get a fresh download." : "This download is unavailable or expired. Get a fresh download.");
  }
  if (found.result.data.bytes_sha256 !== current.result.data.bytes_sha256 || found.result.data.delivery_id !== current.result.data.delivery_id) throw Error("The file changed. Get a fresh download.");
  const resource = found.privateData.resource;
  if (resource.type === "resource") {
    const blob = resource.resource?.blob;
    if (typeof blob !== "string" || blob.length > 174764) throw Error("The original payload is unavailable.");
    const bytes = Uint8Array.from(atob(blob), c => c.charCodeAt(0));
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), b=>b.toString(16).padStart(2,"0")).join("");
    if (bytes.length !== found.result.data.byte_size || hash !== found.result.data.bytes_sha256) throw Error("The original failed its integrity check. Get a fresh download.");
  }
  return found.privateData;
}
async function download(external) {
  if (busy || !current) return;
  if (!external && !app.getHostCapabilities()?.downloadFile) {
    element("external").hidden = false;
    display("This client does not offer an in-chat download. Download in browser opens a private, expiring external download; keep its link private. The server must stay online.");
    return;
  }
  busy = true; display("Checking current access and preparing your download…");
  try {
    const data = await payload();
    if (external) {
      let response;
      try { response = await app.openLink({url:data.external_url}); }
      catch { display("The external download outcome is unknown. Check your browser downloads before trying again."); return; }
      display(response?.isError ? "The browser handoff was not completed. You can retry when ready." : "External download opened. This does not confirm a saved file or a conversation attachment.");
    } else {
      let outcome;
      try { outcome = await app.downloadFile({contents:[data.resource]}, {timeout:60000}); }
      catch { display("Download outcome unknown after a connection or timeout error. Check your downloads before trying again."); return; }
      display(outcome?.isError ? "Download was not completed. You can retry when ready." : "Download request accepted by the host. This does not confirm a saved file or a conversation attachment.");
    }
  } catch (error) { display(error.message || "Download unavailable. Get a fresh download."); }
  finally { busy = false; display(); }
}
element("download").addEventListener("click", ()=>download(false));
element("external").addEventListener("click", ()=>download(true));
element("fresh").addEventListener("click", async()=>{
  if (busy || !input?.file_id) return;
  busy = true; display("Checking access and fetching a fresh original…");
  try {
    const response = await app.callServerTool({name:"prepare_course_file_download", arguments:input});
    const fresh = envelope(response);
    if (fresh?.result.status !== "ok") throw Error("A fresh original could not be prepared. Check Canvas access and retry.");
    accept(response); display("Original prepared. Select Download original when ready.");
  } catch { display("A fresh original could not be prepared. Check Canvas access and retry."); }
  finally { busy = false; display(); }
});
element("canvas").addEventListener("click", async()=>{
  try { await app.openLink({url:current.result.data.source_url}); }
  catch { display("Canvas could not be opened from this client."); }
});
app.ontoolinput = params => { input = params.arguments; globals(); };
const readyMessage = () => current ? "Original prepared. Select Download original when ready." : "No original is ready. Get a fresh download or open the source in Canvas.";
app.ontoolresult = response => { accept(response); display(readyMessage()); };
window.addEventListener("openai:set_globals", globals);
app.connect().then(()=>{ connected = true; globals(); display(readyMessage()); })
  .catch(()=>display("This client could not connect to the download card. Open the source in Canvas or retry in a supported client."));
