"use strict";
const form = document.querySelector("#batch");
const status = document.querySelector("#status");
let cancelled = false, activeKey = null, retryKeys = new Map(), selectedFiles = [];
let dismissReview = null;
function reviewPacket(result, mappings) {
  const panel = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = "Review packet changes";
  panel.append(heading);
  let needsMapping = false;
  for (const item of result.items) {
    const line = document.createElement("p");
    line.textContent = item.logical_path + " · " + item.disposition;
    if (item.disposition === "ambiguous") {
      needsMapping = true;
      const select = document.createElement("select");
      select.append(new Option("Choose an existing source", ""));
      for (const id of item.candidates) {
        select.append(new Option(item.candidate_locations[id] + " · " + id.slice(0, 8), id));
      }
      select.onchange = () => { mappings[item.logical_path] = select.value; };
      line.append(select);
    }
    panel.append(line);
  }
  for (const path of result.excluded) panel.append(document.createTextNode("Unsupported: " + path + " "));
  for (const ref of result.coverage.missing) {
    const line = document.createElement("p");
    line.textContent = ref.logical_path + (ref.retained_version ? " · omitted, earlier version retained" : " · missing");
    panel.append(line);
  }
  form.after(panel);
  return new Promise(resolve => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = needsMapping ? "Review selected mappings" : "Confirm eligible files";
    button.onclick = () => { panel.remove(); dismissReview = null; resolve(needsMapping ? "review" : "commit"); };
    panel.append(button);
    dismissReview = () => { panel.remove(); dismissReview = null; resolve("cancel"); };
  });
}
function renderSelection() {
  const list = document.querySelector("#selection");
  list.replaceChildren();
  for (const file of selectedFiles) {
    const item = document.createElement("li");
    item.textContent = file.name + " · " + file.size + " bytes";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove " + file.name;
    remove.addEventListener("click", () => {
      selectedFiles = selectedFiles.filter(candidate => candidate !== file);
      renderSelection();
    });
    item.append(remove);
    list.append(item);
  }
}
form.files.addEventListener("change", () => {
  selectedFiles = Array.from(form.files.files);
  renderSelection();
});
document.querySelector("#cancel").addEventListener("click", async () => {
  cancelled = true;
  if (dismissReview) dismissReview();
  if (activeKey) {
    await fetch("/settings/materials/cancel", {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({csrf: form.csrf.value, key: activeKey})});
  }
  status.textContent = "Cancellation requested. Completed imports are retained; pending files will not start.";
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  const files = selectedFiles.slice();
  if (!files.length || files.length > 20) {
    status.textContent = "Choose one to twenty files."; return;
  }
  cancelled = false;
  const button = form.querySelector("button");
  button.disabled = true;
  let completed = 0, failed = 0;
  for (const file of files) {
    if (cancelled) break;
    const selection = [file.name, file.size, file.lastModified, form.course.value,
      form.purpose.value, form.term.value, form.expected.value, form.share.checked, form.analysis.checked, form.visual.checked].join("|");
    activeKey = retryKeys.get(selection) || crypto.randomUUID();
    retryKeys.set(selection, activeKey);
    status.textContent = "Processing " + file.name + " locally…";
    try {
      const send = extra => fetch("/settings/materials/import", {method: "POST", credentials: "same-origin",
        headers: {"Content-Type": file.type || "application/octet-stream",
          "X-Bridge-CSRF": form.csrf.value, "X-Bridge-Key": activeKey,
          "X-Bridge-Filename": encodeURIComponent(file.name), "X-Bridge-Course": encodeURIComponent(form.course.value),
          "X-Bridge-Purpose": form.purpose.value, "X-Bridge-Own": String(form.own.checked),
          "X-Bridge-Share": String(form.share.checked), "X-Bridge-Analysis": String(form.analysis.checked),
          "X-Bridge-Term": encodeURIComponent(form.term.value || "unspecified"),
          "X-Bridge-Visual": String(form.visual.checked), ...extra}, body: file});
      let extra = {};
      if (file.name.toLowerCase().endsWith(".zip")) {
        const mappings = {};
        const expected = Object.fromEntries(form.expected.value.split(/\r?\n/).filter(Boolean).map(path => [path, null]));
        while (!cancelled) {
          extra = {"X-Bridge-Mappings": encodeURIComponent(JSON.stringify(mappings)),
            "X-Bridge-Expected": encodeURIComponent(JSON.stringify(expected))};
          const preview = await send({...extra, "X-Bridge-Preview": "true"});
          if (!preview.ok) throw Error("Preview unavailable");
          const result = await preview.json();
          if (result.state === "rejected") {
            status.textContent = "Packet rejected. Review the member paths, formats and limits.";
            throw Error("Packet rejected");
          }
          const choice = await reviewPacket(result, mappings);
          if (choice === "commit") { extra["X-Bridge-Confirmation"] = result.preview_id; break; }
        }
        if (cancelled) break;
      }
      const response = await send(extra);
      if (!response.ok) { failed++; continue; }
      const result = await response.json();
      if (result.state === "ready") completed++;
      else failed++;
    } catch { failed++; }
  }
  activeKey = null;
  button.disabled = false;
  status.textContent = (cancelled ? "Cancelled. " : failed ? "Partial import. " : "Import complete. ") +
    completed + " completed, " + failed + " failed or partial. Refresh to inspect receipts and review candidates. Retry failed files with the same selection.";
});
