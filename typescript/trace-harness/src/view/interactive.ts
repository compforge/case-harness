import { lazyFeatures } from "../feature";
import type { TraceContext } from "../model/context";
import type { Finding, Node } from "../model/node";
import type { DisplayNode } from "./display";
import { renderDisplay } from "./engine";

const ATTR_TRUNCATE = 4000;

function htmlEscape(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[char]!);
}

function displayPayload(context: TraceContext, display: DisplayNode, byId: Map<string, Node>): Record<string, unknown> {
  const children = display.children.map((child) => displayPayload(context, child, byId));
  const findings = display.findings.map((finding) => ({
    severity: finding.severity,
    source: finding.source,
    note: finding.note ?? "",
  }));
  const node = display.kind && display.node_ids.length ? byId.get(display.node_ids[0]!) : undefined;
  if (node) {
    const features = Object.fromEntries(
      Object.entries(lazyFeatures(node, context.view(), (spanId) => context.raw_attr(spanId)))
        .filter(([, value]) => value !== undefined && value !== null && value !== "")
        .map(([key, value]) => [key, typeof value === "string" ? value : JSON.stringify(value)]),
    );
    return {
      node_id: node.node_id,
      kind: display.kind,
      name: display.name,
      service: node.service ?? "",
      start_ms: node.start_ms,
      duration_ms: Number(node.facts.wall_ms ?? node.duration_ms),
      has_error: node.has_error,
      error: node.has_error ? context.error_text(node.error_anchor) : "",
      brief: display.brief.map((field) => `${field.label}=${field.value}`).join("  "),
      findings,
      facts: Object.fromEntries(
        Object.entries(node.facts)
          .filter(([key]) => !key.startsWith("_"))
          .map(([key, value]) => [key, String(value)]),
      ),
      features,
      span_ids: node.span_ids,
      primary_span_id: node.primary_span_id,
      error_span_ids: node.error_span_ids,
      folded: display.folded,
      children,
    };
  }
  const nodes = display.node_ids.map((id) => byId.get(id)).filter((item): item is Node => Boolean(item));
  const start = nodes.length ? Math.min(...nodes.map((item) => item.start_ms)) : 0;
  const end = nodes.length ? Math.max(...nodes.map((item) => item.end_ms)) : 0;
  return {
    node_id: display.node_ids.length ? `fold:${display.node_ids.slice(0, 3).join("·")}` : `fold:${display.name}`,
    kind: "",
    name: display.name,
    service: "",
    start_ms: start,
    duration_ms: end - start,
    has_error: false,
    error: "",
    brief: display.brief.map((field) => `${field.label}=${field.value}`).join("  "),
    findings,
    facts: {},
    features: {},
    span_ids: [],
    primary_span_id: "",
    error_span_ids: [],
    folded: display.folded,
    children,
  };
}

function spanPayload(context: TraceContext, spanId: string): Record<string, unknown> {
  const span = context.spans.get(spanId)!;
  const attrs = Object.fromEntries(Object.entries(span.attrs).map(([key, value]) => {
    let text = typeof value === "string" ? value : JSON.stringify(value);
    if (text.length > ATTR_TRUNCATE) {
      text = `${text.slice(0, ATTR_TRUNCATE)}\n…[已截断，共 ${text.length} 字符；完整原文按 span_id 下钻]`;
    }
    return [key, text];
  }));
  return {
    service: span.service ?? "",
    operation: span.name,
    duration_ms: span.dur_ms,
    has_error: span.has_error,
    error: span.has_error ? context.error_text(spanId) : "",
    attrs,
  };
}

const CSS = String.raw`
*{box-sizing:border-box}:root{--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
body{font:13px/1.5 var(--mono);margin:0;background:#f6f7f9;color:#1a1a1a}
header{background:#1f2937;color:#fff;padding:8px 16px;display:flex;gap:16px;align-items:center}
header h1{font-size:13px;margin:0;font-weight:normal}header b{color:#93c5fd}
header button{font:11px var(--mono);background:#374151;color:#e5e7eb;border:0;border-radius:4px;padding:2px 8px;cursor:pointer}
nav.tabs{display:flex;gap:2px}nav.tabs button.active{background:#2563eb;color:#fff}
.wrap{display:flex;height:calc(100vh - 35px)}#view-flame{display:none;height:calc(100vh - 35px);overflow:auto;background:#fff;padding:12px 16px}
.tree{flex:0 0 52%;max-width:760px;overflow:auto;border-right:1px solid #e5e7eb;background:#fff;padding:8px 0}
.pane{flex:1;overflow:auto;padding:16px}.row{white-space:nowrap;cursor:pointer;font-size:12px;padding:2px 8px;border-left:3px solid transparent;display:flex;align-items:baseline;gap:6px}
.row:hover{background:#f1f5f9}.row.sel{background:#e0edff;border-left-color:#3b82f6}.row.err{color:#b91c1c}.row.err.sel{background:#fee2e2;border-left-color:#dc2626}
.tw{display:inline-block;width:14px;color:#9ca3af;cursor:pointer;text-align:center;flex:none}.kind{font-size:10px;border-radius:3px;padding:0 5px;flex:none;color:#fff;background:#9ca3af}
.kind.agent{background:#7c3aed}.kind.framework,.kind.node{background:#2563eb}.kind.model-call{background:#059669}.kind.tool-call{background:#d97706}.kind.action{background:#0891b2}.kind.service{background:#6b7280}
.dur{color:#6b7280;flex:none}.brief{color:#0d9488;font-size:11px;overflow:hidden;text-overflow:ellipsis}.errdot{color:#dc2626;font-weight:bold;flex:none}
.pane h2{font-size:14px;margin:0 0 4px}.meta{color:#6b7280;font-size:12px;margin-bottom:12px}.findings{margin:0 0 14px;padding:8px 10px;border:1px solid #e5e7eb;border-radius:4px;background:#fff}
.findings div{font-size:12px;margin:2px 0}.findings .f-error{color:#b91c1c}.findings .f-warn{color:#b45309}.findings .f-info{color:#6b7280}
table.facts{border-collapse:collapse;margin-bottom:14px}table.facts td{border:1px solid #e5e7eb;padding:3px 10px;font-size:12px}table.facts td:first-child{background:#f9fafb;color:#374151}
.feat{margin:0 0 10px;border:1px solid #e5e7eb;border-radius:4px;background:#fff;overflow:hidden}.feat-h{display:flex;justify-content:space-between;align-items:center;padding:5px 10px;font-size:12px;background:#f9fafb;color:#374151;cursor:pointer}.feat-body{margin:0;padding:8px 10px;font-size:11px;white-space:pre-wrap;word-break:break-all;max-height:300px;overflow:auto;display:none}.feat.open .feat-body{display:block}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}.chip{font-size:11px;border:1px solid #d1d5db;border-radius:4px;padding:2px 8px;cursor:pointer;background:#fff}.chip.sel{background:#e0edff;border-color:#3b82f6}.chip.errc{border-color:#dc2626;color:#b91c1c}.tag{color:#6b7280}
dl.attrs{margin:0}dl.attrs dt{font-size:11px;color:#6b7280;margin-top:10px}dl.attrs dd{margin:2px 0 0;background:#fff;border:1px solid #e5e7eb;border-radius:4px;padding:6px 8px;white-space:pre-wrap;word-break:break-all;font-size:12px;max-height:340px;overflow:auto}
.faxis{position:relative;height:18px;color:#6b7280;font-size:10px;border-bottom:1px solid #e5e7eb;margin-bottom:6px}.faxis span{position:absolute;transform:translateX(-50%);white-space:nowrap}.flame{position:relative}
.fcell{position:absolute;height:18px;border-radius:2px;font-size:10px;color:#fff;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;padding:1px 4px;cursor:pointer;border:1px solid rgba(255,255,255,.55)}.fcell:hover{filter:brightness(1.18)}.fcell.err{box-shadow:inset 0 0 0 2px #dc2626}
`;

const SCRIPT = String.raw`
const TREE=__TREE__,SPANS=__SPANS__,KCOLOR={agent:'#7c3aed',framework:'#2563eb',node:'#2563eb','model-call':'#059669','tool-call':'#d97706',action:'#0891b2',service:'#6b7280'};
const treeEl=document.getElementById('tree'),paneEl=document.getElementById('pane'),byId={},parentOf={},boxOf={},twOf={};
function esc(s){return String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}
function fmtMs(ms){if(ms<1)return(ms*1000).toFixed(0)+'µs';if(ms<1000)return ms.toFixed(0)+'ms';const s=ms/1000;return s<60?s.toFixed(2)+'s':Math.floor(s/60)+'m'+(s%60).toFixed(1)+'s';}
function renderInto(n,depth,parent){byId[n.node_id]=n;parentOf[n.node_id]=parent&&parent.node_id;const box=document.createElement('div'),row=document.createElement('div');row.className='row'+(n.has_error?' err':'');row.dataset.id=n.node_id;row.style.paddingLeft=(depth*16+8)+'px';
const tw=document.createElement('span');tw.className='tw';tw.textContent=n.children.length?'▾':'·';row.appendChild(tw);if(n.kind){const k=document.createElement('span');k.className='kind '+n.kind;k.textContent=n.kind;row.appendChild(k);}const nm=document.createElement('span');nm.textContent=n.name;row.appendChild(nm);const dur=document.createElement('span');dur.className='dur';dur.textContent=fmtMs(n.duration_ms);row.appendChild(dur);if(n.brief){const b=document.createElement('span');b.className='brief';b.textContent='('+n.brief+')';row.appendChild(b);}if(n.has_error){const e=document.createElement('span');e.className='errdot';e.textContent='[ERROR]';row.appendChild(e);}box.appendChild(row);const kids=document.createElement('div');box.appendChild(kids);boxOf[n.node_id]=kids;twOf[n.node_id]=tw;n.children.forEach(c=>kids.appendChild(renderInto(c,depth+1,n)));if(n.folded&&n.children.length){kids.style.display='none';tw.textContent='▸';}tw.onclick=ev=>{ev.stopPropagation();const open=kids.style.display!=='none';kids.style.display=open?'none':'';tw.textContent=n.children.length?(open?'▸':'▾'):'·';};row.onclick=()=>select(n.node_id);return box;}
function facts(n){const rows=Object.entries(n.facts||{});return rows.length?'<table class="facts">'+rows.map(([k,v])=>'<tr><td>'+esc(k)+'</td><td>'+esc(v)+'</td></tr>').join('')+'</table>':'';}
function findings(n){const marks={error:'✗',warn:'▲',info:'·'};return(n.findings||[]).length?'<div class="findings">'+n.findings.map(f=>'<div class="f-'+esc(f.severity)+'">'+(marks[f.severity]||'·')+' ['+esc(f.source)+'] '+esc(f.note)+'</div>').join('')+'</div>':'';}
function features(n){const rows=Object.entries(n.features||{});return rows.length?'<div class="meta">特征：</div>'+rows.map(([k,v])=>'<div class="feat"><div class="feat-h">'+esc(k)+'</div><pre class="feat-body">'+esc(v)+'</pre></div>').join(''):'';}
function unfold(id){let p=parentOf[id];while(p){const b=boxOf[p];if(b&&b.style.display==='none'){b.style.display='';twOf[p].textContent='▾';}p=parentOf[p];}}
function select(id){document.querySelectorAll('.row.sel').forEach(r=>r.classList.remove('sel'));unfold(id);const row=document.querySelector('.row[data-id="'+CSS.escape(id)+'"]');if(row){row.classList.add('sel');row.scrollIntoView({block:'nearest'});}const n=byId[id];if(!n)return;location.hash=id;paneEl.innerHTML='<h2>'+esc(n.name)+'</h2><div class="meta">'+esc(n.kind)+' · '+fmtMs(n.duration_ms)+(n.service?' · '+esc(n.service):'')+(n.has_error?' · <b style="color:#dc2626">ERROR：'+esc(n.error)+'</b>':'')+'</div>'+findings(n)+facts(n)+features(n)+'<div class="meta">溯源 span（'+n.span_ids.length+'）：</div><div class="chips">'+n.span_ids.map(sid=>'<span class="chip'+((n.error_span_ids||[]).includes(sid)?' errc':'')+'" data-sid="'+esc(sid)+'">'+(sid===n.primary_span_id?'primary':'卫星')+' · '+esc((SPANS[sid]||{}).operation||sid)+'</span>').join('')+'</div><div id="attrs"></div>';paneEl.querySelectorAll('.chip').forEach(c=>c.onclick=()=>showSpan(c.dataset.sid));paneEl.querySelectorAll('.feat-h').forEach(h=>h.onclick=()=>h.parentElement.classList.toggle('open'));showSpan((n.error_span_ids||[])[0]||n.primary_span_id);}
function showSpan(sid){paneEl.querySelectorAll('.chip').forEach(c=>c.classList.toggle('sel',c.dataset.sid===sid));const sp=SPANS[sid],box=document.getElementById('attrs');if(!sp){box.innerHTML='<div class="meta">span 不在快照内</div>';return;}box.innerHTML='<div class="meta">span '+esc(sid)+' · '+esc(sp.operation)+' · '+fmtMs(sp.duration_ms)+'</div><dl class="attrs">'+Object.entries(sp.attrs).map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl>';}
TREE.roots.forEach(r=>treeEl.appendChild(renderInto(r,0,null)));document.getElementById('expand').onclick=()=>document.querySelectorAll('.tw').forEach(t=>{if(t.textContent==='▸')t.click();});document.getElementById('fold').onclick=()=>document.querySelectorAll('.tw').forEach(t=>{if(t.textContent==='▾')t.click();});
const views={stack:document.getElementById('view-stack'),flame:document.getElementById('view-flame')};let flameBuilt=false;function showView(v){Object.entries(views).forEach(([k,e])=>e.style.display=k===v?(k==='stack'?'flex':'block'):'none');document.querySelectorAll('nav.tabs button').forEach(b=>b.classList.toggle('active',b.dataset.v===v));if(v==='flame'&&!flameBuilt){buildFlame();flameBuilt=true;}}document.querySelectorAll('nav.tabs button').forEach(b=>b.onclick=()=>showView(b.dataset.v));
function buildFlame(){const box=document.getElementById('flame'),axis=document.getElementById('faxis');let t0=Infinity,t1=-Infinity,maxD=0;(function scan(ns,d){ns.forEach(n=>{t0=Math.min(t0,n.start_ms);t1=Math.max(t1,n.start_ms+n.duration_ms);maxD=Math.max(maxD,d);scan(n.children,d+1);});})(TREE.roots,0);const span=Math.max(t1-t0,1e-6),rowH=20;box.style.height=((maxD+1)*rowH+4)+'px';for(let i=0;i<=10;i++){const s=document.createElement('span');s.style.left=(i*10)+'%';s.textContent=fmtMs(span*i/10);axis.appendChild(s);}(function place(ns,d){ns.forEach(n=>{const c=document.createElement('div');c.className='fcell'+(n.has_error?' err':'');c.style.left=((n.start_ms-t0)/span*100)+'%';c.style.width=Math.max(n.duration_ms/span*100,.15)+'%';c.style.top=(d*rowH)+'px';c.style.background=KCOLOR[n.kind]||'#9ca3af';c.textContent=n.name;c.onclick=()=>{showView('stack');select(n.node_id);};box.appendChild(c);place(n.children,d+1);});})(TREE.roots,0);}
function firstError(ns){for(const n of ns){if(n.has_error)return n.node_id;const child=firstError(n.children);if(child)return child;}return null;}const wanted=location.hash.slice(1);select((wanted&&byId[wanted]&&wanted)||firstError(TREE.roots)||(TREE.roots[0]&&TREE.roots[0].node_id));
`;

export function renderInteractive(
  context: TraceContext,
  findings: Record<string, Finding[]> = {},
): string {
  const byId = new Map(context.nodes.map((node) => [node.node_id, node]));
  const roots = renderDisplay(context.view(), findings);
  const tree = { roots: roots.map((root) => displayPayload(context, root, byId)) };
  const referenced = new Set(context.nodes.flatMap((node) => node.span_ids));
  const spans = Object.fromEntries(
    [...referenced].filter((spanId) => context.spans.has(spanId)).map((spanId) => [spanId, spanPayload(context, spanId)]),
  );
  const embed = (value: unknown) => JSON.stringify(value).replaceAll("</", "<\\/");
  const script = SCRIPT.replace("__TREE__", embed(tree)).replace("__SPANS__", embed(spans));
  const title = htmlEscape(context.trace_id);
  const errorCount = context.nodes.filter((node) => node.has_error).length;
  return `<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>trace ${title}</title><style>${CSS}</style></head>
<body><header><h1>trace <b>${title}</b> · ${context.nodes.length} nodes / ${context.spans.size} spans · errors ${errorCount}</h1>
<nav class="tabs"><button data-v="stack" class="active">调用栈</button><button data-v="flame">火焰图</button></nav><button id="expand">全部展开</button><button id="fold">全部折叠</button></header>
<div class="wrap" id="view-stack"><div class="tree" id="tree"></div><div class="pane" id="pane"></div></div>
<div id="view-flame"><div class="faxis" id="faxis"></div><div class="flame" id="flame"></div></div><script>${script}</script></body></html>\n`;
}
