#!/usr/bin/env python3
"""
admin_server.py — Local admin UI for managing agent social media data.

Usage:
    python3 admin_server.py
    Then open: http://localhost:8765/admin

Updates data/agents_data.json and rebuilds the MARKETS constant in
competitive-landscape.html on every save.
"""

import json
import re
import sys
from pathlib import Path

try:
    from flask import Flask, jsonify, request, abort
except ImportError:
    sys.exit("Flask not installed. Run: pip3 install flask")

BASE    = Path(__file__).parent
DATA    = BASE / "data" / "agents_data.json"
CL_HTML = BASE / "competitive-landscape.html"
PORT    = 8765

app = Flask(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_data():
    with open(DATA) as f:
        return json.load(f)


def save_data(data):
    with open(DATA, "w") as f:
        json.dump(data, f, indent=2)


def yt_verified_flag(agent):
    """Keep yt_verified false for known bad YT matches (>1M subs + unverified)."""
    return agent.get("yt_verified", True)


def rebuild_html(data):
    """Regenerate the MARKETS JS constant inside competitive-landscape.html."""
    lines = ["const MARKETS = {"]
    for market_key, market in data.items():
        lines.append(f'  {market_key}: {{')
        lines.append(f'    label: "{market["label"]}",')
        lines.append(f'    agents: [')
        for a in market["agents"]:
            yt_v = "true" if yt_verified_flag(a) else "false"
            lines.append(
                f'      {{ name:{json.dumps(a["name"])}, '
                f'fb:{a.get("facebook_followers",0)}, '
                f'tt:{a.get("tiktok_followers",0)}, '
                f'tt_videos:{a.get("tiktok_videos",0)}, '
                f'ig:{a.get("instagram_followers",0)}, '
                f'yt:{a.get("yt_subscribers",0)}, '
                f'yt_verified:{yt_v}, '
                f'ln:{a.get("line_oa_friends",0)}, '
                f'score:{a.get("presence_score",0)} }},'
            )
        lines.append(f'    ]')
        lines.append(f'  }}')
    lines.append("};")
    new_block = "\n".join(lines)

    html = CL_HTML.read_text()
    updated = re.sub(
        r"const MARKETS = \{.*?\};",
        new_block,
        html,
        flags=re.DOTALL,
    )
    if updated == html:
        return False, "Pattern not found in competitive-landscape.html"
    CL_HTML.write_text(updated)
    return True, "competitive-landscape.html rebuilt"


def recalc_score(a):
    """Simple presence score: sum of channels with any data, weighted."""
    score = 0.0
    if a.get("facebook_followers", 0) > 0:   score += 2.0
    if a.get("tiktok_followers", 0) > 0:      score += 2.5
    if a.get("instagram_followers", 0) > 0:   score += 2.0
    if a.get("yt_subscribers", 0) > 0:        score += 2.0
    if a.get("line_oa_friends", 0) > 0:       score += 2.5
    if a.get("tiktok_handle"):                 score += 0.5
    if a.get("instagram_handle"):              score += 0.5
    return min(round(score, 1), 10.0)


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/agents")
def api_agents():
    market = request.args.get("market", "thailand")
    data = load_data()
    if market not in data:
        abort(404)
    return jsonify(data[market]["agents"])


@app.route("/api/agents/<path:name>", methods=["PUT"])
def api_update_agent(name):
    market = request.args.get("market", "thailand")
    data   = load_data()
    agents = data[market]["agents"]
    payload = request.get_json(force=True)

    # coerce numeric fields
    for field in ("facebook_followers","tiktok_followers","tiktok_videos",
                  "instagram_followers","yt_subscribers","line_oa_friends"):
        if field in payload:
            try:
                payload[field] = int(str(payload[field]).replace(",",""))
            except ValueError:
                payload[field] = 0
    if "yt_verified" in payload:
        payload["yt_verified"] = bool(payload["yt_verified"])

    idx = next((i for i, a in enumerate(agents) if a["name"] == name), None)
    if idx is None:
        abort(404)
    agents[idx].update(payload)
    agents[idx]["presence_score"] = recalc_score(agents[idx])
    agents.sort(key=lambda x: x["name"])

    save_data(data)
    ok, msg = rebuild_html(data)
    return jsonify({"ok": ok, "msg": msg, "agent": agents[next(i for i,a in enumerate(agents) if a["name"]==name)]})


@app.route("/api/agents", methods=["POST"])
def api_add_agent():
    market  = request.args.get("market", "thailand")
    data    = load_data()
    agents  = data[market]["agents"]
    payload = request.get_json(force=True)

    name = payload.get("name","").strip()
    if not name:
        abort(400, "name required")
    if any(a["name"] == name for a in agents):
        abort(409, "agent already exists")

    new_agent = {
        "name":               name,
        "tiktok_handle":      payload.get("tiktok_handle",""),
        "tiktok_followers":   int(payload.get("tiktok_followers",0)),
        "tiktok_videos":      int(payload.get("tiktok_videos",0)),
        "instagram_handle":   payload.get("instagram_handle",""),
        "instagram_followers":int(payload.get("instagram_followers",0)),
        "facebook_followers": int(payload.get("facebook_followers",0)),
        "yt_channel":         payload.get("yt_channel",""),
        "yt_subscribers":     int(payload.get("yt_subscribers",0)),
        "yt_verified":        bool(payload.get("yt_verified",True)),
        "line_oa_handle":     payload.get("line_oa_handle",""),
        "line_oa_friends":    int(payload.get("line_oa_friends",0)),
        "presence_score":     0,
    }
    new_agent["presence_score"] = recalc_score(new_agent)

    agents.append(new_agent)
    agents.sort(key=lambda x: x["name"])
    save_data(data)
    ok, msg = rebuild_html(data)
    return jsonify({"ok": ok, "msg": msg, "agent": new_agent}), 201


@app.route("/api/agents/<path:name>", methods=["DELETE"])
def api_delete_agent(name):
    market = request.args.get("market", "thailand")
    data   = load_data()
    agents = data[market]["agents"]
    before = len(agents)
    data[market]["agents"] = [a for a in agents if a["name"] != name]
    if len(data[market]["agents"]) == before:
        abort(404)
    save_data(data)
    ok, msg = rebuild_html(data)
    return jsonify({"ok": ok, "msg": msg})


# ── Admin UI ──────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/admin")
def admin_ui():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Admin — Market Intelligence Hub</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&display=swap');

:root {
  --ink: #0f0f0f;
  --paper: #f7f4ee;
  --cream: #ede9e0;
  --rule: #d4cfc4;
  --accent: #c8392b;
  --accent2: #1a4a6b;
  --gold: #b8963e;
  --muted: #6b6560;
  --green: #2e7d32;
  --sidebar: 320px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'DM Sans',sans-serif; background:var(--paper); color:var(--ink); display:flex; height:100vh; overflow:hidden; }

/* ── Sidebar ── */
#sidebar {
  width: var(--sidebar);
  min-width: var(--sidebar);
  border-right: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  background: #fff;
}
#sidebar-header {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--rule);
}
#sidebar-header h1 { font-size:14px; font-weight:500; letter-spacing:1px; text-transform:uppercase; color:var(--ink); }
#sidebar-header p  { font-size:11px; color:var(--muted); margin-top:4px; }
#search-wrap { padding: 12px 16px; border-bottom:1px solid var(--rule); }
#search {
  width:100%; padding:8px 12px; border:1px solid var(--rule);
  border-radius:4px; font-size:13px; font-family:inherit;
  background:var(--paper);
}
#search:focus { outline:none; border-color:var(--accent2); }
#agent-list { overflow-y:auto; flex:1; }
.agent-item {
  padding: 11px 20px; cursor:pointer; border-bottom:1px solid var(--cream);
  font-size:13px; display:flex; align-items:center; justify-content:space-between;
  transition: background .1s;
}
.agent-item:hover  { background:var(--cream); }
.agent-item.active { background:var(--accent2); color:#fff; }
.agent-score {
  font-size:10px; font-weight:600; padding:2px 6px;
  border-radius:10px; background:var(--cream); color:var(--muted);
}
.agent-item.active .agent-score { background:rgba(255,255,255,0.2); color:#fff; }
#add-btn {
  margin:12px 16px; padding:9px 16px; background:var(--ink); color:#fff;
  border:none; border-radius:4px; font-size:12px; letter-spacing:1px;
  text-transform:uppercase; cursor:pointer; font-family:inherit;
}
#add-btn:hover { background:#333; }

/* ── Main panel ── */
#main { flex:1; overflow-y:auto; padding:40px 48px; }
#main h2 { font-size:22px; font-weight:500; margin-bottom:6px; }
#main .subhead { font-size:12px; color:var(--muted); margin-bottom:32px; letter-spacing:.5px; }

/* ── Form ── */
.form-section { margin-bottom:32px; }
.form-section-title {
  font-size:9px; letter-spacing:3px; text-transform:uppercase;
  color:var(--accent); margin-bottom:16px;
  padding-bottom:8px; border-bottom:1px solid var(--rule);
}
.field-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.field-grid.single { grid-template-columns:1fr; }
.field { display:flex; flex-direction:column; gap:5px; }
.field label { font-size:11px; letter-spacing:1px; text-transform:uppercase; color:var(--muted); font-weight:500; }
.field input, .field select {
  padding:9px 12px; border:1px solid var(--rule); border-radius:4px;
  font-size:14px; font-family:inherit; background:var(--paper);
  transition: border-color .15s;
}
.field input:focus, .field select:focus { outline:none; border-color:var(--accent2); }
.field .hint { font-size:11px; color:var(--muted); margin-top:2px; }

/* ── Actions ── */
.form-actions { display:flex; gap:12px; align-items:center; margin-top:8px; }
#save-btn {
  padding:10px 24px; background:var(--accent2); color:#fff;
  border:none; border-radius:4px; font-size:13px; font-weight:500;
  cursor:pointer; font-family:inherit;
}
#save-btn:hover { background:#15395a; }
#delete-btn {
  padding:10px 20px; background:none; color:var(--accent);
  border:1px solid var(--accent); border-radius:4px; font-size:13px;
  cursor:pointer; font-family:inherit;
}
#delete-btn:hover { background:#fdecea; }
#status { font-size:12px; color:var(--green); font-weight:500; }
#status.error { color:var(--accent); }

/* ── Empty state ── */
#empty { text-align:center; padding:80px 40px; color:var(--muted); }
#empty h3 { font-size:18px; font-weight:400; margin-bottom:8px; }
#empty p  { font-size:13px; }

/* ── Score badge ── */
.score-badge {
  display:inline-block; padding:3px 10px; border-radius:12px;
  font-size:11px; font-weight:600; margin-left:8px; vertical-align:middle;
}
.score-high   { background:#e8f5e9; color:#2e7d32; }
.score-mid    { background:#fff8e1; color:#e65100; }
.score-low    { background:#fdecea; color:#c62828; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <h1>Agent Admin</h1>
    <p id="agent-count">Loading…</p>
  </div>
  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search agents…" oninput="filterList()">
  </div>
  <div id="agent-list"></div>
  <button id="add-btn" onclick="showAddForm()">+ Add Agent</button>
</div>

<div id="main">
  <div id="empty">
    <h3>Select an agent</h3>
    <p>Choose from the list to edit their social media handles and follower counts.</p>
  </div>
  <div id="form-wrap" style="display:none">
    <h2 id="form-title">Agent Name</h2>
    <div class="subhead" id="form-subhead"></div>

    <div class="form-section">
      <div class="form-section-title">TikTok</div>
      <div class="field-grid">
        <div class="field">
          <label>Handle</label>
          <input type="text" id="f-tiktok_handle" placeholder="e.g. oneeducationthailand">
          <span class="hint">Without the @</span>
        </div>
        <div class="field">
          <label>Followers</label>
          <input type="number" id="f-tiktok_followers" min="0">
        </div>
        <div class="field">
          <label>Video Count</label>
          <input type="number" id="f-tiktok_videos" min="0">
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">Instagram</div>
      <div class="field-grid">
        <div class="field">
          <label>Handle</label>
          <input type="text" id="f-instagram_handle" placeholder="e.g. oneeducationthailand">
        </div>
        <div class="field">
          <label>Followers</label>
          <input type="number" id="f-instagram_followers" min="0">
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">Facebook</div>
      <div class="field-grid">
        <div class="field">
          <label>Page Followers</label>
          <input type="number" id="f-facebook_followers" min="0">
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">YouTube</div>
      <div class="field-grid">
        <div class="field">
          <label>Channel Name</label>
          <input type="text" id="f-yt_channel" placeholder="e.g. One Education Consulting">
        </div>
        <div class="field">
          <label>Subscribers</label>
          <input type="number" id="f-yt_subscribers" min="0">
        </div>
        <div class="field">
          <label>Channel Verified</label>
          <select id="f-yt_verified">
            <option value="true">Yes — confirmed their channel</option>
            <option value="false">No — may be wrong match</option>
          </select>
          <span class="hint">Unverified channels are excluded from YouTube rankings</span>
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">LINE Official Account</div>
      <div class="field-grid">
        <div class="field">
          <label>LINE OA Handle / ID</label>
          <input type="text" id="f-line_oa_handle" placeholder="e.g. @oneedu">
        </div>
        <div class="field">
          <label>Friends / Followers</label>
          <input type="number" id="f-line_oa_friends" min="0">
        </div>
      </div>
    </div>

    <div id="add-name-section" style="display:none" class="form-section">
      <div class="form-section-title">Agent Name</div>
      <div class="field-grid single">
        <div class="field">
          <label>Name</label>
          <input type="text" id="f-name" placeholder="Full agent name as registered">
        </div>
      </div>
    </div>

    <div class="form-actions">
      <button id="save-btn" onclick="save()">Save &amp; Rebuild</button>
      <button id="delete-btn" onclick="deleteAgent()" style="display:none">Delete Agent</button>
      <span id="status"></span>
    </div>
  </div>
</div>

<script>
let agents = [];
let currentName = null;
let isAdding = false;

async function loadAgents() {
  const res = await fetch('/api/agents');
  agents = await res.json();
  document.getElementById('agent-count').textContent = agents.length + ' agents · Thailand';
  renderList(agents);
}

function renderList(list) {
  const el = document.getElementById('agent-list');
  el.innerHTML = list.map(a => {
    const cls = a.name === currentName ? 'agent-item active' : 'agent-item';
    const sc = a.presence_score;
    const scCls = sc >= 7 ? 'score-high' : sc >= 4 ? 'score-mid' : 'score-low';
    return `<div class="${cls}" onclick="selectAgent(${JSON.stringify(a.name)})">
      <span>${a.name}</span>
      <span class="agent-score ${scCls}">${sc}</span>
    </div>`;
  }).join('');
}

function filterList() {
  const q = document.getElementById('search').value.toLowerCase();
  renderList(agents.filter(a => a.name.toLowerCase().includes(q)));
}

function selectAgent(name) {
  isAdding = false;
  currentName = name;
  const a = agents.find(x => x.name === name);
  if (!a) return;

  document.getElementById('empty').style.display = 'none';
  document.getElementById('form-wrap').style.display = 'block';
  document.getElementById('add-name-section').style.display = 'none';
  document.getElementById('delete-btn').style.display = '';
  document.getElementById('form-title').textContent = a.name;

  const sc = a.presence_score;
  const scCls = sc >= 7 ? 'score-high' : sc >= 4 ? 'score-mid' : 'score-low';
  document.getElementById('form-subhead').innerHTML =
    `Presence score: <span class="score-badge ${scCls}">${sc} / 10</span>`;

  document.getElementById('f-tiktok_handle').value    = a.tiktok_handle || '';
  document.getElementById('f-tiktok_followers').value  = a.tiktok_followers || 0;
  document.getElementById('f-tiktok_videos').value     = a.tiktok_videos || 0;
  document.getElementById('f-instagram_handle').value  = a.instagram_handle || '';
  document.getElementById('f-instagram_followers').value = a.instagram_followers || 0;
  document.getElementById('f-facebook_followers').value = a.facebook_followers || 0;
  document.getElementById('f-yt_channel').value        = a.yt_channel || '';
  document.getElementById('f-yt_subscribers').value    = a.yt_subscribers || 0;
  document.getElementById('f-yt_verified').value       = a.yt_verified ? 'true' : 'false';
  document.getElementById('f-line_oa_handle').value    = a.line_oa_handle || '';
  document.getElementById('f-line_oa_friends').value   = a.line_oa_friends || 0;

  document.getElementById('status').textContent = '';
  renderList(agents.filter(a => a.name.toLowerCase().includes(
    document.getElementById('search').value.toLowerCase()
  )));
}

function showAddForm() {
  isAdding = true;
  currentName = null;
  document.getElementById('empty').style.display = 'none';
  document.getElementById('form-wrap').style.display = 'block';
  document.getElementById('add-name-section').style.display = 'block';
  document.getElementById('delete-btn').style.display = 'none';
  document.getElementById('form-title').textContent = 'New Agent';
  document.getElementById('form-subhead').textContent = 'Fill in the details and click Save';
  ['tiktok_handle','tiktok_followers','tiktok_videos','instagram_handle',
   'instagram_followers','facebook_followers','yt_channel','yt_subscribers',
   'line_oa_handle','line_oa_friends','name'].forEach(f => {
    const el = document.getElementById('f-' + f);
    if (el) el.value = el.type === 'number' ? 0 : '';
  });
  document.getElementById('f-yt_verified').value = 'true';
  document.getElementById('status').textContent = '';
}

function payload() {
  return {
    tiktok_handle:      document.getElementById('f-tiktok_handle').value.trim().replace(/^@/,''),
    tiktok_followers:   parseInt(document.getElementById('f-tiktok_followers').value)||0,
    tiktok_videos:      parseInt(document.getElementById('f-tiktok_videos').value)||0,
    instagram_handle:   document.getElementById('f-instagram_handle').value.trim().replace(/^@/,''),
    instagram_followers:parseInt(document.getElementById('f-instagram_followers').value)||0,
    facebook_followers: parseInt(document.getElementById('f-facebook_followers').value)||0,
    yt_channel:         document.getElementById('f-yt_channel').value.trim(),
    yt_subscribers:     parseInt(document.getElementById('f-yt_subscribers').value)||0,
    yt_verified:        document.getElementById('f-yt_verified').value === 'true',
    line_oa_handle:     document.getElementById('f-line_oa_handle').value.trim(),
    line_oa_friends:    parseInt(document.getElementById('f-line_oa_friends').value)||0,
  };
}

async function save() {
  const btn = document.getElementById('save-btn');
  const status = document.getElementById('status');
  btn.textContent = 'Saving…';
  btn.disabled = true;
  status.className = '';
  status.textContent = '';

  try {
    let res;
    if (isAdding) {
      const name = document.getElementById('f-name').value.trim();
      if (!name) { status.className='error'; status.textContent='Name is required'; btn.textContent='Save & Rebuild'; btn.disabled=false; return; }
      res = await fetch('/api/agents?market=thailand', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ name, ...payload() })
      });
    } else {
      res = await fetch('/api/agents/' + encodeURIComponent(currentName) + '?market=thailand', {
        method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload())
      });
    }
    const data = await res.json();
    if (!res.ok) throw new Error(data.msg || res.statusText);

    status.textContent = '✓ Saved — competitive-landscape.html rebuilt';
    await loadAgents();
    if (isAdding) {
      currentName = data.agent.name;
      isAdding = false;
    }
    selectAgent(data.agent.name);
  } catch(e) {
    status.className = 'error';
    status.textContent = '✗ ' + e.message;
  }
  btn.textContent = 'Save & Rebuild';
  btn.disabled = false;
}

async function deleteAgent() {
  if (!currentName) return;
  if (!confirm('Delete "' + currentName + '"? This cannot be undone.')) return;
  const res = await fetch('/api/agents/' + encodeURIComponent(currentName) + '?market=thailand', { method:'DELETE' });
  const data = await res.json();
  if (res.ok) {
    currentName = null;
    document.getElementById('form-wrap').style.display = 'none';
    document.getElementById('empty').style.display = 'block';
    await loadAgents();
  }
}

loadAgents();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    if not DATA.exists():
        sys.exit(f"Data file not found: {DATA}")
    if not CL_HTML.exists():
        sys.exit(f"competitive-landscape.html not found: {CL_HTML}")
    print(f"\n  Agent Admin running at: http://localhost:{PORT}/admin\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
