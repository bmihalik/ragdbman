// SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
// SPDX-License-Identifier: Apache-2.0

// QA inventory: raw/LLM search for code/documents/mixed/cards, graph-context
// switches, empty scope, plain/JSON errors, graph actions/options/exact entity
// selection, disabled/unbuilt/empty graph states, escaped hostile evidence,
// static copy/select output, desktop/mobile and both themes.
const assert = (await import("node:assert/strict")).default;
const { readFile } = await import("node:fs/promises");
const { resolve } = await import("node:path");
const { fileURLToPath } = await import("node:url");
const { chromium } = await import("playwright");

export async function checkSearchGraph() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [], requests = [];
    let failure = null, graphStatus = "ok", disabled = false, noCode = false;
    page.on("pageerror", e => errors.push(String(e)));
    const root = new URL("../src/ragdbman/static/", import.meta.url);
    const cols = [
      { id: "c", name: "code", kind: "source_code", graph: { available: true, enabled: true, entities: 4, relationships: 6 }},
      { id: "d", name: "docs", kind: "general" },
      { id: "k", name: "cards", kind: "knowledge_cards", knowledge_cards: { default_top_k: 5, min_similarity: .65 }}
    ];
    const entity = { entity_id: "entity-1", name: "parse_config", qualified_name: "parse_config", kind: "function",
      provenance: { source_path: "src/config.py", line_start: 3, line_end: 8 }};
    const raw = { results: [{ rank:1,collection:"code",kind:"source_code",title:"src/config.py:3-8",
      content:"<img src=x onerror='window.pwned=1'>",relevance:{score:.5,policy:"bm25_strength"},
      provenance:{},graph_context:{available:true,entities:[{provenance:{source_id:"s"}}]}}],
      collections_searched:["code"],warnings:[],effective_options:{} };
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => { throw Error("denied"); } } });
    });
    await page.route("http://ragdbman.test/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if(path.startsWith("/static/")){
        const file=path.split("/").pop();
        return route.fulfill({ body: await readFile(new URL(file,root)), contentType: file.endsWith(".js")?"text/javascript":"text/css" });
      }
      if(path==="/api/collections-list"){
        const items=structuredClone(cols);items[0].graph.enabled=!disabled;
        return route.fulfill({ json:noCode?items.slice(1):items });
      }
      if(path.startsWith("/api/")){
        const body=route.request().postDataJSON();requests.push({path,body});
        if(failure){const f=failure;failure=null;return route.fulfill({status:503,contentType:f==="plain"?"text/plain":"application/json",body:f==="plain"?"Service unavailable":JSON.stringify({message:"Query failed"})});}
        if(body.format==="llm")return route.fulfill({contentType:"text/plain; charset=utf-8",body:"# Result 1\nFile: src/config.py\nCalls: read_file()\n<img src=x onerror='window.pwned=1'>"});
        if(path==="/api/corpus-graph")return route.fulfill({json:{collection:"code",action:body.action,status:graphStatus,
          limitation:"Best-effort static analysis.",truncated:true,candidates:[entity],
          entities:[entity],relationships:[{from_name:"parse_config",kind:"calls",target_name:"read_file",
            resolution:"unresolved",provenance:entity.provenance}],chains:[]}});
        if(path==="/api/corpus-query"&&body.collections[0]==="cards")return route.fulfill({json:{results:[{
          rank:1,collection:"cards",kind:"knowledge_card",title:"Queue card",content:{title:"Queue card",confidence:1,codes:["print('queue')"]},
          relevance:{score:1,policy:"confidence_weighted"},provenance:{}}],warnings:[],collections_searched:["cards"]}});
        return route.fulfill({json:raw});
      }
      return route.fulfill({body:await readFile(new URL("index.html",root)),contentType:"text/html"});
    });
    const go=async path=>{await page.goto("http://ragdbman.test"+path);await page.locator("h1").waitFor();};
    const choose=async(name,value)=>page.locator(`[name="${name}"]`).selectOption(value);
    const search=async()=>{await page.getByTestId("button-search").click();await page.waitForFunction(()=>!document.querySelector("#search").dataset.busy);};
    await go("/collections/code/corpus-query");
    await page.getByTestId("input-query").fill("parse_config");
    await choose("mode","keyword");await search();
    assert.equal(requests.at(-1).body.format,"raw");
    assert.equal(requests.at(-1).body.include_graph_context,null);
    assert.equal(await page.locator("#results img").count(),0);
    await page.getByRole("link",{name:"Explore source graph"}).click();
    await page.getByTestId("button-graph-query").waitFor();
    assert.equal(await page.getByTestId("input-graph-source").inputValue(),"s");
    await go("/collections/code/corpus-query");
    await page.getByTestId("input-query").fill("parse_config");
    await choose("format","llm");await choose("graph_context","false");await search();
    assert.equal(requests.at(-1).body.include_graph_context,false);
    assert.equal(requests.at(-1).body.format,"llm");
    assert.match(await page.getByTestId("response-text").textContent(),/Calls: read_file/);
    assert.equal(await page.locator("#results img").count(),0);
    await page.getByTestId("copy-response").click();
    assert.match(await page.locator("#copy-status").textContent(),/Response selected/);
    assert.equal(await page.evaluate(()=>getSelection().toString()),await page.getByTestId("response-text").textContent());
    await choose("format","raw");await choose("graph_context","true");await search();
    assert.equal(requests.at(-1).body.include_graph_context,true);
    for(const kind of ["plain","json"]){failure=kind;await search();assert.match(await page.locator("#results").textContent(),kind==="plain"?/Service unavailable/:/Query failed/);assert.equal(await page.getByTestId("button-search").isEnabled(),true);}
    await go("/corpus-query");
    await page.getByTestId("input-query").fill("config");
    for(const checkbox of await page.locator('[name="collection"]').all())await checkbox.uncheck();
    const count=requests.length;await search();assert.equal(requests.length,count);
    assert.match(await page.locator("#feedback").textContent(),/Select at least one/);
    await page.locator('[name="collection"][value="code"]').check();await choose("format","llm");await search();
    assert.equal(requests.at(-1).path,"/api/corpus-query");
    await go("/collections/cards/corpus-query");
    await page.getByTestId("input-query").fill("queue");await choose("mode","semantic");
    await search();assert.equal(requests.at(-1).path,"/api/corpus-query");
    await choose("format","llm");await choose("perspective","general");await search();
    assert.equal(requests.at(-1).path,"/api/corpus-query");
    assert.equal(requests.at(-1).body.mode,"semantic");assert.equal(requests.at(-1).body.perspective,"general");
    assert.equal(requests.at(-1).body.minimum_score,.65);
    await go("/corpus-graph");
    assert.equal(await page.locator('[name="collection"] option').count(),1);
    graphStatus="ambiguous";await page.getByTestId("input-graph-selector").fill("parse_config");
    const graphRun=async()=>{await page.getByTestId("button-graph-query").click();await page.waitForFunction(()=>!document.querySelector("#graph-form").dataset.busy);};
    await graphRun();await page.getByTestId("button-use-entity").first().click();
    assert.equal(await page.locator('[name="selector_type"]').inputValue(),"entity_id");
    assert.equal(await page.getByTestId("input-graph-selector").inputValue(),"entity-1");
    assert.equal(await page.locator('[name="action"]').inputValue(),"neighbors");
    await page.locator("#graph-options summary").click();
    await page.locator('[name="depth"]').fill("2");await page.locator('[name="limit"]').fill("10");
    await choose("direction","both");await page.locator('[name="relationship"][value="calls"]').check();
    graphStatus="ok";await graphRun();
    assert.equal(JSON.stringify(requests.at(-1).body),JSON.stringify({collection:"code",action:"neighbors",format:"raw",depth:2,limit:10,entity_id:"entity-1",direction:"both",relationships:["calls"]}));
    await page.locator('[name="relationship"][value="calls"]').uncheck();
    for(const action of ["callers","callees","dependencies","inheritance","impact"]){
      await choose("action",action);await graphRun();assert.equal(requests.at(-1).body.action,action);
      assert.equal("direction" in requests.at(-1).body,false);
    }
    await choose("format","llm");await graphRun();assert.match(await page.getByTestId("response-text").textContent(),/Calls:/);
    assert.equal(await page.locator("#graph-results img").count(),0);
    await choose("format","raw");failure="plain";await graphRun();assert.match(await page.locator("#graph-results").textContent(),/Service unavailable/);
    disabled=true;await go("/corpus-graph");assert.equal(await page.getByTestId("button-graph-query").isDisabled(),true);
    assert.match(await page.locator("#graph-summary").textContent(),/disabled/);disabled=false;
    noCode=true;await go("/corpus-graph");assert.match(await page.locator("main").textContent(),/No source-code collections/);noCode=false;
    await go("/collections/docs/corpus-graph");assert.match(await page.locator("main").textContent(),/Source-code collections only/);
    await go("/corpus-graph");
    await page.setViewportSize({width:375,height:812});
    await page.getByTestId("button-graph-query").click();
    await page.waitForFunction(()=>!document.querySelector("#graph-form").dataset.busy);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator("#theme").click();
    assert.equal(await page.locator("body").count(),1);
    assert.deepEqual(errors,[]);
    console.log("Search/graph browser regression passed: formats, filters, cards, actions, selection, errors, safety and mobile.");
  } finally {await browser.close();}
}
if(typeof process!=="undefined"&&process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))await checkSearchGraph();
