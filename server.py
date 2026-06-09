"""Cloud Run entrypoint — one FastAPI app, two front doors.

  /dev-ui   ADK's built-in agent UI (the reasoning trace; for hackathon judges).
  /demo     SchedulerRX-styled before/after block calendar (for prospects/the video),
            rendered from `realsolver.demo_payload` — deterministic, no LLM dependency.

`get_fast_api_app(agents_dir="adk_app", web=True)` builds the ADK app + UI; we add the
/demo routes to that same app. The agent's McpToolset spawns `python -m agent.mcp_server`
(cwd=/app), which builds the real CP-SAT model on the vendored solver snapshot.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so `agent` resolves regardless of cwd

from fastapi.responses import HTMLResponse, JSONResponse
from google.adk.cli.fast_api import get_fast_api_app

from agent import realsolver

_AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adk_app")
app = get_fast_api_app(agents_dir=_AGENTS_DIR, web=True)

# --- /demo: deterministic before/after calendar (cached; no LLM) ---
_demo_cache: dict[str, dict] = {}


def _get_demo(scenario: str) -> dict:
    if scenario not in _demo_cache:
        _demo_cache[scenario] = realsolver.anonymize_pods(realsolver.demo_payload(scenario))
    return _demo_cache[scenario]


@app.get("/demo/data")
def demo_data(scenario: str = "em_block_gap"):
    return JSONResponse(_get_demo(scenario))


@app.get("/demo", response_class=HTMLResponse)
def demo_page():
    return _DEMO_HTML


_DEMO_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SchedulerRX · Constraint Debugger</title>
<style>
  :root{ --slate:#1e293b; --slate2:#334155; --gold:#c9a227; --cream:#fbf8ef; --line:#e7e2d4;
         --red:#b42318; --redbg:#fde8e6; --green:#15803d; --greenbg:#e7f5ec; }
  *{box-sizing:border-box} html,body{margin:0}
  body{font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--slate);
       background:var(--cream)}
  header{background:var(--slate);color:#fff;padding:18px 28px}
  header h1{margin:0;font-size:20px;letter-spacing:.2px}
  header h1 b{color:var(--gold)}
  header .sub{opacity:.8;font-size:13px;margin-top:3px}
  .wrap{max-width:1100px;margin:22px auto;padding:0 20px}
  .scenario{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin-bottom:18px}
  .controls{display:flex;gap:10px;align-items:center;margin:18px 0 10px}
  .toggle{display:inline-flex;border:1px solid var(--slate);border-radius:999px;overflow:hidden}
  .toggle button{border:0;background:#fff;color:var(--slate);padding:8px 20px;font-weight:600;cursor:pointer}
  .toggle button.on{background:var(--slate);color:#fff}
  .banner{padding:10px 16px;border-radius:8px;font-weight:600;margin:6px 0 16px;display:inline-block}
  .banner.before{background:var(--redbg);color:var(--red);border:1px solid #f2c4bf}
  .banner.after{background:var(--greenbg);color:var(--green);border:1px solid #bfe3cb}
  table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{border:1px solid var(--line);padding:7px 9px;text-align:center;font-size:13px;vertical-align:middle}
  th{background:#f4efe2;font-weight:600}
  th.shift{text-align:left;white-space:nowrap;background:#efe9da}
  td.empty{color:#bbb}
  td.night{background:#faf7ee}
  .cell-names{font-weight:600}
  td.gap.before{background:var(--redbg);color:var(--red);font-weight:700}
  td.gap.after{background:var(--greenbg);color:var(--green);font-weight:700}
  .thu{outline:2px solid var(--gold);outline-offset:-2px}
  .fix{background:#fff;border:1px solid var(--line);border-left:4px solid var(--gold);border-radius:8px;
       padding:14px 18px;margin-top:18px}
  .fix h3{margin:0 0 8px;font-size:15px}
  .fix ul{margin:6px 0 0;padding-left:20px} .fix li{margin:2px 0}
  .caught{color:var(--slate2);font-style:italic;margin-top:8px}
  .verified{display:inline-block;background:var(--green);color:#fff;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:700}
  footer{color:#8a8472;font-size:12px;text-align:center;margin:26px 0}
  a{color:var(--gold)}
</style></head>
<body>
<header>
  <h1><b>SchedulerRX</b> · Constraint Debugger</h1>
  <div class="sub">When an ACGME-compliant schedule can't be solved, the agent explains why — and only shows fixes the solver re-verified.</div>
  <div class="sub" style="opacity:.65;font-size:12px;margin-top:3px">Google for Startups AI Agents Challenge · built on Google Cloud Vertex AI</div>
</header>
<div class="wrap">
  <div class="scenario" id="scenario">Loading the real scheduling model…</div>
  <div class="controls">
    <div class="toggle">
      <button id="btnBefore" class="on" onclick="setMode('before')">Before</button>
      <button id="btnAfter" onclick="setMode('after')">After fix</button>
    </div>
    <span id="banner" class="banner before">INFEASIBLE — a shift can't be staffed</span>
  </div>
  <div id="grid"></div>
  <div class="fix" id="fix" style="display:none"></div>
  <footer>Real OR-Tools CP-SAT model · diagnosis + fixes verified by re-solving · <a href="/dev-ui">see the agent reason ↗</a></footer>
</div>
<script>
const WK=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
let DATA=null, MODE='before';
function wd(iso){const [y,m,d]=iso.split('-').map(Number);return WK[new Date(y,m-1,d).getDay()];}
function key(si,date){return si+'|'+date;}

function render(){
  if(!DATA) return;
  document.getElementById('scenario').innerHTML =
    '<b>'+ (DATA.scenario||'') +'</b> — '+ (DATA.description||'');
  // build lookup: (shift_instance_id|date) -> [names]
  const cell={}; (DATA.after_schedule||[]).forEach(e=>{
    const k=key(e.metadata.shift_instance_id, e.date); (cell[k]=cell[k]||[]).push(e.resident_name.replace('Dr. ',''));
  });
  const gap=new Set((DATA.gap_cells||[]).map(g=>key(g.shift_instance,g.date)));
  const shifts=DATA.shifts||[], dates=DATA.dates||[];
  let h='<table><thead><tr><th class="shift">Shift</th>';
  dates.forEach(d=>{h+='<th'+(wd(d)==='Thu'?' class="thu"':'')+'>'+wd(d)+'<br><small>'+d.slice(5)+'</small></th>';});
  h+='</tr></thead><tbody>';
  shifts.forEach(s=>{
    const label=s.code[0].toUpperCase()+s.code.slice(1)+' · Pod '+s.location.toUpperCase();
    h+='<tr><th class="shift">'+label+'</th>';
    dates.forEach(d=>{
      const k=key(s.id,d), isGap=gap.has(k), names=cell[k]||[];
      let cls=s.is_night?'night ':'';
      if(isGap){
        cls+='gap '+MODE+' thu';
        h+='<td class="'+cls+'">'+(MODE==='before'?'✗ unstaffable':'✓ '+names.join(', '))+'</td>';
      } else {
        h+='<td class="'+cls+(names.length?'':'empty')+'">'+(names.length?'<span class="cell-names">'+names.join(', ')+'</span>':'—')+'</td>';
      }
    });
    h+='</tr>';
  });
  h+='</tbody></table>';
  document.getElementById('grid').innerHTML=h;
  // banner + fix
  const ban=document.getElementById('banner');
  if(MODE==='before'){ ban.className='banner before';
    ban.textContent='INFEASIBLE — Thursday night cannot be staffed (every eligible resident is blocked)'; }
  else { ban.className='banner after'; ban.textContent='FEASIBLE ✓ — verified fix applied'; }
  const fix=document.getElementById('fix');
  if(MODE==='after' && (DATA.fix_labels||[]).length){
    fix.style.display='block';
    fix.innerHTML='<h3>Verified fix <span class="verified">re-solved ✓</span></h3><ul>'+
      DATA.fix_labels.map(l=>'<li>'+l+'</li>').join('')+'</ul>'+
      '<div class="caught">A single cancellation was caught as insufficient — both night pods require coverage, so the verified fix composes two relaxations.</div>'+
      ((DATA.certificate&&DATA.certificate.proven_minimal)?'<div class="caught">✓ <b>Proven minimal</b> — '+DATA.certificate.resolves+' re-solves confirm each change is necessary; remove any one and it’s infeasible again.</div>':'');
  } else { fix.style.display='none'; }
}
function setMode(m){MODE=m;
  document.getElementById('btnBefore').className=m==='before'?'on':'';
  document.getElementById('btnAfter').className=m==='after'?'on':'';
  render();}
fetch('/demo/data').then(r=>r.json()).then(d=>{DATA=d; if(d.localized===false){
  document.getElementById('grid').innerHTML='<p>'+(d.message||'Not localized.')+'</p>';} render();})
 .catch(e=>{document.getElementById('grid').innerHTML='<p>Failed to load: '+e+'</p>';});
</script>
</body></html>
"""
