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
  const data = await response.json();
  if(!response.ok) throw new Error(data.message || JSON.stringify(data.detail || data));
  return data;
}
function error(node, err) {node.innerHTML=`<p class="error" role="alert">${esc(err.message)}</p>`;}
function heading(title, sub) {document.title=title+" · ragdbman";return `<div class="eyebrow">Document intelligence</div><h1>${esc(title)}</h1><p class="muted">${esc(sub)}</p><div id="feedback" role="status"></div>`;}
function table(headers, rows) {return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;}
async function confirmAction(message) {
  const d=$("#confirm-dialog");$("#confirm-message").textContent=message;d.returnValue="cancel";d.showModal();
  return new Promise(resolve => d.addEventListener("close",()=>resolve(d.returnValue==="yes"),{once:true}));
}
function bindForm(id, fn) {
  $(id).onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector("button[type=submit]") || e.target.querySelector("button");button.disabled=true;
    try{await fn(new FormData(e.target));}catch(err){error($("#feedback"),err);}finally{button.disabled=false;}};
}
async function dashboard() {
  const collections=await api("/api/collections");
  const sum=key=>collections.reduce((n,c)=>n+c.counts[key],0);
  main.innerHTML=heading("Your knowledge, inspectable.","Manage sources, follow indexing progress, and inspect the evidence behind every match.")+
    `<section class="stats">${[["Collections",collections.length],["Sources",sum("sources")],["Chunks",sum("chunks")],["Cards",sum("cards")],["Failed sources",sum("failed_sources")]].map(([l,n])=>`<div class="stat"><strong>${n}</strong><span class="muted">${l}</span></div>`).join("")}</section>
    <section><h2>Model service</h2><div id="health" role="status">Checking Ollama…</div></section>
    <a class="btn" href="/collections">Manage collections</a>`;
  try {const h=await api("/api/health");$("#health").innerHTML=`<p>${h.ollama_reachable?"Reachable":"Unavailable"} · <code>${esc(h.ollama_model)}</code> · ${h.active_jobs} active jobs</p>${h.message?`<p class="error">${esc(h.message)}</p>`:""}`;}catch(e){error($("#health"),e);}
}
async function collectionsPage() {
  const cols=await api("/api/collections");
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
    await api("/api/collections","POST",body);location.href="/collections/"+encodeURIComponent(body.name);});
}
async function detail(name) {
  const base="/api/collections/"+encodeURIComponent(name), c=await api(base), roots=await api(base+"/roots"), jobs=await api(base+"/jobs");
  main.innerHTML=heading(name,c.description || "Collection overview and indexing controls.")+
  `<div class="toolbar"><a class="btn" href="/collections/${encodeURIComponent(name)}/search">Search</a><a class="btn secondary" href="/collections/${encodeURIComponent(name)}/sources">Sources</a><a class="btn secondary" href="/collections/${encodeURIComponent(name)}/upload">Upload</a><a class="btn secondary" href="${base}/manifest">Manifest</a></div>
  <section><h2>Configuration</h2><p><b>${esc(c.kind)}</b> · ${c.counts.sources} sources · ${c.kind==="knowledge_cards"?`${c.counts.cards} cards`:`${c.counts.chunks} chunks`}</p><code>${esc(c.embedding.model)} · ${c.embedding.dimensions} dimensions · ${c.kind==="knowledge_cards"?"Whole-field embeddings, no sidecars":`${c.chunking.size_tokens}/${c.chunking.overlap_tokens} tokens · ${esc(c.chunking.tokenizer_mode)}`}</code>
  <details><summary>Inspect full configuration</summary>${json(c)}</details></section>
  <section><h2>Source roots</h2><div id="roots">${roots.length?table(["Path","Action"],roots.map(r=>`<tr><td><code>${esc(r.path)}</code></td><td><button class="secondary scan-root" data-root="${esc(r.path)}">Scan</button> <button class="danger remove-root" data-id="${esc(r.id)}">Unregister</button></td></tr>`)):"<p>No registered directories yet. Add a root or upload a document.</p>"}</div>
  <form id="root"><label>Allowed directory<input name="path" required placeholder="/home/you/documents"></label><button type="submit">Register root</button></form></section>
  <section><h2>Indexing jobs</h2>${jobs.length?table(["Job","Status","Completed / failed"],jobs.map(j=>`<tr><td><a href="/collections/${encodeURIComponent(name)}/jobs/${j.id}">${esc(j.kind)} · ${esc(j.created_at.slice(0,19))}</a></td><td>${esc(j.status)}</td><td>${j.progress.completed} / ${j.progress.failed}</td></tr>`)):"<p>Run a scan to see durable progress and per-file errors.</p>"}</section>
  <details><summary>Maintenance and deletion</summary><div class="toolbar"><button id="vacuum" class="secondary">Vacuum</button><button id="rebuild" class="danger">Rebuild indexes</button><button id="delete" class="danger">Delete collection</button></div><p>Deletion preserves source files by default.</p></details>`;
  bindForm("#root",async f=>{await api(base+"/roots","POST",{path:f.get("path")});await detail(name);});
  document.querySelectorAll(".scan-root").forEach(b=>b.onclick=async()=>{try{const j=await api(base+"/scan","POST",{root:b.dataset.root});location.href=`/collections/${encodeURIComponent(name)}/jobs/${j.id}`;}catch(e){error($("#feedback"),e);}});
  document.querySelectorAll(".remove-root").forEach(b=>b.onclick=async()=>{try{if(await confirmAction("Unregister this root? Existing indexed content and original files will remain.")){await api(base+"/roots/"+b.dataset.id,"DELETE");await detail(name);}}catch(e){error($("#feedback"),e);}});
  $("#vacuum").onclick=async()=>{try{await api(base+"/vacuum","POST");$("#feedback").textContent="Database vacuum completed.";}catch(e){error($("#feedback"),e);}};
  $("#rebuild").onclick=async()=>{if(await confirmAction("Clear this collection’s indexes and reindex its tracked sources?")){try{const j=await api(base+"/rebuild","POST",{confirm:true});location.href=`/collections/${encodeURIComponent(name)}/jobs/${j.id}`;}catch(e){error($("#feedback"),e);}}};
  $("#delete").onclick=async()=>{if(await confirmAction(`Delete collection "${name}" and all indexed data? Original and managed source files will be preserved.`)){try{await api(base+"?confirm=true","DELETE");location.href="/collections";}catch(e){error($("#feedback"),e);}}};
}
async function sourcesPage(name) {
  const base="/api/collections/"+encodeURIComponent(name);
  main.innerHTML=heading(name+" / Sources","Inspect source state, extraction warnings, and Markdown paths.")+
    `<form id="filter" class="row"><label>Extension<input name="extension"></label><label>Status<select name="status"><option value="">All</option><option>indexed</option><option>failed</option><option>unsupported</option><option>missing</option></select></label><button type="submit">Filter</button></form><section id="sources">Loading sources…</section><div class="toolbar"><button id="prev" class="secondary">Previous</button><button id="next" class="secondary">Next</button></div>`;
  let offset=0,params=new URLSearchParams();
  async function load(){params.set("offset",offset);params.set("limit",50);const sources=await api(base+"/sources?"+params);
    $("#prev").disabled=offset===0;$("#next").disabled=sources.length<50;
    $("#sources").innerHTML=sources.length?table(["Source","Status","Inspect"],sources.map(s=>`<tr><td>${esc(s.original_filename)}<br><code>${esc(s.canonical_path)}</code></td><td>${esc(s.status)}</td><td><details><summary>Details</summary>${json(s)}<button class="danger remove-source" data-id="${esc(s.id)}">Remove index</button></details></td></tr>`)):"<p>No sources match. Try clearing the filters or start a scan from the collection page.</p>";
    document.querySelectorAll(".remove-source").forEach(b=>b.onclick=async()=>{try{if(await confirmAction("Remove this source and its chunks from the index? The original file will remain.")){await api(base+"/sources/"+b.dataset.id+"?confirm=true","DELETE");await load();}}catch(e){error($("#feedback"),e);}});}
  bindForm("#filter",async f=>{params=new URLSearchParams(f);offset=0;await load();});
  $("#prev").onclick=()=>{offset=Math.max(0,offset-50);load().catch(e=>error($("#feedback"),e));};
  $("#next").onclick=()=>{offset+=50;load().catch(e=>error($("#feedback"),e));};await load();
}
async function uploadPage(name) {
  main.innerHTML=heading(name+" / Upload","Files are copied into this collection’s managed source directory.")+
    `<section><form id="upload"><label>Document<input type="file" name="file" required></label><button type="submit">Upload and index</button></form></section>`;
  bindForm("#upload",async f=>{const result=await api("/api/collections/"+encodeURIComponent(name)+"/upload","POST",f);$("#feedback").innerHTML="<p>Upload processed.</p>"+json(result);});
}
async function jobPage(name,id) {
  const base="/api/collections/"+encodeURIComponent(name)+"/jobs/"+id;
  main.innerHTML=heading(name+" / Indexing job","Progress is saved in SQLite and streamed live.")+
    `<section id="job">Connecting to job…</section><div class="toolbar"><button id="cancel" class="secondary">Cancel</button><button id="resume" class="secondary">Resume</button><a href="/collections/${encodeURIComponent(name)}">Back to collection</a></div>`;
  const render=j=>{$("#job").innerHTML=`<h2>${esc(j.status)}</h2><p>${j.progress.completed} completed · ${j.progress.unchanged} unchanged · ${j.progress.failed} failed · ${j.progress.skipped} skipped</p><code>${esc(j.current_item||"")}</code>${j.error_summary?`<pre class="error">${esc(j.error_summary)}</pre>`:""}<details><summary>Inspect job record</summary>${json(j)}</details>`;
    $("#cancel").disabled=!["queued","running"].includes(j.status);$("#resume").disabled=!["paused","failed","cancelled","completed_with_errors"].includes(j.status);};
  render(await api(base));
  const stream=new EventSource(`/collections/${encodeURIComponent(name)}/jobs/${id}/events`);
  stream.addEventListener("progress",e=>{const j=JSON.parse(e.data);render(j);if(!["running","queued"].includes(j.status))stream.close();});
  stream.onerror=()=>{stream.close();api(base).then(render).catch(e=>error($("#feedback"),e));};
  $("#cancel").onclick=async()=>{try{await api("/api/jobs/"+id+"/cancel","POST");}catch(e){error($("#feedback"),e);}};
  $("#resume").onclick=async()=>{try{await api(base+"/resume","POST");location.reload();}catch(e){error($("#feedback"),e);}};
}
async function searchPage(name) {
  const cols=await api("/api/collections");
  const current=name&&cols.find(c=>c.name===name), isKC=current?.kind==="knowledge_cards";
  main.innerHTML=heading(name?name+" / Search":"Search across collections","Inspect rank, evidence, citations, and applied filters.")+
    `<section><form id="search">${name?"":`<fieldset><legend>Collections</legend>${cols.map(c=>`<label class="check"><input type="checkbox" name="collection" value="${esc(c.name)}" checked>${esc(c.name)}</label>`).join("")}</fieldset>`}
    <label>Query<input name="query" ${isKC?"required":""} placeholder="What are you looking for?"></label><div class="row"><label>Retrieval mode<select name="mode"><option>hybrid</option><option>keyword</option><option>vector</option>${isKC?"":"<option>structured</option>"}</select></label><label>Maximum results<input name="top_k" type="number" value="${isKC?current.knowledge_cards.default_top_k:8}" min="1" max="50" required></label></div>
    ${isKC?`<div class="row"><label>Query type<select name="query_type"><option>expert</option><option>general</option></select></label><label>Minimum confidence-weighted similarity<input name="minimum_similarity" type="number" value="${current.knowledge_cards.min_similarity}" min="0" max="1" step="0.01" required></label></div>`:`<details><summary>Structured filters</summary><label>Filters as JSON<textarea name="filters" placeholder='{"numeric":[{"field":"price","op":"less_than","value":100}]}'>{}</textarea></label></details>`}
    <button type="submit">Search</button></form></section><div id="results" aria-live="polite"></div>`;
  bindForm("#search",async f=>{const request={query:f.get("query"),mode:f.get("mode"),top_k:Number(f.get("top_k"))};
    if(isKC){request.collection=name;request.query_type=f.get("query_type");request.minimum_similarity=Number(f.get("minimum_similarity"));}
    else request.filters=JSON.parse(f.get("filters"));
    if(name)request.collection=name;else request.collections=f.getAll("collection");
    $("#results").innerHTML="<p>Searching…</p>";const data=await api(isKC?"/api/knowledge-cards/search":name?"/api/search":"/api/search/multi","POST",request);
    $("#results").innerHTML=`<p>${data.results.length} matching ${isKC?"cards":"results"}</p>`+(isKC&&!data.results.length?`<p>${esc(data.yaml)}</p>`:"")+data.results.map(r=>isKC?`<article class="card"><h2>${esc(r.card.title)}</h2><p class="muted">Score ${r.score.toFixed(6)} · confidence ${r.card.confidence}</p><pre>${esc(r.yaml)}</pre><details><summary>Provenance and scores</summary>${json({...r,card:undefined,yaml:undefined})}</details></article>`:`<article class="card"><h2>${esc(r.citation_label)}</h2><p class="muted">Score ${r.score.toFixed(6)} · Vector ${r.vector_score??"—"} · Keyword ${r.keyword_score??"—"}</p><pre>${esc(r.text||"")}</pre><details><summary>Provenance and metadata</summary>${json(r)}</details></article>`).join("")+
      (isKC?"":`<details><summary>Filter and collection diagnostics</summary>${json({...data,results:undefined})}</details>`);});
}
(async()=>{try{const parts=location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if(parts[0]==="collections"&&parts[1]){const [_,name,page,id]=parts;if(page==="sources")await sourcesPage(name);else if(page==="upload")await uploadPage(name);else if(page==="jobs")await jobPage(name,id);else if(page==="search")await searchPage(name);else await detail(name);}
  else if(parts[0]==="collections")await collectionsPage();else if(parts[0]==="search-multi")await searchPage();else await dashboard();
}catch(e){main.innerHTML=heading("Unable to load this view","Check that the daemon is running and the collection still exists.");error($("#feedback"),e);}})();
