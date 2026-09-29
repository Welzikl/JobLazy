"""Local-only dashboard for JobLazy's existing queue and terminal engine."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import webbrowser
from csv import DictWriter
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .common import ROOT, NeedsInput, digest, read_json
from .model import CodexModel
from .pipeline import processing_priority
from .profiles import load_profile
from .status import summary
from .store import Store
from .work_mode import require_application_work


ASSETS = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobLazy</title><style>
:root{--ink:#17201c;--muted:#65706a;--paper:#f6f5f0;--card:#fff;--line:#dde2da;--green:#2f6d50;--lime:#c8f36a;--amber:#a85c25;--red:#a53d35}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,a{font:inherit}button{cursor:pointer;border:0}.shell{max-width:1400px;margin:auto;padding:28px}.top{display:flex;gap:24px;align-items:flex-start;justify-content:space-between;margin:16px 0 34px}.brand{display:flex;gap:13px;align-items:center}.mark{width:34px;height:34px;border-radius:11px;background:var(--ink);position:relative}.mark:after{content:"";position:absolute;width:13px;height:13px;border-radius:50%;background:var(--lime);right:6px;bottom:6px}h1{font-size:28px;letter-spacing:-1.2px;margin:0}.sub{color:var(--muted);margin:2px 0 0}.actions{display:flex;gap:9px;flex-wrap:wrap}.button{padding:10px 14px;border-radius:9px;background:var(--ink);color:white;text-decoration:none;font-weight:650}.button.secondary{background:transparent;border:1px solid var(--line);color:var(--ink)}.status{display:flex;align-items:center;gap:8px;padding:9px 12px;border-radius:999px;background:#e7efe9;font-size:13px;font-weight:650}.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}.dot.off{background:var(--amber)}.notice{display:none;margin:0 0 20px;padding:13px 15px;border-radius:10px;background:#fff3e9;color:#7e431f}.grid{display:grid;grid-template-columns:1.45fr .85fr;gap:20px}.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px}.eyebrow{color:var(--muted);font-size:12px;font-weight:750;letter-spacing:.09em;text-transform:uppercase}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}.metric{padding:14px;border-radius:12px;background:#f3f5ef}.metric strong{font-size:25px;letter-spacing:-1px;display:block}.metric span{color:var(--muted);font-size:13px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:36px 0 14px}.section-head h2{font-size:19px;letter-spacing:-.5px;margin:0}.filters{display:flex;gap:7px;flex-wrap:wrap}.filter{background:#eef1eb;color:#425048;padding:7px 10px;border-radius:999px}.filter.active{background:var(--ink);color:#fff}.jobs{display:grid;gap:10px}.job{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;padding:16px;border:1px solid var(--line);border-radius:13px;background:#fff}.job h3{font-size:16px;margin:0 0 3px}.meta,.reason{color:var(--muted);font-size:13px}.reason{margin:9px 0 0;max-width:70ch}.score{text-align:right;font-size:13px;font-weight:700;color:var(--green);white-space:nowrap}.score b{display:block;font-size:22px;letter-spacing:-.7px}.empty{padding:28px;color:var(--muted);border:1px dashed var(--line);border-radius:12px;text-align:center}.queue{display:grid;gap:12px}.queue-row{display:flex;align-items:center;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--line)}.queue-row:last-child{border:0}.badge{font-size:12px;font-weight:700;padding:5px 8px;border-radius:999px;background:#eef1eb;color:#435047}.badge.warn{background:#fff0e5;color:#914c21}.boundary{margin-top:18px;padding:15px;border-radius:12px;background:#f0f5ec;color:#35483a;font-size:13px}.foot{color:var(--muted);font-size:12px;margin:20px 0}@media(max-width:820px){.shell{padding:16px}.top{display:block}.actions{margin-top:18px}.grid{grid-template-columns:1fr}.metrics{grid-template-columns:1fr}.job{grid-template-columns:1fr}.score{text-align:left}}
</style></head><body><main class="shell"><header class="top"><div class="brand"><div class="mark"></div><div><h1>JobLazy</h1><p class="sub">A calmer way to run your job search.</p></div></div><div class="actions"><button class="button secondary" id="connect">Connect Codex</button><a class="button" href="#shortlist">View shortlist</a></div></header><div class="notice" id="notice"></div><section class="grid"><article class="panel"><div class="eyebrow">Today</div><div class="metrics" id="metrics"></div></article><aside class="panel"><div class="eyebrow">System</div><div class="queue" id="system"></div><div class="boundary">JobLazy can rank roles, prepare forms and upload a reviewed CV. It always stops before you submit an application.</div></aside></section><section id="shortlist"><div class="section-head"><div><div class="eyebrow">Your queue</div><h2>Roles that need attention</h2></div><div class="filters"><button class="filter active" data-state="active">Active</button><button class="filter" data-state="all">All reviewed</button></div></div><div class="jobs" id="jobs"></div></section><p class="foot">Local only. Your profile, CVs, browser sessions and Codex sign-in stay on this computer.</p></main><script>const token='__TOKEN__';let state='active';const api=(path,options={})=>fetch(path,{...options,headers:{'X-JobLazy-Token':token,'Content-Type':'application/json',...(options.headers||{})}}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error||'Something went wrong');return d});const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function notify(text){const n=document.querySelector('#notice');n.textContent=text;n.style.display='block';setTimeout(()=>n.style.display='none',6500)}function render(data){const usage=data.summary.usage||{};document.querySelector('#metrics').innerHTML=`<div class="metric"><strong>${data.summary.total}</strong><span>roles in your saved queue</span></div><div class="metric"><strong>${usage.job_attempts||0}</strong><span>processing attempts today</span></div><div class="metric"><strong>${usage.model_requests||0}</strong><span>model requests today</span></div>`;const codex=data.codex||{};document.querySelector('#system').innerHTML=`<div class="queue-row"><span>Codex connection</span><span class="badge ${codex.available?'':'warn'}">${codex.available?'Connected':'Needs sign-in'}</span></div><div class="queue-row"><span>Application preparation</span><span class="badge ${data.preparation.paused?'warn':''}">${data.preparation.paused?'Paused':'Ready'}</span></div><div class="queue-row"><span>Final submission</span><span class="badge">Always yours</span></div>`;const cards=data.jobs.length?data.jobs.map(j=>`<article class="job"><div><h3>${esc(j.title)}</h3><div class="meta">${esc(j.company)} · ${esc(j.location)} · ${esc(j.status.replaceAll('_',' '))}</div><p class="reason">${esc(j.reason||'No assessment reason saved yet.')}</p></div><div class="score">${j.score==null?'Review needed':`Fit <b>${j.score}</b>`}</div></article>`).join(''):'<div class="empty">No reviewed roles in this view yet. Use a controlled ranking run to build your shortlist.</div>';document.querySelector('#jobs').innerHTML=cards}async function load(){try{render(await api('/api/overview?state='+state))}catch(e){notify(e.message)}}document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{state=b.dataset.state;document.querySelectorAll('.filter').forEach(x=>x.classList.toggle('active',x===b));load()});document.querySelector('#connect').onclick=async()=>{try{const d=await api('/api/connect',{method:'POST',body:'{}'});notify(d.message)}catch(e){notify(e.message)}};load();setInterval(load,10000);</script></body></html>"""


# Keep the browser UI deliberately small: it is a local control surface for the
# existing engine, rather than a second workflow with its own state.
ASSETS = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JobLazy</title><style>
:root{--ink:#17201c;--muted:#65706a;--paper:#f6f5f0;--line:#dde2da;--lime:#c8f36a;--green:#2f6d50;--warn:#914c21}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}.shell{max-width:1180px;margin:auto;padding:28px}.top,.head,.card-actions,.queue-tools{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.brand{display:flex;gap:12px;align-items:center}.mark{width:34px;height:34px;border-radius:11px;background:var(--ink);position:relative}.mark:after{content:'';position:absolute;width:13px;height:13px;border-radius:50%;background:var(--lime);right:6px;bottom:6px}h1,h2,h3,p{margin:0}h1{font-size:28px;letter-spacing:-1px}.sub,.meta,.reason,.foot{color:var(--muted)}.sub{margin-top:2px}.button{appearance:none;border:0;border-radius:9px;padding:10px 14px;background:var(--ink);color:#fff;font:inherit;font-weight:700;text-decoration:none;cursor:pointer}.secondary{background:transparent;color:var(--ink);border:1px solid var(--line)}.notice{display:none;margin:20px 0;padding:12px 14px;border-radius:10px;background:#fff3e9;color:#7e431f}.grid{display:grid;grid-template-columns:1.45fr .85fr;gap:20px;margin-top:34px}.panel,.job{background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px}.eyebrow{font-size:12px;color:var(--muted);font-weight:800;letter-spacing:.09em;text-transform:uppercase}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}.metric{padding:14px;border-radius:12px;background:#f3f5ef}.metric strong{display:block;font-size:25px}.metric span,.meta,.reason{font-size:13px}.queue-row{display:flex;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--line)}.queue-row:last-child{border:0}.badge,.filter,.sort{border:0;border-radius:999px;padding:6px 10px;background:#eef1eb;color:#435047;font:inherit;font-size:12px;font-weight:700}.badge.warn{background:#fff0e5;color:var(--warn)}.boundary{margin-top:18px;padding:14px;border-radius:12px;background:#f0f5ec;font-size:13px}.head{margin:36px 0 14px}.filters{display:flex;gap:7px;flex-wrap:wrap}.filter{cursor:pointer}.filter.active{background:var(--ink);color:#fff}.jobs{display:grid;gap:10px}.job{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;padding:16px}.job h3{font-size:16px}.reason{margin-top:8px;max-width:78ch;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.score{text-align:right;color:var(--green);font-size:13px;font-weight:700;white-space:nowrap;min-width:62px}.score b{display:block;font-size:25px}.card-actions{margin-top:13px;justify-content:flex-start}.open{color:var(--green);font-size:13px;font-weight:700}.empty{padding:28px;border:1px dashed var(--line);border-radius:12px;color:var(--muted);text-align:center}.foot{font-size:12px;margin:20px 0}@media(max-width:760px){.shell{padding:16px}.grid{grid-template-columns:1fr}.metrics{grid-template-columns:1fr}.job{grid-template-columns:1fr}.score{text-align:left}}
</style></head><body><main class="shell"><header class="top"><div class="brand"><div class="mark"></div><div><h1>JobLazy</h1><p class="sub">A calmer way to run your job search.</p></div></div><div><button class="button secondary" id="tracker">Download tracker</button> <button class="button secondary" id="connect">Connect Codex</button> <a class="button" href="#shortlist">View shortlist</a></div></header><div class="notice" id="notice"></div><section class="grid"><article class="panel"><div class="eyebrow">Today</div><div class="metrics" id="metrics"></div></article><aside class="panel"><div class="eyebrow">System</div><div id="system"></div><div class="boundary">JobLazy can rank roles, prepare forms and upload a reviewed CV. It always stops before you submit an application.</div></aside></section><section id="shortlist"><div class="head"><div><div class="eyebrow">Your queue</div><h2>Choose a role to move forward</h2></div><div class="queue-tools"><div class="filters"><button class="filter active" data-state="active">Active</button><button class="filter" data-state="ready">Ready to prepare</button><button class="filter" data-state="needs_input">Needs input</button><button class="filter" data-state="materials">CV ready</button><button class="filter" data-state="all">All reviewed</button></div><select class="sort" id="sort" aria-label="Sort roles"><option value="priority">Recommended order</option><option value="fit_desc">Highest fit</option><option value="fit_asc">Lowest fit</option></select></div></div><div class="jobs" id="jobs"></div></section><p class="foot">Local only. Your profile, CVs, browser sessions and Codex sign-in stay on this computer.</p></main><script>
const token='__TOKEN__';const initial=__INITIAL__;let state='active';const api=(path,options={})=>fetch(path,{...options,headers:{'X-JobLazy-Token':token,'Content-Type':'application/json',...(options.headers||{})}}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error||'Something went wrong');return d});const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function notify(t){const n=document.querySelector('#notice');n.textContent=t;n.style.display='block';setTimeout(()=>n.style.display='none',7000)}function render(d){const u=d.summary.usage||{};document.querySelector('#metrics').innerHTML=`<div class="metric"><strong>${d.summary.total}</strong><span>roles in your saved queue</span></div><div class="metric"><strong>${u.job_attempts||0}</strong><span>processing attempts today</span></div><div class="metric"><strong>${u.model_requests||0}</strong><span>model requests today</span></div>`;const c=d.codex||{};document.querySelector('#system').innerHTML=`<div class="queue-row"><span>Codex connection</span><span class="badge ${c.available?'':'warn'}">${c.available?'Connected':'Needs sign-in'}</span></div><div class="queue-row"><span>Application preparation</span><span class="badge ${d.preparation.paused?'warn':''}">${d.preparation.paused?'Paused':'Ready'}</span></div><div class="queue-row"><span>Final submission</span><span class="badge">Always yours</span></div>`;document.querySelector('#jobs').innerHTML=d.jobs.length?d.jobs.map(j=>{const open=j.url?`<a class="open" href="${esc(j.url)}" target="_blank" rel="noreferrer">Open posting</a>`:'';const prepare=`<a class="button" href="/application/${esc(j.id)}">Review application</a>`;const score=j.score==null?'Review needed':'Fit <b>'+esc(j.score)+'</b>';return `<article class="job"><div><h3>${esc(j.title)}</h3><div class="meta">${esc(j.company)} · ${esc(j.location)} · ${esc(j.status.replaceAll('_',' '))}</div><p class="reason">${esc(j.reason||'No assessment reason saved yet.')}</p><div class="card-actions">${open}${prepare}</div></div><div class="score">${score}</div></article>`}).join(''):'<div class="empty">No reviewed roles in this view yet.</div>';document.querySelectorAll('[data-prepare]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const d=await api('/api/jobs/'+encodeURIComponent(b.dataset.prepare)+'/prepare',{method:'POST',body:'{}'});notify(d.message)}catch(e){notify(e.message);b.disabled=false}})}async function load(){try{render(await api('/api/overview?state='+state))}catch(e){notify(e.message)}}document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{state=b.dataset.state;document.querySelectorAll('.filter').forEach(x=>x.classList.toggle('active',x===b));load()});document.querySelector('#connect').onclick=async()=>{try{notify((await api('/api/connect',{method:'POST',body:'{}'})).message)}catch(e){notify(e.message)}};document.querySelector('#tracker').onclick=async()=>{try{const r=await fetch('/api/tracker.csv',{headers:{'X-JobLazy-Token':token}});if(!r.ok)throw Error('Tracker download failed');const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='joblazy-opportunities.csv';a.click();URL.revokeObjectURL(u)}catch(e){notify(e.message)}};render(initial);setInterval(load,10000);
</script></body></html>"""

# The queue controls are links only in spirit: the existing local script owns
# their state and refreshes the same local overview endpoint.
ASSETS = ASSETS.replace(
    '<select class="sort" id="sort" aria-label="Sort roles"><option value="priority">Recommended order</option><option value="fit_desc">Highest fit</option><option value="fit_asc">Lowest fit</option></select>',
    '<div class="filters"><button class="filter" data-state="fit_desc">Highest fit</button><button class="filter" data-state="fit_asc">Lowest fit</button></div>',
)
ASSETS = ASSETS.replace(
    '<button class="filter" data-state="all">All reviewed</button>',
    '<button class="filter" data-state="saved">All saved roles</button><button class="filter" data-state="ats">All ATS roles</button><button class="filter" data-state="all">All reviewed</button>',
)
ASSETS = ASSETS.replace(
    "${esc(j.company)} · ${esc(j.location)} · ${esc(j.status.replaceAll('_',' '))}",
    "${esc(j.company)} · ${esc(j.location)} · ${esc(j.ats)} · ${esc(j.status.replaceAll('_',' '))}",
)
for _queue_view in ("active", "ready", "needs_input", "materials", "ats", "saved", "all", "fit_desc", "fit_asc"):
    ASSETS = ASSETS.replace(
        f'data-state="{_queue_view}"',
        f'data-state="{_queue_view}" onclick="location.search=\'?state={_queue_view}\'"',
    )
ASSETS = ASSETS.replace(
    "b.onclick=()=>{state=b.dataset.state;document.querySelectorAll('.filter').forEach(x=>x.classList.toggle('active',x===b));load()}",
    "b.onclick=()=>{location.search='?state='+b.dataset.state}",
)


DIRECT_ATS = {"ashby", "greenhouse", "lever", "smartrecruiters", "amazon", "workday", "teamtailor"}
QUEUE_VIEWS = {"active", "ready", "needs_input", "materials", "ats", "saved", "all", "fit_desc", "fit_asc"}
QUEUE_SORTS = {"priority", "fit_desc", "fit_asc"}


ASSETS = ASSETS.replace('href="#shortlist">View shortlist</a>', 'href="/search">Build your search</a>')
ASSETS = ASSETS.replace('<button class="button secondary" id="connect">Connect Codex</button> <a class="button" href="/search">Build your search</a>',
                        '<a class="button secondary" href="/profile">Update profile</a> <button class="button secondary" id="connect">Connect Codex</button> <a class="button" href="/search">Build your search</a>')
ASSETS = ASSETS.replace('<button class="button secondary" id="tracker">Download tracker</button> ',
                        '<a class="button secondary" href="/profile">Update profile</a> <a class="button secondary" href="/review">Review applications</a> <button class="button secondary" id="tracker">Download tracker</button> ')


def dashboard_data(data, profile_path, state="active", sort="priority", limit=30):
    if state not in QUEUE_VIEWS:
        raise ValueError("Unknown queue view")
    if sort not in QUEUE_SORTS:
        raise ValueError("Unknown queue sort")
    if state in {"fit_desc", "fit_asc"}:
        sort, state = state, "active"
    data = Path(data)
    profile = load_profile(profile_path)
    policy_path = data / "preparation-policy.json"
    if not policy_path.exists():
        policy_path = Path(profile_path).parent / "preparation-policy.json"
    try:
        policy = read_json(policy_path)
    except FileNotFoundError:
        # Match the command-line workflow: an absent policy permits
        # preparation, while an explicit pause remains an operator control.
        policy = {"paused": False}
    except (OSError, ValueError):
        # A malformed policy must fail closed until the user fixes it.
        policy = {"paused": True}
    with closing(Store(data / "jobs.sqlite")) as store:
        report = summary(store, limit=limit, profile=profile)
        allowed = {"ranked", "materials_ready", "needs_input", "manual_review", "retryable", "model_failed", "not_selected"}
        rows = store.list() if state in {"ats", "saved"} else [row for row in store.list() if row["status"] in allowed]
        if state == "active":
            # A live handoff needs the operator's attention; hiding it from
            # Active makes a prepared application appear to disappear.
            rows = [row for row in rows if row["status"] not in {"model_failed", "not_selected"}]
        elif state == "ready":
            rows = [row for row in rows if row["status"] in {"ranked", "materials_ready", "retryable"}]
        elif state == "needs_input":
            rows = [row for row in rows if row["status"] in {"needs_input", "manual_review"}]
        elif state == "materials":
            rows = [row for row in rows if row["status"] == "materials_ready"]
        elif state == "ats":
            rows = [row for row in rows if row["data"].get("ats") in DIRECT_ATS]
        cards = []
        status_priority = {"materials_ready": 3, "ranked": 2, "retryable": 1, "needs_input": 0,
                           "manual_review": -1, "model_failed": -2}
        def card_order(row):
            result = row["result"] or {}; ranking = result.get("ranking") or result
            return (-processing_priority(row["data"], profile), -status_priority.get(row["status"], 0),
                    -(ranking.get("score") or -1), row["id"])
        if sort == "fit_desc":
            rows = sorted(rows, key=lambda row: -((row["result"] or {}).get("ranking", row["result"] or {}).get("score") or -1))
        elif sort == "fit_asc":
            rows = sorted(rows, key=lambda row: ((row["result"] or {}).get("ranking", row["result"] or {}).get("score") is None,
                                                   (row["result"] or {}).get("ranking", row["result"] or {}).get("score") or 0))
        else:
            rows = sorted(rows, key=card_order)
        # The ATS view is an inventory, so do not silently hide unreviewed
        # roles or stop at the normal shortlist-card limit.
        visible_rows = rows if state in {"ats", "saved"} else rows[:limit]
        for row in visible_rows:
            result = row["result"] or {}
            ranking = result.get("ranking") or result
            cards.append({"id": row["id"], "title": row["data"].get("title", "Untitled role"),
                          "company": row["data"].get("company", ""), "location": row["data"].get("location", ""),
                          "status": row["status"], "score": ranking.get("score"),
                          "reason": ranking.get("reason") or result.get("reason"),
                          "url": row["data"].get("url", ""),
                          "ats": row["data"].get("ats") or "other source",
                          "can_prepare": (not bool(policy.get("paused", True)) and
                                          row["status"] in {"ranked", "materials_ready", "needs_input", "retryable"})})
    return {"summary": report, "codex": CodexModel(data / "model-cache").status(),
            "preparation": {"paused": bool(policy.get("paused", True))}, "jobs": cards}


def tracker_csv(data):
    """Export every durable role and its latest recorded state for a spreadsheet."""
    fields = ("id", "company", "title", "location", "source_ats", "status", "fit_score", "fit_reason",
              "posting_url", "observed_at", "updated_at", "latest_event_at", "latest_event", "outcome_note")
    output = StringIO(newline="")
    writer = DictWriter(output, fieldnames=fields)
    writer.writeheader()
    with closing(Store(Path(data) / "jobs.sqlite")) as store:
        events = {}
        for event in store.db.execute("SELECT job_id,status,detail,created FROM events ORDER BY seq"):
            events[event["job_id"]] = dict(event)
        for row in store.list():
            result = row["result"] or {}
            ranking = result.get("ranking") or result
            event = events.get(row["id"], {})
            try:
                detail = json.loads(event.get("detail") or "{}")
            except json.JSONDecodeError:
                detail = {}
            writer.writerow({
                "id": row["id"], "company": row["data"].get("company", ""),
                "title": row["data"].get("title", ""), "location": row["data"].get("location", ""),
                "source_ats": row["data"].get("ats", ""),
                "status": row["status"], "fit_score": ranking.get("score", ""),
                "fit_reason": ranking.get("reason") or result.get("reason", ""),
                "posting_url": row["data"].get("url", ""), "observed_at": row["data"].get("observed_at", ""),
                "updated_at": row["updated"], "latest_event_at": event.get("created", ""),
                "latest_event": event.get("status", ""), "outcome_note": detail.get("note", ""),
            })
    return output.getvalue()


def codex_login_command(data):
    executable = CodexModel(Path(data) / "model-cache").executable
    if not executable:
        return None
    return [str(executable), "login"]


def assist_command(data, profile_path, key, browser_channel="chrome", model_name="gpt-5.6-terra"):
    return [sys.executable, "-m", "joblazy", "--data", str(Path(data).resolve()),
            "assist", key, "--profile", str(Path(profile_path).resolve()), "--browser-channel", browser_channel,
            "--model", model_name, "--ui-session"]


def make_handler(data, profile_path, token, login_launcher=None, assist_launcher=None, browser_channel="chrome", model_preset_name="personal"):
    from .search import SearchController
    from .model_presets import model_preset
    models = model_preset(model_preset_name)
    search = SearchController(data, profile_path, browser_channel,
                              search_model=models['search'], review_model=models['review'])
    from .application_ui import ApplicationController, job_key
    applications = ApplicationController(data, profile_path, models, browser_channel)
    login_launcher = login_launcher or _launch_login
    assist_launcher = assist_launcher or _launch_login
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            return
        def local_request(self):
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host', '').casefold()
            origin = self.headers.get('Origin')
            if host not in allowed or (origin and origin not in {'http://' + value for value in allowed}):
                self.send_json({'error': 'Local dashboard origin required'}, 403)
                return False
            return True
        def send_json(self, value, status=200):
            body = json.dumps(value).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header('Cache-Control', 'no-store')
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if not self.local_request(): return
            parsed = urlparse(self.path)
            if parsed.path.startswith('/application/'):
                try:
                    key = job_key(parsed.path.removeprefix('/application/'))
                    body = (ROOT/'joblazy/application.html').read_text(encoding='utf-8').replace('__TOKEN__', token).replace('__KEY__', key).encode('utf-8')
                    self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body); return
                except ValueError: return self.send_json({'error': 'Invalid role'}, 400)
            if parsed.path.startswith('/api/application/'):
                if self.headers.get('X-JobLazy-Token') != token:
                    return self.send_json({'error': 'Local dashboard token required'}, 403)
                try: return self.send_json(applications.state(parsed.path.removeprefix('/api/application/')))
                except (NeedsInput, ValueError, OSError, KeyError) as error:
                    return self.send_json({'error': str(error)}, 409)
            if parsed.path == '/review':
                if not Path(profile_path).exists():
                    self.send_response(303); self.send_header('Location', '/onboarding'); self.end_headers(); return
                from .review import render_review
                try:
                    profile = load_profile(profile_path)
                    with closing(Store(Path(data) / 'jobs.sqlite')) as store:
                        links = {row['id']: '/review/cv/' + row['id'] + '?token=' + token for row in store.list()}
                        output = render_review(store, data, profile=profile, pdf_links=links)
                    body = Path(output['path']).read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
                except (NeedsInput, OSError, ValueError, KeyError):
                    return self.send_json({'error': 'Application review could not be generated from the saved local data.'}, 409)
            if parsed.path.startswith('/review/cv/'):
                key = parsed.path.removeprefix('/review/cv/')
                supplied = parse_qs(parsed.query).get('token', [''])[0]
                if supplied != token or len(key) != 24 or any(c not in '0123456789abcdef' for c in key):
                    return self.send_json({'error': 'Local review token required'}, 403)
                try:
                    with closing(Store(Path(data) / 'jobs.sqlite')) as store:
                        store.get(key)
                    pdf = Path(data) / 'applications' / key / 'cv.pdf'
                    artifact = read_json(pdf.parent / 'artifact.json')
                    if Path(artifact['path']).resolve() != pdf.resolve() or digest(pdf.read_bytes()) != artifact['sha256']:
                        raise ValueError('CV artifact mismatch')
                    body = pdf.read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'application/pdf')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Disposition', 'inline; filename="reviewed-cv.pdf"')
                    self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
                except (OSError, ValueError, KeyError):
                    return self.send_json({'error': 'The saved CV could not be verified for review.'}, 404)
            if parsed.path == '/profile':
                if not Path(profile_path).exists():
                    self.send_response(303); self.send_header('Location', '/onboarding'); self.end_headers(); return
                body = (ROOT / 'joblazy/profile.html').read_text(encoding='utf-8').replace('__TOKEN__', token).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == '/api/profile':
                if self.headers.get('X-JobLazy-Token') != token:
                    return self.send_json({'error': 'Local dashboard token required'}, 403)
                from .profile_edit import profile_state
                try: return self.send_json(profile_state(profile_path))
                except (NeedsInput, OSError, ValueError): return self.send_json({'error': 'Your saved profile could not be opened.'}, 409)
            if parsed.path == '/api/onboarding':
                if self.headers.get('X-JobLazy-Token') != token:
                    return self.send_json({'error': 'Local dashboard token required'}, 403)
                from .onboarding import onboarding_state
                try: return self.send_json(onboarding_state(data, profile_path, parse_qs(parsed.query).get('draft', [None])[0]))
                except (NeedsInput, ValueError, OSError):
                    return self.send_json({'error': 'The saved intake draft could not be opened. Its original documents are preserved.'}, 409)
            if parsed.path == '/search':
                if not Path(profile_path).exists():
                    self.send_response(303); self.send_header('Location', '/onboarding'); self.end_headers(); return
                body = (ROOT / 'joblazy/search.html').read_text(encoding='utf-8').replace('__TOKEN__', token).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == '/api/search':
                if self.headers.get('X-JobLazy-Token') != token:
                    return self.send_json({'error': 'Local dashboard token required'}, 403)
                try: return self.send_json(search.snapshot())
                except NeedsInput as error: return self.send_json({'error': str(error)}, 409)
            if parsed.path == '/onboarding' or (parsed.path == '/' and not Path(profile_path).exists()):
                body = (ROOT / 'joblazy/onboarding.html').read_text(encoding='utf-8').replace('__TOKEN__', token).replace('__MODEL__', models['application']).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == "/":
                state = parse_qs(parsed.query).get("state", ["active"])[0]
                try:
                    initial = json.dumps(dashboard_data(data, profile_path, state), ensure_ascii=False).replace("<", "\\u003c")
                except ValueError:
                    return self.send_json({"error": "Unknown queue view"}, 400)
                body = ASSETS.replace("__TOKEN__", token).replace("__INITIAL__", initial).encode("utf-8")
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == "/api/overview":
                state = parse_qs(parsed.query).get("state", ["active"])[0]
                sort = parse_qs(parsed.query).get("sort", ["priority"])[0]
                try:return self.send_json(dashboard_data(data, profile_path, state, sort))
                except Exception as error:return self.send_json({"error": str(error)}, 500)
            if parsed.path == "/api/tracker.csv":
                if self.headers.get("X-JobLazy-Token") != token:
                    return self.send_json({"error": "Local dashboard token required"}, 403)
                body = tracker_csv(data).encode("utf-8-sig")
                self.send_response(200); self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="joblazy-opportunities.csv"')
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            self.send_json({"error": "Not found"}, 404)
        def do_POST(self):
            from .work_mode import require_application_work
            if not self.local_request(): return
            if self.headers.get("X-JobLazy-Token") != token:
                return self.send_json({"error": "Local dashboard token required"}, 403)
            if self.path.startswith('/api/application/'):
                from .locking import LockBusy
                try:
                    parts = self.path.removeprefix('/api/application/').split('/')
                    if len(parts) != 2: raise ValueError('Invalid application action')
                    key, action = parts
                    job_key(key)
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 32768: raise ValueError('Application request is empty or too large')
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict): raise ValueError('Expected an application form')
                    if action in {'assess', 'materials'}:
                        return self.send_json(applications.start(key, action), 202)
                    if action == 'answer': return self.send_json(applications.answer(key, payload))
                    if action == 'outcome': return self.send_json(applications.outcome(key, payload))
                    if action == 'resume': return self.send_json(applications.resume(key, payload))
                    if action == 'prepare':
                        require_application_work(data, profile_path)
                        applications.verify_reviewed_cv(key, payload)
                        with closing(Store(Path(data)/'jobs.sqlite')) as store:
                            if store.get(key)['status'] not in {'ranked','materials_ready','needs_input','retryable'}:
                                raise NeedsInput('Record the existing handoff outcome before preparing again.')
                        assist_launcher(assist_command(data, profile_path, key, browser_channel, models['application']) +
                                        ['--reviewed-cv-sha256', payload['cv_sha256']])
                        return self.send_json({'message': 'Opening the reviewed application. Continue using this screen for answers and outcomes.'})
                    raise ValueError('Unknown application action')
                except (NeedsInput, LockBusy, ValueError, KeyError) as error:
                    return self.send_json({'error': str(error)}, 409)
                except OSError:
                    return self.send_json({'error': 'Application action could not start. Saved work is preserved.'}, 503)
            if self.path == '/api/profile':
                from .profile_edit import edit_profile, ProfileEditConflict
                from .locking import LockBusy
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 512 * 1024:
                        return self.send_json({'error': 'Profile update is empty or too large.'}, 413)
                    payload = json.loads(self.rfile.read(length))
                    return self.send_json(edit_profile(data, profile_path, payload))
                except ProfileEditConflict as error: return self.send_json({'error': str(error)}, 409)
                except LockBusy: return self.send_json({'error': 'Another profile edit is running. Wait for it to finish.'}, 409)
                except (NeedsInput, ValueError) as error: return self.send_json({'error': str(error)}, 400)
                except (OSError, KeyError): return self.send_json({'error': 'Profile changes could not be saved. Your existing profile is unchanged.'}, 500)
            if self.path.startswith('/api/search/'):
                from .locking import LockBusy
                from jsonschema import ValidationError
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 32768:
                        return self.send_json({'error': 'Search request is empty or too large.'}, 413)
                    payload = json.loads(self.rfile.read(length))
                    return self.send_json(search.start(self.path.removeprefix('/api/search/'), payload), 202)
                except LockBusy as error: return self.send_json({'error': str(error)}, 409)
                except ValidationError: return self.send_json({'error': 'Check search phrases, location and source selections.'}, 400)
                except (NeedsInput, ValueError) as error: return self.send_json({'error': str(error)}, 400)
            if self.path in ('/api/onboarding/draft', '/api/onboarding/confirm', '/api/onboarding/save'):
                from .onboarding import create_draft, confirm_draft, save_draft, DraftConflict
                from .locking import run_lock, LockBusy
                from .worker import utc_day
                from jsonschema import ValidationError
                try:
                    if Path(profile_path).exists():
                        return self.send_json({'error': 'A profile already exists; onboarding will not overwrite it.'}, 409)
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 58 * 1024 * 1024:
                        return self.send_json({'error': 'Upload request is empty or too large.'}, 413)
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):raise ValueError('Expected an intake form.')
                    with run_lock(Path(data) / 'onboarding.lock'):
                        if self.path.endswith('/confirm'):
                            result = confirm_draft(data, profile_path, payload)
                        elif self.path.endswith('/save'):
                            result = save_draft(data, payload)
                        else:
                            with closing(Store(Path(data) / 'jobs.sqlite')) as store:
                                model = CodexModel(Path(data) / 'model-cache', model=models['application'],
                                                   before_request=lambda: store.reserve_model_request(utc_day(), 50))
                                result = create_draft(data, payload.get('files'), model)
                    return self.send_json(result)
                except LockBusy:
                    return self.send_json({'error': 'Another intake operation is running. Wait for it to finish.'}, 409)
                except DraftConflict as error:
                    return self.send_json({'error': str(error)}, 409)
                except ValidationError:
                    return self.send_json({'error': 'The profile draft has an invalid structure; check the form and try again.'}, 400)
                except (ValueError, NeedsInput) as error:
                    return self.send_json({'error': str(error)}, 400)
                except Exception:
                    return self.send_json({'error': 'Document extraction or saving failed. No new profile was approved. Check the file format and Codex connection.'}, 500)
            if self.path == "/api/connect":
                command = codex_login_command(data)
                if not command:return self.send_json({"error": "Codex CLI was not found"}, 503)
                try:login_launcher(command)
                except OSError as error:return self.send_json({"error": str(error)}, 503)
                return self.send_json({"message": "Codex sign-in opened in a separate window. Finish there, then this page will refresh."})
            prefix = "/api/jobs/"
            suffix = "/prepare"
            if not (self.path.startswith(prefix) and self.path.endswith(suffix)):
                return self.send_json({"error": "Not found"}, 404)
            key = self.path[len(prefix):-len(suffix)]
            if model_preset_name == 'friend':
                return self.send_json({'error': 'Open the role application page and confirm the verified CV before preparation.'}, 409)
            if not key or "/" in key:
                return self.send_json({"error": "Invalid job"}, 400)
            try:
                require_application_work(data, profile_path)
                with closing(Store(Path(data) / "jobs.sqlite")) as store:
                    row = store.get(key)
                allowed = {"ranked", "materials_ready", "needs_input", "retryable"}
                if row["status"] not in allowed:
                    return self.send_json({"error": "This role needs review or reconciliation before preparation."}, 409)
                assist_launcher(assist_command(data, profile_path, key, browser_channel, models['application']))
            except NeedsInput as error:
                return self.send_json({"error": str(error)}, 409)
            except (KeyError, OSError) as error:
                return self.send_json({"error": str(error)}, 503)
            self.send_json({"message": "A visible JobLazy preparation window opened. Review it there; JobLazy will stop before Submit."})
    return Handler


def _launch_login(command):
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
    subprocess.Popen(command, creationflags=flags)


def serve(data, profile_path, host="127.0.0.1", port=8765, open_browser=True, browser_channel="chrome", model_preset_name="personal"):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Dashboard must bind to localhost only")
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((host, port), make_handler(data, profile_path, token, browser_channel=browser_channel,
                                                         model_preset_name=model_preset_name))
    url = f"http://{host}:{server.server_port}/"
    if open_browser:webbrowser.open(url)
    try:server.serve_forever()
    finally:server.server_close()
    return url
