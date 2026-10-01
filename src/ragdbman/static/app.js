// SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
// SPDX-License-Identifier: Apache-2.0

"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const json = (value) => `<pre>${esc(JSON.stringify(value,null,2))}</pre>`;
const main = $("#main");
document.documentElement.dataset.theme = matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light";
$("#theme").onclick = () => {document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";};
async function api(url, method="GET", body) {
  const opts = {method};
  if(body instanceof FormData) opts.body = body;
  else if(body !== undefined) {opts.headers={"Content-Type":"application/json"};opts.body=JSON.stringify(body);}
  const response = await fetch(url,opts);
  const type = response.headers.get("content-type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  if(!response.ok) throw new Error(typeof data === "string" ? data || `HTTP ${response.status}` : data.message || JSON.stringify(data.detail || data));
  return data;
}
const operation = (name, body={}) => api("/api/"+name,"POST",body);
function error(node, err) {node.innerHTML=`<p class="error" role="alert">${esc(err.message)}</p>`;}
function heading(title, sub) {document.title=title+" · ragdbman";return `<div class="eyebrow">Document intelligence</div><h1>${esc(title)}</h1><p class="muted">${esc(sub)}</p><div id="feedback" role="status"></div>`;}
function table(headers, rows) {return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;}
async function confirmAction(message) {
  const d=$("#confirm-dialog");$("#confirm-message").textContent=message;d.returnValue="cancel";d.showModal();
  return new Promise(resolve => d.addEventListener("close",()=>resolve(d.returnValue==="yes"),{once:true}));
}
function bindForm(id, fn) {
  $(id).onsubmit=async e=>{e.preventDefault();if(e.target.dataset.busy==="true"||e.target.dataset.disabled==="true")return;const button=e.target.querySelector("button[type=submit]") || e.target.querySelector("button");button.disabled=true;e.target.dataset.busy="true";
    $("#feedback").textContent="";
    try{await fn(new FormData(e.target));}catch(err){error($("#feedback"),err);}finally{delete e.target.dataset.busy;button.disabled=e.target.dataset.disabled==="true";}};
}
async function dashboard() {
  const collections=await operation("collections-list");
  const sum=key=>collections.reduce((n,c)=>n+c.counts[key],0);
  main.innerHTML=heading("Your knowledge, inspectable.","Manage sources, follow indexing progress, and inspect the evidence behind every match.")+
    `<section class="stats">${[["Collections",collections.length],["Sources",sum("sources")],["Chunks",sum("chunks")],["Cards",sum("cards")],["Failed sources",sum("failed_sources")]].map(([l,n])=>`<div class="stat"><strong>${n}</strong><span class="muted">${l}</span></div>`).join("")}</section>
    <section><h2>Model service</h2><div id="health" role="status">Checking Ollama…</div></section>
    <a class="btn" href="/collections">Manage collections</a>`;
  try {const h=await operation("health-status");$("#health").innerHTML=`<p>${h.ollama_reachable?"Reachable":"Unavailable"} · <code>${esc(h.ollama_model)}</code> · ${h.active_jobs} active jobs</p>${h.message?`<p class="error">${esc(h.message)}</p>`:""}`;}catch(e){error($("#health"),e);}
}
async function collectionsPage() {
  const cols=await operation("collections-list");
  main.innerHTML=heading("Collections","Choose documents, source code, or structured Knowledge Cards independently for each collection.")+
  `<section><h2>Workspace</h2>${cols.length?table(["Name","Kind / model","Sources","Chunks / cards"],cols.map(c=>`<tr><td><a href="/collections/${encodeURIComponent(c.name)}">${esc(c.name)}</a></td><td>${esc(c.kind)}<br><code>${esc(c.embedding.model)}</code></td><td>${c.counts.sources}</td><td>${c.kind==="knowledge_cards"?`${c.counts.cards} cards`:`${c.counts.chunks} chunks`}</td></tr>`)):"<p>Create your first collection below, then add a source directory or upload files.</p>"}</section>
  <section><h2>New collection</h2><form id="create">
  <div class="row"><label>Name<input name="name" required pattern="[A-Za-z0-9](?:[A-Za-z0-9_]|-){0,127}" placeholder="research"></label>
  <label>Indexing strategy<select name="kind"><option value="general">General documents</option><option value="source_code">Source code · no sidecars</option><option value="knowledge_cards">Knowledge Cards · structured YAML</option></select></label></div>
  <label>Description<input name="description"></label><label>Source roots, one per line<textarea name="roots" placeholder="/home/you/documents"></textarea></label>
  <details><summary>Model and chunk overrides</summary><label>Embedding model<input name="model" placeholder="Use collection-kind default"></label>
  <div class="row" id="chunk-overrides"><label>Chunk size<input name="size" type="number" min="1"></label><label>Overlap<input name="overlap" type="number" min="0"></label></div><p id="card-fields" hidden>Knowledge Cards embed whole YAML fields, without token chunking or sidecars.</p></details>
  <button type="submit">Create collection</button></form></section>`;
  $('#create select[name="kind"]').onchange=e=>{const kc=e.target.value==="knowledge_cards";$("#chunk-overrides").hidden=kc;$("#card-fields").hidden=!kc;$("#chunk-overrides").querySelectorAll("input").forEach(i=>i.disabled=kc);};
  bindForm("#create",async f=>{const body={name:f.get("name"),description:f.get("description")||null,kind:f.get("kind"),source_roots:f.get("roots").split("\n").map(x=>x.trim()).filter(Boolean)};
    if(f.get("model"))body.embedding_model=f.get("model");if(f.get("size"))body.chunk_size_tokens=Number(f.get("size"));if(f.get("overlap"))body.chunk_overlap_tokens=Number(f.get("overlap"));
    await operation("collection-create",body);location.href="/collections/"+encodeURIComponent(body.name);});
}
async function detail(name) {
  const c=await operation("collection-get",{name}), roots=await operation("collection-list-roots",{collection:name}), jobs=await operation("scan-jobs-list",{collection:name});
  main.innerHTML=heading(name,c.description || "Collection overview and indexing controls.")+
  `<div class="toolbar"><a class="btn" href="/collections/${encodeURIComponent(name)}/corpus-query">Search</a>${c.kind==="source_code"?`<a class="btn secondary" href="/collections/${encodeURIComponent(name)}/corpus-graph">Graph explorer</a>`:""}<a class="btn secondary" href="/collections/${encodeURIComponent(name)}/sources">Sources</a><a class="btn secondary" href="/collections/${encodeURIComponent(name)}/upload">Upload</a><button class="secondary" id="manifest">Manifest</button></div>
  <section><h2>Configuration</h2><p><b>${esc(c.kind)}</b> · ${c.counts.sources} sources · ${c.kind==="knowledge_cards"?`${c.counts.cards} cards`:`${c.counts.chunks} chunks`}</p><code>${esc(c.embedding.model)} · ${c.embedding.dimensions} dimensions · ${c.kind==="knowledge_cards"?"Whole-field embeddings, no sidecars":`${c.chunking.size_tokens}/${c.chunking.overlap_tokens} tokens · ${esc(c.chunking.tokenizer_mode)}`}</code>
  <details><summary>Inspect full configuration</summary>${json(c)}</details></section>
  <section><h2>Source roots</h2><div id="roots">${roots.length?table(["Path","Action"],roots.map(r=>`<tr><td><code>${esc(r.path)}</code></td><td><button class="secondary scan-root" data-root="${esc(r.path)}">Scan</button> <button class="danger remove-root" data-id="${esc(r.id)}">Unregister</button></td></tr>`)):"<p>No registered directories yet. Add a root or upload a document.</p>"}</div>
  <form id="root"><label>Allowed directory<input name="path" required placeholder="/home/you/documents"></label><button type="submit">Register root</button></form></section>
  <section><h2>Indexing jobs</h2>${jobs.length?table(["Job","Status","Completed / failed"],jobs.map(j=>`<tr><td><a href="/collections/${encodeURIComponent(name)}/jobs/${j.id}">${esc(j.kind)} · ${esc(j.created_at.slice(0,19))}</a></td><td>${esc(j.status)}</td><td>${j.progress.completed} / ${j.progress.failed}</td></tr>`)):"<p>Run a scan to see durable progress and per-file errors.</p>"}</section>
  <details><summary>Maintenance and deletion</summary><div class="toolbar"><button id="vacuum" class="secondary">Vacuum</button><button id="rebuild" class="danger">Rebuild indexes</button><button id="delete" class="danger">Delete collection</button></div><p>Deletion preserves source files by default.</p></details>`;
  $("#manifest").onclick=async()=>{try{$("#feedback").innerHTML=json(await operation("collection-export-manifest",{collection:name}));}catch(e){error($("#feedback"),e);}};
  bindForm("#root",async f=>{await operation("collection-add-root",{collection:name,path:f.get("path")});await detail(name);});
  document.querySelectorAll(".scan-root").forEach(b=>b.onclick=async()=>{try{const j=await operation("scan-start",{collection:name,root:b.dataset.root});location.href=`/collections/${encodeURIComponent(name)}/jobs/${j.id}`;}catch(e){error($("#feedback"),e);}});
  document.querySelectorAll(".remove-root").forEach(b=>b.onclick=async()=>{try{if(await confirmAction("Unregister this root? Existing indexed content and original files will remain.")){await operation("collection-remove-root",{collection:name,root_id:b.dataset.id,confirm:true});await detail(name);}}catch(e){error($("#feedback"),e);}});
  $("#vacuum").onclick=async()=>{try{await operation("collection-vacuum",{collection:name});$("#feedback").textContent="Database vacuum completed.";}catch(e){error($("#feedback"),e);}};
  $("#rebuild").onclick=async()=>{if(await confirmAction("Clear this collection’s indexes and reindex its tracked sources?")){try{const j=await operation("collection-rebuild",{collection:name,confirm:true});location.href=`/collections/${encodeURIComponent(name)}/jobs/${j.id}`;}catch(e){error($("#feedback"),e);}}};
  $("#delete").onclick=async()=>{if(await confirmAction(`Delete collection "${name}" and all indexed data? Original and managed source files will be preserved.`)){try{await operation("collection-delete",{name,confirm:true});location.href="/collections";}catch(e){error($("#feedback"),e);}}};
}
async function sourcesPage(name) {
  main.innerHTML=heading(name+" / Sources","Inspect source state, extraction warnings, and Markdown paths.")+
    `<form id="filter" class="row"><label>Extension<input name="extension"></label><label>Status<select name="status"><option value="">All</option><option>indexed</option><option>failed</option><option>unsupported</option><option>missing</option></select></label><button type="submit">Filter</button></form><section id="sources">Loading sources…</section><div class="toolbar"><button id="prev" class="secondary">Previous</button><button id="next" class="secondary">Next</button></div>`;
  let offset=0,params=new URLSearchParams();
  async function load(){const filters=Object.fromEntries([...params].filter(([,v])=>v));const sources=await operation("collection-list-files",{collection:name,...filters,offset,limit:50});
    $("#prev").disabled=offset===0;$("#next").disabled=sources.length<50;
    $("#sources").innerHTML=sources.length?table(["Source","Status","Inspect"],sources.map(s=>`<tr><td>${esc(s.original_filename)}<br><code>${esc(s.canonical_path)}</code></td><td>${esc(s.status)}</td><td><details><summary>Details</summary>${json(s)}<button class="danger collection-remove-file" data-id="${esc(s.id)}">Remove index</button></details></td></tr>`)):"<p>No sources match. Try clearing the filters or start a scan from the collection page.</p>";
    document.querySelectorAll(".collection-remove-file").forEach(b=>b.onclick=async()=>{try{if(await confirmAction("Remove this source and its chunks from the index? The original file will remain.")){await operation("collection-remove-file",{collection:name,source_id:b.dataset.id,confirm:true});await load();}}catch(e){error($("#feedback"),e);}});}
  bindForm("#filter",async f=>{params=new URLSearchParams(f);offset=0;await load();});
  $("#prev").onclick=()=>{offset=Math.max(0,offset-50);load().catch(e=>error($("#feedback"),e));};
  $("#next").onclick=()=>{offset+=50;load().catch(e=>error($("#feedback"),e));};await load();
}
async function uploadPage(name) {
  main.innerHTML=heading(name+" / Upload","Files are copied into this collection’s managed source directory.")+
    `<section><form id="upload"><label>Document<input type="file" name="file" required></label><button type="submit">Upload and index</button></form></section>`;
  bindForm("#upload",async f=>{const file=f.get("file");const content_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(",")[1]);reader.onerror=reject;reader.readAsDataURL(file);});const result=await operation("collection-upload-file",{collection:name,filename:file.name,content_base64});$("#feedback").innerHTML="<p>Upload processed.</p>"+json(result);});
}
async function jobPage(name,id) {
  const getJob=()=>operation("scan-job-get",{collection:name,job_id:id});
  main.innerHTML=heading(name+" / Indexing job","Progress is saved in SQLite and streamed live.")+
    `<section id="job"><h2 id="job-status">Connecting to job…</h2><p id="job-progress-summary"></p><progress id="job-progress-bar" aria-label="Files processed" max="100"></progress><div class="row"><p>Elapsed: <strong id="job-elapsed">Not available</strong></p><p>Estimated remaining: <strong id="job-remaining">Not available</strong></p></div><p class="muted">Approximate ETA from processed files in this attempt; file sizes and conversion times vary.<span id="job-cleanup-note"></span></p><p id="job-counts"></p><code id="job-current-item" class="job-path"></code><pre id="job-error" class="error" hidden></pre><details id="job-inspection"><summary>Inspect job record</summary><p class="muted">This is a snapshot. Live progress continues above; this record stays unchanged while you read or select text.</p><button id="refresh-job-record" type="button" class="secondary">Refresh record</button><p id="job-snapshot-time" class="muted"></p><pre id="job-record" tabindex="0" aria-label="Job record snapshot"></pre></details></section><div class="toolbar"><button id="cancel" class="secondary">Cancel</button><button id="resume" class="secondary">Resume</button><a href="/collections/${encodeURIComponent(name)}">Back to collection</a></div>`;
  const duration=value=>{if(value==null)return "Not available";let s=Math.max(0,Math.round(value));const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return `${h?h+"h ":""}${h||m?m+"m ":""}${s%60}s`;};
  let latestJob=null,snapshotReady=false;
  // Keep the DOM nodes stable: replacing this panel would collapse details,
  // clear text selections and lose keyboard focus every time an SSE event arrives.
  const setText=(selector,value)=>{const node=$(selector),text=String(value??"");if(node.textContent!==text)node.textContent=text;};
  const refreshRecord=()=>{if(!latestJob)return;setText("#job-record",JSON.stringify(latestJob,null,2));setText("#job-snapshot-time","Snapshot captured at "+new Date().toLocaleTimeString());snapshotReady=true;};
  $("#refresh-job-record").onclick=refreshRecord;
  $("#job-inspection").ontoggle=()=>{if($("#job-inspection").open)refreshRecord();};
  const render=j=>{latestJob=j;const p=j.progress,t=j.timing||{},percent=p.percent,total=p.total;
    const summary=total==null?(["queued","running"].includes(j.status)?"Discovering files; total not yet known":"File total unavailable"):`${p.processed} / ${total} files processed${percent==null?"":` (${percent.toFixed(1)}%)`}`;
    const eta=t.estimated_remaining_seconds==null?(j.status==="running"?"Estimating…":"Not available"):duration(t.estimated_remaining_seconds);
    setText("#job-status",`${j.status} · ${p.phase||""}`);
    setText("#job-progress-summary",summary);
    if(percent==null)$("#job-progress-bar").removeAttribute("value");else $("#job-progress-bar").value=percent;
    setText("#job-elapsed",duration(t.elapsed_seconds));
    setText("#job-remaining",eta);
    setText("#job-cleanup-note",p.phase==="pruning"?" Files are processed; missing-source cleanup is still running.":"");
    setText("#job-counts",`${p.completed} completed · ${p.unchanged} unchanged · ${p.failed} failed · ${p.skipped} skipped`);
    setText("#job-current-item",j.current_item);
    setText("#job-error",j.error_summary);
    $("#job-error").hidden=!j.error_summary;
    if(!snapshotReady)refreshRecord();
    $("#cancel").disabled=!["queued","running"].includes(j.status);$("#resume").disabled=!["paused","failed","cancelled","completed_with_errors"].includes(j.status);};
  render(await getJob());
  const stream=new EventSource(`/collections/${encodeURIComponent(name)}/jobs/${id}/events`);
  stream.addEventListener("progress",e=>{const j=JSON.parse(e.data);render(j);if(!["running","queued"].includes(j.status))stream.close();});
  stream.onerror=()=>{stream.close();getJob().then(render).catch(e=>error($("#feedback"),e));};
  $("#cancel").onclick=async()=>{try{await operation("scan-job-cancel",{job_id:id});}catch(e){error($("#feedback"),e);}};
  $("#resume").onclick=async()=>{try{await operation("scan-job-resume",{collection:name,job_id:id});location.reload();}catch(e){error($("#feedback"),e);}};
}
function formatControl(defaultValue="raw") {
  return `<label>Output format<select name="format" data-testid="select-output-format"><option value="raw" ${defaultValue==="raw"?"selected":""}>Raw JSON</option><option value="llm" ${defaultValue==="llm"?"selected":""}>LLM text</option></select></label>`;
}
function outputPanel(data, format, title) {
  const text=typeof data==="string"?data:JSON.stringify(data,null,2);
  return `<section class="response-panel" data-testid="response-panel"><div class="response-heading"><h2>${esc(title)}</h2><button type="button" class="secondary" data-testid="copy-response" id="copy-response">Copy ${format==="llm"?"text":"JSON"}</button></div><p class="muted" id="copy-status" role="status">Static response snapshot. Select or copy without automatic refresh.</p><pre id="response-text" data-testid="response-text" tabindex="0" aria-label="${format==="llm"?"LLM-ready response":"Raw JSON response"}">${esc(text)}</pre></section>`;
}
function bindOutput() {
  const button=$("#copy-response");if(!button)return;
  button.onclick=async()=>{
    const node=$("#response-text");
    try{await navigator.clipboard.writeText(node.textContent);$("#copy-status").textContent="Response copied.";}
    catch{const range=document.createRange();range.selectNodeContents(node);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);node.focus();$("#copy-status").textContent="Clipboard access is unavailable. Response selected; use your system Copy command.";}
  };
}
async function searchPage(name) {
  const cols=await operation("collections-list");
  const current=name&&cols.find(c=>c.name===name), isKC=current?.kind==="knowledge_cards";
  if(name&&!current)throw new Error("Collection not found.");
  main.innerHTML=heading(name?name+" / Search":"Search across collections","Inspect rank, evidence, citations, and applied filters.")+
    (name?`<div class="toolbar"><a href="/collections/${encodeURIComponent(name)}">Back to collection</a>${current.kind==="source_code"?`<a href="/collections/${encodeURIComponent(name)}/corpus-graph">Graph explorer</a>`:""}</div>`:"")+
    `<section><form id="search">${name?"":`<fieldset><legend>Collections</legend>${cols.map(c=>`<label class="check"><input type="checkbox" name="collection" value="${esc(c.name)}" checked>${esc(c.name)}</label>`).join("")}</fieldset>`}
    <label>Query<input name="query" data-testid="input-query" ${isKC?"required":""} placeholder="What are you looking for?"></label><div class="row"><label>Retrieval mode<select name="mode"><option>hybrid</option><option>keyword</option><option>semantic</option>${isKC?"":"<option>structured</option>"}</select></label><label>Maximum results<input name="limit" type="number" value="5" min="1" max="50" required></label>${formatControl()}</div>
    ${!name||current.kind==="source_code"?`<label>Graph context<select name="graph_context" data-testid="select-graph-context"><option value="auto">Automatic for source code</option><option value="true">Include source graph context</option><option value="false">Omit graph context</option></select></label>`:""}
    <p class="muted">Raw keeps structured metadata; LLM text is formatted by the server. Output formatting does not change ranking or generate summaries.</p>
    ${isKC?`<div class="row"><label>Query type<select name="perspective"><option>general</option><option>expert</option></select></label><label>Minimum confidence-weighted similarity<input name="minimum_score" type="number" value="${current.knowledge_cards.min_similarity}" min="0" max="1" step="0.01" required></label></div>`:`<details><summary>Structured filters</summary><label>Filters as JSON<textarea name="filters" placeholder='{"numeric":[{"field":"price","op":"less_than","value":100}]}'>{}</textarea></label></details>`}
    <button type="submit" data-testid="button-search" ${!name&&!cols.length?"disabled":""}>Search</button></form></section><div id="results" aria-live="polite"></div>`;
  bindForm("#search",async f=>{const format=f.get("format"),request={query:f.get("query"),mode:f.get("mode"),limit:Number(f.get("limit"))};
    if(isKC){request.collection=name;request.perspective=f.get("perspective");request.minimum_score=Number(f.get("minimum_score"));}
    else request.filters=JSON.parse(f.get("filters"));
    if(name)request.collection=name;else request.collections=f.getAll("collection");
    if(!name&&!request.collections.length)throw new Error("Select at least one collection.");
    const node=$("#results");node.setAttribute("aria-busy","true");node.innerHTML="<p role='status'>Searching…</p>";
    try{
    const graph=f.get("graph_context");
    const body={query:request.query,collections:name?[name]:request.collections,mode:request.mode,
      perspective:isKC?request.perspective:"general",minimum_score:isKC?request.minimum_score:null,
      limit:request.limit,format,filters:request.filters||{},include_graph_context:graph==="auto"||graph===null?null:graph==="true"};
    const data=await operation("corpus-query",body);
    if(format==="llm"){if(typeof data!=="string")throw new Error("Expected a text response from the server.");node.innerHTML=outputPanel(data,format,"LLM-ready query response");bindOutput();return;}
    node.innerHTML=`<p>${data.results.length} matching results · Collections: ${esc(body.collections.join(", "))}</p>`+data.results.map(r=>`<article class="card"><h2>${esc(r.title)}</h2><p class="muted">Score ${Number(r.relevance.score).toFixed(6)} · ${esc(r.relevance.policy)}</p><pre>${esc(typeof r.content==="string"?r.content:JSON.stringify(r.content,null,2))}</pre><details><summary>Provenance and metadata</summary>${json(r)}</details></article>`).join("")+
      `<details><summary>Filter and collection diagnostics</summary>${json({...data,results:undefined})}</details>`+
      `<details><summary>Full raw response</summary>${outputPanel(data,format,"Raw query response")}</details>`;
    bindOutput();
    if(!isKC)node.querySelectorAll("article").forEach((article,index)=>{
      const result=data.results[index],collection=cols.find(c=>c.name===result.collection),sourceId=result.graph_context?.entities?.[0]?.provenance?.source_id;
      if(collection?.kind==="source_code"&&sourceId){
        const link=document.createElement("a");link.textContent="Explore source graph";
        link.href=`/collections/${encodeURIComponent(collection.name)}/corpus-graph?source_id=${encodeURIComponent(sourceId)}&action=find`;
        article.append(link);
      }
    });
    }catch(err){error(node,err);}finally{node.removeAttribute("aria-busy");}
  });
}
async function graphPage(name) {
  const all=await operation("collections-list"),cols=all.filter(c=>c.kind==="source_code");
  const requested=name&&all.find(c=>c.name===name);
  main.innerHTML=heading(name?name+" / Graph explorer":"Source graph explorer",
    "Find entities, inspect calls and dependencies, and follow source-backed relationship chains.");
  if(name&&!requested)throw new Error("Collection not found.");
  if(name&&requested.kind!=="source_code"){main.innerHTML+=`<section><h2>Source-code collections only</h2><p>General documents and Knowledge Cards do not build source graphs.</p><a href="/corpus-graph">Choose a source-code collection</a></section>`;return;}
  if(!cols.length){main.innerHTML+=`<section><h2>No source-code collections yet</h2><p>Create a source-code collection and scan its files to build a graph.</p><a class="btn" href="/collections">Manage collections</a></section>`;return;}
  const selected=name||cols[0].name,params=new URLSearchParams(location.search);
  main.innerHTML+=`<div class="toolbar"><a id="graph-back" href="/collections/${encodeURIComponent(selected)}">Back to collection</a></div>
    <section><form id="graph-form">
    <div class="row"><label>Source-code collection<select name="collection" data-testid="select-graph-collection">${cols.map(c=>`<option value="${esc(c.name)}" ${c.name===selected?"selected":""}>${esc(c.name)}</option>`).join("")}</select></label>
    <label>Graph action<select name="action" data-testid="select-graph-action">${["find","neighbors","callers","callees","dependencies","inheritance","impact"].map(a=>`<option value="${a}">${a}</option>`).join("")}</select></label>${formatControl()}</div>
    <p class="muted" id="graph-summary" role="status"></p>
    <div class="row"><label>Identify by<select name="selector_type" data-testid="select-graph-selector"><option value="symbol">Symbol</option><option value="entity_id">Entity ID</option></select></label>
    <label class="grow">Symbol or entity ID<input name="selector_value" data-testid="input-graph-selector" placeholder="Optional for find; e.g. parse_config"></label></div>
    <button type="submit" data-testid="button-graph-query">Query graph</button>
    <details id="graph-options"><summary>Traversal options</summary>
    <div class="row"><label>Depth<input name="depth" type="number" min="1" max="5" value="1" required></label><label>Result limit<input name="limit" type="number" min="1" max="200" value="50" required></label>
    <label>Direction<select name="direction"><option value="outgoing">Outgoing</option><option value="incoming">Incoming</option><option value="both">Both</option></select></label></div>
    <label>Restrict to source ID<input name="source_id" data-testid="input-graph-source" placeholder="Optional stable source ID"></label>
    <fieldset><legend>Relationship override</legend><p class="muted">Leave unchecked to use the action defaults.</p><div class="check-grid">${["contains","imports","calls","inherits","implements","type_base","references","depends_on"].map(k=>`<label class="check"><input type="checkbox" name="relationship" value="${k}">${k}</label>`).join("")}</div></fieldset></details>
    <p class="muted" id="graph-action-help">Find matches by name, or leave the selector empty to list entities.</p>
    <p class="notice">Read-only, best-effort static analysis. Unresolved or omitted edges are not proof of runtime behavior. Queries never build or rescan graphs.</p>
    </form></section><div id="graph-results" aria-live="polite"></div>`;
  const form=$("#graph-form"),field=n=>form.elements.namedItem(n);
  const actions={find:"Find matches by name, or leave the selector empty to list entities.",neighbors:"Inspect incoming, outgoing or both directions for one entity.",
    callers:"Follow incoming call relationships.",callees:"Follow outgoing call relationships.",dependencies:"Follow outgoing file/module dependencies.",
    inheritance:"Follow outgoing base-type and implementation relationships.",impact:"Follow incoming static calls, references, type and dependency relationships."};
  function update(){
    const c=cols.find(c=>c.name===field("collection").value),g=c.graph||{};
    field("direction").disabled=field("action").value!=="neighbors";
    field("selector_value").required=field("action").value!=="find"&&!field("source_id").value.trim();
    field("selector_value").placeholder=field("selector_type").value==="entity_id"?"Paste an entity ID":"Optional for find; e.g. parse_config";
    if(name){$("h1").textContent=c.name+" / Graph explorer";document.title=c.name+" / Graph explorer · ragdbman";}
    $("#graph-action-help").textContent=actions[field("action").value];
    $("#graph-summary").textContent=g.enabled===false?"Graphs are disabled. Enable graph.enabled in daemon configuration and restart.":
      !g.available?"No graph database yet. Run a normal scan from the collection page; queries do not index files.":
      `${g.entities??0} stored entities · ${g.relationships??0} relationships · ${g.pending_updates??0} pending updates. Read validation may hide stale revisions.`;
    form.dataset.disabled=String(g.enabled===false);form.querySelector("button[type=submit]").disabled=g.enabled===false||form.dataset.busy==="true";
    $("#graph-back").href="/collections/"+encodeURIComponent(c.name);
  }
  for(const n of ["collection","action","selector_type","source_id"])field(n).addEventListener(n==="source_id"?"input":"change",update);
  if(Object.hasOwn(actions,params.get("action")))field("action").value=params.get("action");
  if(params.get("source_id")){field("source_id").value=params.get("source_id");$("#graph-options").open=true;}
  update();
  bindForm("#graph-form",async f=>{
    const request={collection:f.get("collection"),action:f.get("action"),format:f.get("format"),depth:Number(f.get("depth")),limit:Number(f.get("limit"))};
    const selector=f.get("selector_value").trim(),source=f.get("source_id").trim(),relationships=f.getAll("relationship");
    if(selector)request[f.get("selector_type")]=selector;if(source)request.source_id=source;
    if(request.action!=="find"&&!selector&&!source)throw new Error("Choose a symbol, entity ID or source ID.");
    if(request.action==="neighbors")request.direction=f.get("direction");
    if(relationships.length)request.relationships=relationships;
    const node=$("#graph-results");node.setAttribute("aria-busy","true");node.innerHTML="<p role='status'>Reading graph…</p>";
    try{
      const data=await operation("corpus-graph",request);
      if(typeof data==="string"){node.innerHTML=outputPanel(data,"llm","LLM-ready graph response");bindOutput();return;}
      const candidates=data.status==="ambiguous"||request.action==="find"?data.candidates:data.entities;
      const entities=new Map((data.entities||[]).map(e=>[e.entity_id,e]));
      node.innerHTML=`<section><h2>Graph result: ${esc(data.status)}</h2><p>Collection: <code>${esc(request.collection)}</code> · Action: <code>${esc(request.action)}</code></p><p>${esc(data.message||(candidates?.length?"Select an entity below for a precise follow-up query.":"No entities or relationships matched. Try a different selector, or scan the collection."))}</p><p class="muted">${esc(data.limitation)}</p>${data.truncated?'<p class="notice">Results are partial/truncated. Narrow the selector or adjust the limits.</p>':""}</section>`+
        (data.status==="ok"&&request.action!=="find"&&!data.relationships?.length?'<p class="notice">No matching relationships were returned. This does not prove that no runtime relationships exist.</p>':"")+
        (candidates?.length?`<section><h2>${data.status==="ambiguous"?"Choose an exact match":"Entities"}</h2><div class="entity-list">${candidates.map(e=>`<article class="entity"><h3>${esc(e.qualified_name||e.name)}</h3><p>${esc(e.kind)} · ${esc(e.provenance?.source_path)} · lines ${esc(e.provenance?.line_start)}-${esc(e.provenance?.line_end)}</p><button type="button" class="secondary use-entity" data-testid="button-use-entity" data-id="${esc(e.entity_id)}">Use this entity</button></article>`).join("")}</div></section>`:"")+
        (data.relationships?.length?`<section><h2>Relationships</h2>${table(["From","Relationship","To","Resolution","Evidence"],data.relationships.map(e=>`<tr><td>${esc(e.from_name||entities.get(e.from_entity_id)?.name||"<module>")}</td><td>${esc(e.kind)}</td><td>${esc(e.resolved_target_name||e.target_name)}</td><td>${esc(e.resolution)}</td><td>${esc(e.provenance?.source_path)}:${esc(e.provenance?.line_start)}</td></tr>`))}</section>`:"")+
        `<details><summary>Full raw graph response and chains</summary>${outputPanel(data,"raw","Raw graph response")}</details>`;
      node.querySelectorAll(".use-entity").forEach(button=>button.onclick=()=>{
        field("collection").value=request.collection;field("selector_type").value="entity_id";field("selector_value").value=button.dataset.id;
        field("source_id").value="";field("action").value="neighbors";update();field("selector_value").focus();form.scrollIntoView({block:"start"});
        $("#feedback").textContent="Entity selected. Choose a graph action, then query again.";
      });
      bindOutput();
    }catch(err){error(node,err);}finally{node.removeAttribute("aria-busy");}
  });
}
(async()=>{try{const parts=location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if(parts[0]==="collections"&&parts[1]){const [_,name,page,id]=parts;if(page==="sources")await sourcesPage(name);else if(page==="upload")await uploadPage(name);else if(page==="jobs")await jobPage(name,id);else if(page==="corpus-query")await searchPage(name);else if(page==="corpus-graph")await graphPage(name);else await detail(name);}
  else if(parts[0]==="collections")await collectionsPage();else if(parts[0]==="corpus-query")await searchPage();else if(parts[0]==="corpus-graph")await graphPage();else await dashboard();
}catch(e){main.innerHTML=heading("Unable to load this view","Check that the daemon is running and the collection still exists.");error($("#feedback"),e);}})();
