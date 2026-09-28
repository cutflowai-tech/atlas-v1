"""Atlas CEO Dashboard and Editor Profile pages: static, self-contained HTML (presentation only).

Rendered from the dashboard document (``atlas_commander.dashboard``). The page formats values that
are already in that document: durations, percentages, dates, and marker positions on a timeline. It
computes no metric, comparison or conclusion. Management judgements with no approved rule
(``atlas_commander.management``) appear as calm empty states; their reasons are listed under
Data & System.

Presentation-only choices, documented so they are never mistaken for business rules:

- Editor card headline: the first comparable Video Type speed result (cohorts in the profile's order,
  largest Editor sample first); otherwise the deadline results, if any are classified; otherwise the
  completed-project count. This is a fixed display order, not a judgement of which metric matters most.
- Timelines place each completed project at its first Ready For Approval, and each Monday Performance
  Issues label at the time it was added. The profile does not date revision events, so revisions
  appear only as neutral context on their project.
- Month pills group those dated facts by their UTC calendar month.
"""

from __future__ import annotations

import calendar
import json
from collections import Counter
from datetime import datetime
from html import escape
from typing import Any

from atlas_commander.dashboard import month_name
from atlas_commander.management import PENDING_RULES
from atlas_commander.profile_html import STATUS_TEXT

NOT_EVALUATED = "Not evaluated yet"
NO_SIGNAL = "No supported signal yet"
RESULT_TEXT = {"early": "Early", "on_time": "On time", "late": "Late"}
ETA_ISSUE_TEXT = {"REQUESTED_ETA_DATE_ONLY": "Requested ETA has a date but no time", "MISSING_REQUESTED_ETA": "No Requested ETA",
                  "REQUESTED_ETA_INVALID": "Requested ETA could not be read"}
SPEED_WORD = {"faster_than_team_median": "faster", "slower_than_team_median": "slower", "equal_to_team_median": "level"}

# ---------------------------------------------------------------- design tokens and styles

CSS = """
:root{color-scheme:light;
--bg:#e9e6df;--shell:#f4f2ed;--surface:#fcfbf8;--surface-2:#efece5;--surface-3:#e4e0d7;
--ink:#1d1e18;--ink-2:#5b5a52;--ink-3:#8a887e;--line:#e0dcd2;--line-2:#d2cdc1;
--dark:#23241d;--dark-2:#30312a;--on-dark:#f4f2ea;--on-dark-2:#b3b1a5;--on-dark-3:#7f7e73;
--accent:#e2ff3d;--accent-ink:#1d1e18;--late:#a9563d;
--r-xl:36px;--r-lg:26px;--r-md:18px;--r-sm:12px;--r-pill:999px;
--s-1:4px;--s-2:8px;--s-3:12px;--s-4:16px;--s-5:24px;--s-6:32px;--s-7:48px;--s-8:64px;
--shadow-1:0 1px 2px rgba(29,30,24,.04),0 2px 8px rgba(29,30,24,.04);--shadow-2:0 2px 4px rgba(29,30,24,.05),0 12px 32px rgba(29,30,24,.08);
--t:200ms cubic-bezier(.2,.7,.2,1);
--font:"Inter","SF Pro Text","Segoe UI Variable","Segoe UI",system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--font);font-feature-settings:"tnum" 1,"cv11" 1;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit}a{color:inherit}
:focus-visible{outline:2px solid var(--ink);outline-offset:3px;border-radius:8px}
.shell{max-width:1320px;margin:var(--s-4) auto;background:var(--shell);border-radius:var(--r-xl);padding:var(--s-5) var(--s-7) var(--s-8);min-height:calc(100vh - 32px)}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:var(--s-4);margin-bottom:var(--s-7);flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-size:19px;letter-spacing:-.01em;font-weight:600;text-decoration:none}
.brand i{width:10px;height:10px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px var(--dark)}
.nav{display:flex;gap:6px;background:var(--surface-2);padding:5px;border-radius:var(--r-pill)}
.nav a{padding:8px 18px;border-radius:var(--r-pill);text-decoration:none;font-size:14px;color:var(--ink-2);transition:background var(--t),color var(--t)}
.nav a:hover{color:var(--ink)}.nav a[aria-current=page]{background:var(--dark);color:var(--on-dark)}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)}
.hello{display:flex;justify-content:space-between;align-items:flex-end;gap:var(--s-5);flex-wrap:wrap;margin-bottom:var(--s-6)}
.hello h1{font-size:clamp(34px,4.4vw,52px);font-weight:400;letter-spacing:-.03em;line-height:1.05;margin:6px 0 0}
.hello p{margin:10px 0 0;color:var(--ink-2);font-size:17px}
.meta{display:flex;gap:8px;flex-wrap:wrap}.meta span{padding:7px 14px;border-radius:var(--r-pill);background:var(--surface);border:1px solid var(--line);font-size:13px;color:var(--ink-2)}
.meta b{font-weight:500;color:var(--ink)}
section{margin-top:var(--s-7)}
.sh{display:flex;justify-content:space-between;align-items:flex-end;gap:var(--s-4);margin-bottom:var(--s-4);flex-wrap:wrap}
.sh h2{font-size:26px;font-weight:400;letter-spacing:-.02em;margin:0}.sh p{margin:4px 0 0;color:var(--ink-3);font-size:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);padding:var(--s-5)}
.quiet{color:var(--ink-3)}.soft{color:var(--ink-2)}.small{font-size:13px}.tiny{font-size:12px}
.focus{background:var(--dark);color:var(--on-dark);border-radius:var(--r-xl);padding:var(--s-6) var(--s-7);display:grid;grid-template-columns:1.3fr 1fr;gap:var(--s-6);position:relative;overflow:hidden}
.focus .eyebrow{color:var(--on-dark-2);display:flex;align-items:center;gap:8px}
.focus .eyebrow i{width:8px;height:8px;border-radius:50%;background:var(--accent)}
.focus h2{font-size:clamp(26px,3vw,36px);font-weight:400;letter-spacing:-.02em;line-height:1.15;margin:14px 0 12px}
.focus p{color:var(--on-dark-2);margin:0;max-width:52ch}
.focus .col h3{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--on-dark-3);font-weight:500;margin:0 0 10px}
.focus .col+.col{margin-top:var(--s-5)}.focus a{color:var(--on-dark);font-size:14px}
.fchip{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:var(--r-pill);font-size:13px;margin:0 6px 6px 0;background:var(--dark-2);color:var(--on-dark)}
.fchip.cal{background:transparent;border:1px dashed #56574d;color:var(--on-dark-2)}
.grid-ed{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:var(--s-4)}
.ed{position:relative;display:flex;flex-direction:column;gap:var(--s-4);transition:transform var(--t),box-shadow var(--t),border-color var(--t)}
.ed:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);border-color:var(--line-2)}
.ed .stretch::after{content:"";position:absolute;inset:0;border-radius:var(--r-lg)}
.ed .above{position:relative;z-index:1}
.who{display:flex;align-items:center;gap:var(--s-3)}.who h3{margin:0;font-size:20px;font-weight:500;letter-spacing:-.01em}
.avatar{flex:none;width:46px;height:46px;border-radius:50%;background:var(--surface-3);color:var(--ink);display:grid;place-items:center;font-size:15px;letter-spacing:.02em;font-weight:500}
.avatar.xl{width:84px;height:84px;font-size:28px}
.overall{margin-left:auto;text-align:right}.overall b{display:block;font-size:22px;font-weight:300;line-height:1}.overall span{font-size:11.5px;color:var(--ink-3)}
.hero{background:var(--surface-2);border-radius:var(--r-md);padding:var(--s-4) var(--s-5);display:flex;flex-direction:column;gap:6px}
.hero .big{font-size:44px;font-weight:300;letter-spacing:-.03em;line-height:1}.hero .big small{font-size:15px;letter-spacing:.06em;text-transform:uppercase;margin-left:6px;font-weight:500}
.hero .pair{display:flex;gap:var(--s-5);margin-top:4px}.hero .pair div b{display:block;font-size:17px;font-weight:500}.hero .pair div span{font-size:12px;color:var(--ink-3)}
.line{display:grid;grid-template-columns:108px 1fr;gap:var(--s-3);align-items:start;font-size:14px}
.line>.k{color:var(--ink-3);font-size:12.5px;padding-top:2px;display:flex;align-items:center;gap:6px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:var(--r-pill);background:var(--surface-2);font-size:12.5px;color:var(--ink-2)}
.chip{white-space:nowrap}.chip b{font-weight:500;color:var(--ink)}.chip.context{background:transparent;border:1px dashed var(--line-2)}
.strip{display:flex;gap:3px;height:8px;border-radius:var(--r-pill);overflow:hidden;background:var(--surface-3);margin:4px 0 6px}
.strip.lg{height:14px}.strip i{display:block;height:100%}.strip .e{background:var(--ink)}.strip .o{background:var(--ink-3)}.strip .l{background:var(--late)}
.key{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px;vertical-align:-1px}.key.e{background:var(--ink)}.key.o{background:var(--ink-3)}.key.l{background:var(--late)}
.cta{display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border-radius:var(--r-pill);background:var(--dark);color:var(--on-dark);text-decoration:none;font-size:14px;transition:background var(--t)}
.cta:hover{background:#000}.ed .cta{align-self:flex-start;margin-top:auto}
.info{display:inline-flex;align-items:center;gap:5px;border:0;background:none;padding:0;cursor:pointer;color:var(--ink-3);font-size:12.5px;text-decoration:underline dotted;text-underline-offset:3px}
.info:hover{color:var(--ink)}.info svg{flex:none}
.ghost{border:1px solid var(--line-2);background:var(--surface);border-radius:var(--r-pill);padding:7px 14px;font-size:13px;cursor:pointer;transition:background var(--t)}
.ghost:hover{background:var(--surface-2)}
.empty{color:var(--ink-3)}.empty b{display:block;color:var(--ink-2);font-weight:500;font-size:15px}
.pills{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;padding:2px}.pills::-webkit-scrollbar{display:none}
.pill{flex:none;border:1px solid var(--line);background:var(--surface);border-radius:var(--r-pill);padding:6px 14px;font-size:13.5px;cursor:pointer;color:var(--ink-2);transition:background var(--t),color var(--t),border-color var(--t)}
.pill:hover{border-color:var(--line-2);color:var(--ink)}.pill[aria-selected=true]{background:var(--dark);border-color:var(--dark);color:var(--on-dark)}
.pill:disabled{opacity:.45;cursor:default}
.pulse{padding:var(--s-5) var(--s-5) var(--s-4)}
.tl{overflow-x:auto}.tl-inner{min-width:680px}
.axis{position:relative;height:26px;margin-left:150px;border-bottom:1px solid var(--line)}
.axis span{position:absolute;bottom:6px;transform:translateX(-50%);font-size:12px;color:var(--ink-3);white-space:nowrap}
.axis .today{color:var(--ink);font-weight:500}
.lane{display:flex;align-items:stretch;border-bottom:1px solid var(--line)}.lane:last-child{border-bottom:0}
.lane .ln{width:150px;flex:none;display:flex;align-items:center;gap:8px;font-size:13.5px;padding:8px 8px 8px 0}
.lane .ln .avatar{width:26px;height:26px;font-size:10.5px}
.track{position:relative;flex:1;min-height:40px;background:linear-gradient(var(--line),var(--line)) center/100% 1px no-repeat}
.track .now{position:absolute;top:0;bottom:0;width:0;border-left:1px dashed var(--ink-3)}
.mk{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border:0;padding:0;background:none;cursor:pointer;display:grid;place-items:center;border-radius:50%;transition:transform var(--t)}
.mk:hover{transform:scale(1.25)}.mk i{display:block;width:10px;height:10px;border-radius:50%}
.mk.early i{background:var(--ink)}.mk.on_time i{background:var(--surface);box-shadow:inset 0 0 0 2px var(--ink)}
.mk.late i{background:var(--late);border-radius:2px;transform:rotate(45deg);width:9px;height:9px}
.mk.unclassified i{width:7px;height:7px;background:var(--surface);box-shadow:inset 0 0 0 1.5px var(--ink-3)}
.mk.issue i{border-radius:3px;width:10px;height:10px;background:var(--surface);box-shadow:inset 0 0 0 2px var(--ink);position:relative}
.mk.issue i::after{content:"";position:absolute;left:4px;top:2px;width:2px;height:4px;background:var(--ink)}
.mk.is-selected{box-shadow:0 0 0 3px var(--accent),0 0 0 4px var(--ink)}
.legend{display:flex;flex-wrap:wrap;gap:var(--s-4);margin-top:var(--s-4);font-size:12.5px;color:var(--ink-3);align-items:center}
.legend .mk{position:static;margin:0;display:inline-grid;cursor:default;vertical-align:middle}.legend .mk:hover{transform:none}
.ctx{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--s-4)}
.ctx .card h3{margin:0;font-size:17px;font-weight:500;display:flex;align-items:center;gap:8px}
.ctx .card .sub{font-size:13px;color:var(--ink-3);margin:2px 0 var(--s-4)}
.rowlist{display:flex;flex-direction:column;gap:var(--s-3)}.rowlist>div{display:flex;justify-content:space-between;gap:var(--s-3);align-items:flex-start;font-size:14px}.rowlist .chips{justify-content:flex-end}
.hist .row{display:grid;grid-template-columns:200px 1fr 1.2fr;gap:var(--s-5);padding:var(--s-4) 0;border-bottom:1px solid var(--line);align-items:start;font-size:14px}
.hist .row:last-child{border-bottom:0}
.back{display:inline-flex;gap:6px;align-items:center;font-size:14px;color:var(--ink-2);text-decoration:none;margin-bottom:var(--s-5)}.back:hover{color:var(--ink)}
.phead{display:grid;grid-template-columns:auto 1fr auto;gap:var(--s-5);align-items:center}
.phead h1{font-size:clamp(34px,4vw,48px);font-weight:400;letter-spacing:-.03em;margin:0;line-height:1.05}
.phead .facts{display:flex;gap:var(--s-6);flex-wrap:wrap}.phead .facts div span{display:block;font-size:12px;color:var(--ink-3)}.phead .facts div b{font-weight:400;font-size:17px}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--s-4);margin-top:var(--s-6)}
.metric{text-align:left;cursor:pointer;display:flex;flex-direction:column;gap:6px;transition:box-shadow var(--t),border-color var(--t)}
.metric:hover{box-shadow:var(--shadow-1);border-color:var(--line-2)}
.metric .v{font-size:40px;font-weight:300;letter-spacing:-.03em;line-height:1.05}.metric .v small{font-size:14px;letter-spacing:.04em;text-transform:uppercase;margin-left:4px}
.tabs{position:sticky;top:0;z-index:5;background:var(--shell);padding:var(--s-3) 0;margin-top:var(--s-6)}
.panel{margin-top:var(--s-4)}.two{display:grid;grid-template-columns:1.4fr 1fr;gap:var(--s-4)}
.qa{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:var(--s-4)}
.qa h3{font-size:14px;font-weight:500;margin:0 0 4px}.qa .j{font-size:12.5px;color:var(--ink-3);margin-bottom:8px}.qa ul{margin:0;padding-left:18px;font-size:14px;color:var(--ink-2)}
.cohorts{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:var(--s-3)}
.cohort{text-align:left;cursor:pointer;display:flex;flex-direction:column;gap:8px;border-radius:var(--r-md);padding:var(--s-4) var(--s-5)}
.cohort .nums{display:flex;gap:var(--s-5)}.cohort .nums b{display:block;font-size:20px;font-weight:400}.cohort .nums span{font-size:12px;color:var(--ink-3)}
.cohort.cmp{border-color:var(--ink)}
.list{display:flex;flex-direction:column}.list button{all:unset;cursor:pointer;display:grid;grid-template-columns:130px 1fr 110px 1fr 90px;gap:var(--s-3);padding:12px 6px;border-bottom:1px solid var(--line);font-size:13.5px;align-items:center}
.list button:hover{background:var(--surface-2)}.list button:focus-visible{outline:2px solid var(--ink)}
.res-early{color:var(--ink)}.res-late{color:var(--late)}.res-on_time{color:var(--ink)}
.sys table{width:100%;border-collapse:collapse;font-size:13.5px}.sys th,.sys td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.sys th{font-weight:500;color:var(--ink-3);font-size:12.5px}.sys .card{margin-top:var(--s-4)}.sys h3{margin:0 0 var(--s-3);font-size:17px;font-weight:500}
.sys code,.drawer code{font-size:12px;background:var(--surface-2);padding:1px 6px;border-radius:6px;word-break:break-all}
.scrim{position:fixed;inset:0;background:rgba(29,30,24,.28);opacity:0;pointer-events:none;transition:opacity var(--t);z-index:20}
.drawer{position:fixed;top:12px;right:12px;bottom:12px;width:min(520px,calc(100vw - 24px));background:var(--surface);border-radius:var(--r-lg);box-shadow:var(--shadow-2);
transform:translateX(calc(100% + 24px));transition:transform var(--t);z-index:21;display:flex;flex-direction:column}
body.drawer-open .scrim{opacity:1;pointer-events:auto}body.drawer-open .drawer{transform:none}
.drawer header{display:flex;justify-content:space-between;align-items:center;padding:var(--s-5) var(--s-5) var(--s-3)}
.drawer header h2{margin:0;font-size:20px;font-weight:500}.drawer .body{overflow:auto;padding:0 var(--s-5) var(--s-5)}
.drawer .x{border:0;background:var(--surface-2);width:36px;height:36px;border-radius:50%;cursor:pointer;display:grid;place-items:center}
.drawer dl,.sys dl{display:grid;grid-template-columns:170px 1fr;gap:8px 12px;margin:0;font-size:13.5px}.drawer dt,.sys dt{color:var(--ink-3)}.drawer dd,.sys dd{margin:0}
.drawer h4{margin:var(--s-5) 0 var(--s-2);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:500}
.drawer iframe{width:100%;height:70vh;border:1px solid var(--line);border-radius:var(--r-md)}
.drawer p{font-size:14px;color:var(--ink-2)}.drawer ul{padding-left:18px;font-size:14px}
[hidden]{display:none!important}
@media (max-width:1080px){.ctx{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}}
@media (max-width:760px){.shell{margin:0;border-radius:0;padding:var(--s-4) var(--s-4) var(--s-7)}.focus{grid-template-columns:1fr;padding:var(--s-5)}
.grid-ed{grid-template-columns:1fr}.ctx{grid-template-columns:1fr}.hist .row{grid-template-columns:1fr;gap:var(--s-2)}.phead{grid-template-columns:auto 1fr}
.phead .overall{grid-column:1/-1;text-align:left;margin:0}.metrics{grid-template-columns:1fr 1fr}.line{grid-template-columns:96px 1fr}
.list button{grid-template-columns:1fr 1fr;row-gap:2px}.metric .v{font-size:32px}.topbar{margin-bottom:var(--s-5)}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

SCRIPT = """
(function(){
  var reports = JSON.parse(document.getElementById('atlas-reports').textContent);
  var views = document.querySelectorAll('[data-view]');
  function route(){
    var h = location.hash || '#/', name = 'team', m;
    if (h === '#/system') name = 'system';
    else if ((m = h.match(/^#\\/editor\\/(.+)$/))) name = 'editor:' + decodeURIComponent(m[1]);
    var found = false;
    views.forEach(function(v){ var on = v.getAttribute('data-view') === name; v.hidden = !on; found = found || on; });
    if (!found) document.querySelector('[data-view="team"]').hidden = false;
    document.querySelectorAll('.nav a').forEach(function(a){
      var on = a.getAttribute('data-nav') === (name === 'system' ? 'system' : 'team');
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    closeDrawer(); window.scrollTo(0, 0);
  }
  document.addEventListener('click', function(e){
    var pill = e.target.closest('[data-pill]');
    if (pill) {
      var group = pill.closest('[data-pills]');
      group.querySelectorAll('[data-pill]').forEach(function(p){
        var on = p === pill; p.setAttribute('aria-selected', on ? 'true' : 'false');
        var panel = document.getElementById(p.getAttribute('data-pill')); if (panel) panel.hidden = !on;
      });
      return;
    }
    var opener = e.target.closest('[data-drawer]');
    if (opener) { e.preventDefault(); openDrawer(opener.getAttribute('data-drawer'), opener); }
  });
  var drawer = document.getElementById('drawer'), body = drawer.querySelector('.body'), title = drawer.querySelector('h2'), last = null;
  function openDrawer(id, trigger){
    var tpl = document.getElementById(id); if (!tpl) return;
    document.querySelectorAll('.mk.is-selected').forEach(function(m){ m.classList.remove('is-selected'); });
    if (trigger.classList.contains('mk')) trigger.classList.add('is-selected');
    title.textContent = tpl.getAttribute('data-title') || '';
    body.innerHTML = ''; body.appendChild(tpl.content.cloneNode(true));
    body.querySelectorAll('iframe[data-report]').forEach(function(f){ f.srcdoc = reports[f.getAttribute('data-report')] || ''; });
    last = trigger; document.body.classList.add('drawer-open'); drawer.setAttribute('aria-hidden', 'false'); drawer.querySelector('.x').focus();
  }
  function closeDrawer(){
    if (!document.body.classList.contains('drawer-open')) return;
    document.body.classList.remove('drawer-open'); drawer.setAttribute('aria-hidden', 'true');
    document.querySelectorAll('.mk.is-selected').forEach(function(m){ m.classList.remove('is-selected'); });
    if (last) last.focus();
  }
  drawer.querySelector('.x').addEventListener('click', closeDrawer);
  document.querySelector('.scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeDrawer(); });
  var hello = document.getElementById('greeting');
  if (hello) { var hr = new Date().getHours(); hello.textContent = hr < 12 ? 'Good morning.' : hr < 18 ? 'Good afternoon.' : 'Good evening.'; }
  window.addEventListener('hashchange', route); route();
})();
"""

ICONS = {
    "speed": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5M12 16.2v.1"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "stack": '<rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/>',
    "doc": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    "rotate": '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    "activity": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.1"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "back": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
}


def icon(name: str, size: int = 16) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


# ---------------------------------------------------------------- formatting (presentation only)

def _h(seconds: Any) -> str:
    return "—" if seconds is None else f"{seconds / 3600:.1f}h"


def _signed_h(seconds: Any) -> str:
    return "—" if seconds is None else f"{seconds / 3600:+.1f}h"


def _pct(rate: Any) -> str:
    return "—" if rate is None else f"{rate * 100:.1f}%"


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _date(value: Any, with_time: bool = True) -> str:
    moment = _dt(value)
    if moment is None:
        return "—"
    return moment.strftime("%d %b %Y, %H:%M UTC") if with_time else moment.strftime("%d %b %Y")


def _initials(name: str) -> str:
    words = [w for w in name.replace("(", " ").replace(")", " ").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def _labels(labels: list[str], fallback: str = "—") -> str:
    return " + ".join(labels) or fallback


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _item(item_id: str, url: str | None) -> str:
    text = escape(str(item_id))
    return f'<a href="{escape(url.format(item_id=item_id))}" target="_blank" rel="noopener">{text}</a>' if url else text


# ---------------------------------------------------------------- primitives

def avatar(name: str, size: str = "") -> str:
    return f'<span class="avatar {size}" aria-hidden="true">{escape(_initials(name))}</span>'


def empty_state(title: str, detail: str = "") -> str:
    return f'<div class="empty"><b>{escape(title)}</b>{escape(detail)}</div>'


def info_button(text: str, drawer_id: str) -> str:
    return f'<button type="button" class="info above" data-drawer="{escape(drawer_id)}">{icon("info", 14)}{escape(text)}</button>'


def overall_placeholder() -> str:
    return f'<div class="overall" title="{NOT_EVALUATED}"><span>Overall</span><b aria-label="Overall: {NOT_EVALUATED}">—</b><span>{NOT_EVALUATED}</span></div>'


def deadline_strip(d: dict[str, Any], large: bool = False) -> str:
    total = (d.get("early") or 0) + (d.get("on_time") or 0) + (d.get("late") or 0)
    if not total:
        return ""
    label = f"{d['early']} early, {d['on_time']} on time, {d['late']} late of {total} classified"
    parts = "".join(f'<i class="{cls}" style="flex:{n}"></i>' for cls, n in (("e", d["early"]), ("o", d["on_time"]), ("l", d["late"])) if n)
    return f'<div class="strip{" lg" if large else ""}" role="img" aria-label="{label}" title="{label}">{parts}</div>'


def deadline_counts(d: dict[str, Any]) -> str:
    return (f'<span><b>{d["early"]}</b> early · <b>{d["on_time"]}</b> on time · <b>{d["late"]}</b> late</span>')


def template(tid: str, title: str, content: str) -> str:
    return f'<template id="{escape(tid)}" data-title="{escape(title)}">{content}</template>'


def _dl(rows: list[tuple[str, str]]) -> str:
    return "<dl>" + "".join(f"<dt>{escape(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


# ---------------------------------------------------------------- evidence drawer contents

def _project_tid(editor_id: str, item_id: str) -> str:
    return f"p-{editor_id}-{item_id}"


def project_evidence(editor_name: str, row: dict[str, Any], url: str | None) -> str:
    result = row["deadline_result"]
    if result:
        deadline = f'{escape(RESULT_TEXT[result])} · {_signed_h(row["deadline_delta_seconds"])} against the Requested ETA'
    else:
        deadline = escape(ETA_ISSUE_TEXT.get(row["requested_eta_issue"] or "", "Not classified") + " — not classified")
    ids = row["evidence_event_ids"] or {}
    content = _dl([
        ("Editor", escape(editor_name)),
        ("Monday item", _item(row["monday_item_id"], url)),
        ("Video Type", escape(_labels(row["cohort_labels"]))),
        ("Work started", escape(_date(row["in_progress_at"]))),
        ("Ready For Approval", escape(_date(row["ready_for_approval_at"]))),
        ("Work duration", f'{_h(row["duration_seconds"])}{"" if row["speed_eligible"] else " · not used for speed"}'),
        ("Requested ETA", escape(_date(row["requested_eta"])) + (f' <span class="quiet">(set {escape(_date(row["requested_eta_observed_at"]))})</span>'
                                                                  if row.get("requested_eta_observed_at") else "")),
        ("Deadline", deadline),
    ])
    ignored = row.get("requested_eta_changes_ignored_after_ready_for_approval") or 0
    notes = []
    if ignored:
        notes.append(f"{_plural(ignored, 'later Requested ETA change')} after Ready For Approval, ignored by the deadline rule.")
    labels = "".join(f'<span class="chip">{escape(label)}</span>' for label in row["quality_labels"]) or '<span class="quiet">None recorded</span>'
    revisions = row["client_revision_events"]
    evidence = "".join(f"<dt>{escape(k.replace('_', ' ').capitalize())}</dt><dd><code>{escape(str(v))}</code></dd>" for k, v in ids.items() if v)
    status = ", ".join(row["exclusions"]) or "Included in metrics"
    return (content + (f'<p>{escape(" ".join(notes))}</p>' if notes else "")
            + f'<h4>Monday Performance Issues</h4><div class="chips">{labels}</div>'
            + f'<h4>Client revision context</h4><p>{_plural(revisions, "client revision event")} on this project. Context only — not a performance signal.</p>'
            + f'<h4>Metric status</h4><p>{escape(status)}</p>'
            + (f'<p class="tiny quiet">Flags: {escape(", ".join(row["flags"]))}</p>' if row["flags"] else "")
            + f"<h4>Monday events</h4><dl>{evidence}</dl>")


def _project_templates(s: dict[str, Any], url: str | None) -> str:
    return "".join(template(_project_tid(s["editor_id"], row["monday_item_id"]), f"Project {row['monday_item_id']}",
                            project_evidence(s["display_name"], row, url)) for row in s["projects"])


def _project_list(s: dict[str, Any], item_ids: list[str] | None = None) -> str:
    rows = [row for row in s["projects"] if item_ids is None or row["monday_item_id"] in set(item_ids)]
    if not rows:
        return '<p class="quiet">No projects.</p>'
    out = []
    for row in rows:
        result = row["deadline_result"]
        deadline = (f'<span class="res-{result}">{RESULT_TEXT[result]} {_signed_h(row["deadline_delta_seconds"])}</span>' if result
                    else '<span class="quiet">not classified</span>')
        out.append(f'<button type="button" data-drawer="{escape(_project_tid(s["editor_id"], row["monday_item_id"]))}">'
                   f'<span>{escape(_date(row["ready_for_approval_at"], False))}</span><span>{escape(_labels(row["cohort_labels"]))}</span>'
                   f'<span>{deadline}</span><span class="soft">{escape(", ".join(row["quality_labels"]) or "")}</span>'
                   f'<span class="quiet">{_h(row["duration_seconds"])}</span></button>')
    return f'<div class="list">{"".join(out)}</div>'


# ---------------------------------------------------------------- Editor card (CEO home)

def _hero(s: dict[str, Any]) -> tuple[str, str]:
    """Headline block for the card and which section it shows (fixed display order, see module docstring)."""
    speed, deadline = s["speed"], s["deadline"]
    if speed["compared_cohorts"]:
        c = speed["compared_cohorts"][0]
        pct = abs(c["editor_vs_team_median_pct"] or 0)
        word = SPEED_WORD[c["conclusion"]]
        big = f'{pct:.1f}%<small>{word}</small>' if c["conclusion"] != "equal_to_team_median" else 'Level<small>with team</small>'
        return ("speed", (f'<div class="hero"><span class="eyebrow">{icon("speed", 13)} Speed · {escape(_labels(c["labels"]))} vs team median</span>'
                f'<div class="big">{big}</div>'
                f'<div class="pair"><div><b>{_h(c["editor_median_seconds"])}</b><span>Editor median</span></div>'
                f'<div><b>{_h(c["team_median_seconds"])}</b><span>Team median</span></div></div>'
                f'<span class="tiny quiet">n = {c["editor_sample_size"]} Editor projects · {c["team_sample_size"]} team projects · {c["team_editor_count"]} Editors · '
                f'{escape(_labels(c["labels"]))} only</span></div>'))
    if deadline["evaluated"]:
        return ("deadline", (f'<div class="hero"><span class="eyebrow">{icon("clock", 13)} Deadlines</span>{deadline_strip(deadline, True)}'
                f'<div style="font-size:17px">{deadline_counts(deadline)}</div><span class="tiny quiet">{deadline["evaluated"]} classified deliveries</span></div>'))
    return ("projects", (f'<div class="hero"><span class="eyebrow">{icon("layers", 13)} Projects</span><div class="big">{s["sample"]["completed_projects"]}'
            f'<small>completed</small></div></div>'))


def _speed_line(s: dict[str, Any]) -> str:
    speed = s["speed"]
    compared = speed["compared_cohorts"]
    others = len(speed["cohorts"]) - len(compared)
    head = ""
    if compared:
        c = compared[0]
        head = f'{escape(_labels(c["labels"]))}: {_h(c["editor_median_seconds"])} vs {_h(c["team_median_seconds"])}'
    more = []
    if len(compared) > 1:
        more.append(f"+{len(compared) - 1} comparable")
    if others:
        more.append(f"+{others} not comparable")
    link = info_button(" · ".join(more), f"speed-{s['editor_id']}") if more else ""
    if not compared:
        return '<span class="soft">No comparable Video Type yet</span> ' + info_button("Why", f"speed-{s['editor_id']}")
    return f"{head} {link}"


def _deadline_line(s: dict[str, Any]) -> str:
    d = s["deadline"]
    unclassified = (d.get("not_classifiable_insufficient_eta_precision") or 0) + (d.get("not_classifiable_missing_eta") or 0)
    note = info_button(f"{unclassified} unclassified", f"dq-{s['editor_id']}") if unclassified else ""
    if not d["evaluated"]:
        return '<span class="soft">Deadline data unavailable</span> ' + info_button("Why", f"dq-{s['editor_id']}")
    return f'{deadline_strip(d)}<div class="small">{deadline_counts(d)} <span class="quiet">of {d["evaluated"]}</span> {note}</div>'


def _issue_line(s: dict[str, Any]) -> str:
    q = s["quality"]
    if not q["total_occurrences"]:
        return '<span class="soft">No issue labels recorded</span>'
    chips = "".join(f'<span class="chip">{escape(row["label"])} <b>×{row["occurrences"]}</b></span>' for row in q["by_label"][:3])
    extra = f'<span class="chip">+{len(q["by_label"]) - 3}</span>' if len(q["by_label"]) > 3 else ""
    return (f'<div class="small"><b>{_plural(q["total_occurrences"], "issue signal")}</b> <span class="quiet">on '
            f'{_plural(q["projects_with_issues"], "project")}</span></div><div class="chips" style="margin-top:6px">{chips}{extra}</div>')


def workload_chips(w: dict[str, Any], limit: int | None = None) -> str:
    items = list(w["by_current_status"].items())
    if not items:
        return '<span class="soft">No current items</span>'
    shown = items[:limit] if limit else items
    chips = "".join(f'<span class="chip{" context" if "revision" in status.lower() else ""}"><b>{n}</b> {escape(status)}</span>' for status, n in shown)
    rest = len(items) - len(shown)
    return f'<div class="chips">{chips}{f"<span class=chip>+{rest}</span>" if rest > 0 else ""}</div>'


def editor_card(s: dict[str, Any]) -> str:
    kind, hero = _hero(s)
    lines = []
    if kind != "speed":
        lines.append(("speed", "Speed", _speed_line(s)))
    else:
        more = _speed_line(s)
        if "info" in more:
            lines.append(("speed", "Speed", more))
    if kind != "deadline":
        lines.append(("clock", "Deadlines", _deadline_line(s)))
    lines.append(("alert", "Issue signals", _issue_line(s)))
    lines.append(("spark", "Positive", f'<span class="quiet">— {NO_SIGNAL}</span>'))
    lines.append(("stack", "Current work", workload_chips(s["current_workload"], 3)))
    body = "".join(f'<div class="line"><span class="k">{icon(ic, 13)}{escape(k)}</span><div>{v}</div></div>' for ic, k, v in lines)
    return (f'<article class="card ed" aria-label="{escape(s["display_name"])}">'
            f'<div class="who">{avatar(s["display_name"])}<div><h3>{escape(s["display_name"])}</h3>'
            f'<span class="small quiet">{_plural(s["sample"]["completed_projects"], "completed project")}</span></div>{overall_placeholder()}</div>'
            f'{hero}{body}'
            f'<a class="cta stretch" href="#/editor/{escape(s["editor_id"])}">View profile {icon("arrow", 15)}</a></article>')


# ---------------------------------------------------------------- timelines (Team Pulse and Editor Performance Timeline)

def _event_month(event: dict[str, Any]) -> str:
    return str(event["at"])[:7]


def _position(at: str, month: str) -> float:
    moment = _dt(at)
    assert moment is not None
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    return ((moment.day - 1) + (moment.hour * 3600 + moment.minute * 60 + moment.second) / 86400) / days * 100


def _marker_class(event: dict[str, Any]) -> tuple[str, str]:
    if event["kind"] == "issue_label":
        return "issue", f'Issue label: {event["label"]}'
    result = event["deadline_result"]
    if result:
        return result, f"{RESULT_TEXT[result]} delivery"
    return "unclassified", "Delivery, deadline not classified"


def _event_tid(editor_id: str, index: int) -> str:
    return f"e-{editor_id}-{index}"


def _event_templates(s: dict[str, Any]) -> str:
    """Drawer content for issue-label events (deliveries open their project's evidence)."""
    out = []
    for index, event in enumerate(s["events"]):
        if event["kind"] != "issue_label":
            continue
        ids = "".join(f"<dd><code>{escape(str(v))}</code></dd>" for v in event["event_ids"])
        out.append(template(_event_tid(s["editor_id"], index), event["label"], _dl([
            ("Editor", escape(s["display_name"])), ("Label added", escape(_date(event["at"]))), ("Monday item", escape(event["monday_item_id"])),
            ("Source", "Monday Performance Issues column")]) + f"<h4>Monday events</h4><dl><dt>Evidence</dt>{ids}</dl>"
            + f'<p><button type="button" class="ghost" data-drawer="{escape(_project_tid(s["editor_id"], event["monday_item_id"]))}">Open project evidence</button></p>'))
    return "".join(out)


def _lane(s: dict[str, Any], month: str, retrieved: str | None, show_name: bool) -> str:
    markers: list[str] = []
    rows_last: dict[int, float] = {}
    events = [(i, e) for i, e in enumerate(s["events"]) if _event_month(e) == month]
    for index, event in events:
        pos = _position(event["at"], month)
        row = 0
        while row in rows_last and pos - rows_last[row] < 1.3:
            row += 1
        rows_last[row] = pos
        cls, label = _marker_class(event)
        tid = _project_tid(s["editor_id"], event["monday_item_id"]) if event["kind"] == "delivery" else _event_tid(s["editor_id"], index)
        aria = f'{s["display_name"]}: {label}, {_date(event["at"])}, project {event["monday_item_id"]}'
        markers.append(f'<button type="button" class="mk {cls}" style="left:{pos:.2f}%;top:{14 + row * 16}px" data-drawer="{escape(tid)}" '
                       f'aria-label="{escape(aria)}" title="{escape(aria)}"><i></i></button>')
    height = 28 + (max(rows_last) + 1 if rows_last else 1) * 16
    now = f'<span class="now" style="left:{_position(retrieved, month):.2f}%"></span>' if retrieved and retrieved[:7] == month else ""
    name = (f'<div class="ln">{avatar(s["display_name"])}<span>{escape(s["display_name"])}</span></div>' if show_name
            else '<div class="ln"><span class="quiet small">Events</span></div>')
    empty = '' if markers else '<span class="tiny quiet" style="position:absolute;left:8px;top:10px">No dated events this month</span>'
    return f'<div class="lane">{name}<div class="track" style="height:{height}px">{now}{empty}{"".join(markers)}</div></div>'


def _axis(month: str, retrieved: str | None) -> str:
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    label = calendar.month_abbr[int(month[5:])]
    ticks = "".join(f'<span style="left:{(day - 1) / days * 100:.2f}%">{label} {day:02d}</span>' for day in (1, 8, 15, 22) if day <= days)
    if retrieved and retrieved[:7] == month:
        ticks += f'<span class="today" style="left:{_position(retrieved, month):.2f}%">Updated</span>'
    return f'<div class="axis">{ticks}</div>'


LEGEND = ('<div class="legend"><span><span class="mk early"><i></i></span> Early</span><span><span class="mk on_time"><i></i></span> On time</span>'
          '<span><span class="mk late"><i></i></span> Late</span><span><span class="mk unclassified"><i></i></span> Not classified</span>'
          '<span><span class="mk issue"><i></i></span> Issue label added</span>'
          '<span>Each delivery is placed at its first Ready For Approval. Client revisions are shown as context inside each project.</span></div>')


def timeline(summaries: list[dict[str, Any]], retrieved: str | None, prefix: str, show_names: bool = True) -> str:
    months = sorted({_event_month(e) for s in summaries for e in s["events"]}, reverse=True)
    if not months:
        return empty_state("No dated events in this snapshot")
    pills = "".join(f'<button type="button" class="pill" role="tab" data-pill="{prefix}-{m}" aria-selected="{"true" if i == 0 else "false"}">'
                    f'{escape(month_name(m))}</button>' for i, m in enumerate(months))
    panels = "".join(f'<div id="{prefix}-{m}" role="tabpanel" {"" if i == 0 else "hidden"}><div class="tl"><div class="tl-inner">{_axis(m, retrieved)}'
                     f'{"".join(_lane(s, m, retrieved, show_names) for s in summaries)}</div></div></div>' for i, m in enumerate(months))
    return f'<div class="pills" role="tablist" data-pills style="margin-bottom:12px">{pills}</div>{panels}{LEGEND}'


# ---------------------------------------------------------------- CEO home sections

def management_focus(doc: dict[str, Any]) -> str:
    available = ("Speed vs team", "Deadlines", "Issue signals", "Current work", "Monthly history")
    calibrating = ("Attention", "Recognition", "Trends", "Team patterns", "Overall status")
    return (f'<section class="focus" aria-labelledby="focus-h"><div><span class="eyebrow"><i></i>Management focus</span>'
            f'<h2 id="focus-h">Management insights are being calibrated.</h2>'
            f'<p>Performance evidence for {_plural(len(doc["editors"]), "Editor")} is available below. Attention, recognition and trend insights will '
            'appear here once Atlas has approved rules for them — until then, nothing here is a judgement.</p></div>'
            '<div><div class="col"><h3>Available now</h3>' + "".join(f'<span class="fchip">{escape(a)}</span>' for a in available) + '</div>'
            '<div class="col"><h3>Calibrating</h3>' + "".join(f'<span class="fchip cal">{escape(c)}</span>' for c in calibrating) + '</div>'
            '<div class="col"><a href="#/system">How Atlas evaluates →</a></div></div></section>')


def issue_activity(doc: dict[str, Any], month: str | None) -> str:
    counts: dict[str, Counter[str]] = {}
    for s in doc["editors"]:
        for event in s["events"]:
            if event["kind"] == "issue_label" and month and _event_month(event) == month:
                counts.setdefault(event["label"], Counter())[s["display_name"]] += 1
    rows = "".join(f'<div><span>{escape(label)}</span><span class="chips">'
                   + "".join(f'<span class="chip">{escape(name)} <b>×{n}</b></span>' for name, n in sorted(c.items(), key=lambda p: (-p[1], p[0])))
                   + "</span></div>" for label, c in sorted(counts.items(), key=lambda p: (-sum(p[1].values()), p[0])))
    body = (f'<div class="rowlist">{rows}</div>' if rows
            else empty_state("No issue labels added this month", " A missing label is not an assessment of quality."))
    return (f'<div class="card"><h3>{icon("alert")}Issue activity</h3><p class="sub">Monday Performance Issues labels added in '
            f'{escape(month_name(month)) if month else "this period"}</p>{body}'
            '<p class="tiny quiet" style="margin-top:14px">Factual counts, no severity weighting. Which activity needs attention is not evaluated yet.</p></div>')


def patterns_card() -> str:
    return (f'<div class="card"><h3>{icon("layers")}Team &amp; process patterns</h3><p class="sub">Across the editing team</p>'
            + empty_state("Pattern detection is not active yet.", " Atlas currently shows shared evidence without assigning a team-level cause.")
            + "</div>")


def workload_card(doc: dict[str, Any]) -> str:
    rows = "".join(f'<div><span>{escape(s["display_name"])}</span>{workload_chips(s["current_workload"])}</div>' for s in doc["editors"])
    return (f'<div class="card"><h3>{icon("stack")}Current work</h3><p class="sub">Items by their current Monday status</p><div class="rowlist">{rows}</div>'
            '<p class="tiny quiet" style="margin-top:14px">Factual context. Capacity is not evaluated.</p></div>')


def history(doc: dict[str, Any]) -> str:
    months = sorted({m["month"] for s in doc["editors"] for m in s["monthly"]})
    if not months:
        return empty_state("No monthly history in this snapshot")
    first, last = months[0], months[-1]
    every, cursor = [], first
    while cursor <= last:
        every.append(cursor)
        y, mo = int(cursor[:4]), int(cursor[5:])
        cursor = f"{y + mo // 12}-{mo % 12 + 1:02d}"
    every.reverse()
    pills, panels = [], []
    for m in every:
        has = m in months
        selected = m == last
        label = calendar.month_abbr[int(m[5:])] + ("" if m[:4] == last[:4] else f" {m[:4]}")
        disabled = "" if has else ' disabled title="No data"'
        pills.append(f'<button type="button" class="pill" role="tab" data-pill="hist-{m}" aria-selected="{"true" if selected else "false"}"'
                     f'{disabled}>{escape(label)}</button>')
        if not has:
            continue
        rows = []
        for s in doc["editors"]:
            entry = next((x for x in s["monthly"] if x["month"] == m), None)
            if not entry:
                rows.append(f'<div class="row"><div class="who">{avatar(s["display_name"])}<span>{escape(s["display_name"])}</span></div>'
                            '<div class="quiet">No figures this month</div><div></div></div>')
                continue
            d = entry["deadline"]
            dl = (f'{deadline_strip(d)}<div class="small">{deadline_counts(d)} <span class="quiet">· late {d["late"]} / {d["evaluated"]} classified</span></div>'
                  if d else '<span class="quiet">No classified deadlines</span>')
            sp = "<br>".join(f'{escape(_labels(c["labels"], c["cohort_key"]))} <b>{_h(c["median_seconds"])}</b> <span class="quiet">n={c["projects"]}</span>'
                             for c in sorted(entry["speed_by_cohort"], key=lambda c: -c["projects"])[:4]) or '<span class="quiet">—</span>'
            more = len(entry["speed_by_cohort"]) - 4
            rows.append(f'<div class="row"><div class="who">{avatar(s["display_name"])}<span>{escape(s["display_name"])}</span></div><div>{dl}</div>'
                        f'<div class="small"><span class="tiny quiet">Median work duration</span><br>{sp}{f"<br><span class=quiet>+{more} more</span>" if more > 0 else ""}</div></div>')
        partial = next((x["partial"] for s in doc["editors"] for x in s["monthly"] if x["month"] == m), False)
        panels.append(f'<div id="hist-{m}" role="tabpanel" {"" if selected else "hidden"}><p class="small quiet" style="margin:0 0 4px">{escape(month_name(m))}'
                      f'{" · in progress" if partial else ""}</p><div class="hist">{"".join(rows)}</div></div>')
    return (f'<div class="pills" role="tablist" data-pills style="margin-bottom:12px">{"".join(pills)}</div><div class="card">{"".join(panels)}'
            '<p class="tiny quiet" style="margin:14px 0 0">Trend not evaluated yet — months are shown side by side without an improving or declining label. '
            'Speed is per exact Video Type, never pooled.</p></div>')


# ---------------------------------------------------------------- drawers shared by home and profile

def _speed_drawer(s: dict[str, Any]) -> str:
    speed = s["speed"]
    rows = []
    for c in speed["cohorts"]:
        compared = c["conclusion"] in SPEED_WORD
        verdict = (f'{abs(c["editor_vs_team_median_pct"] or 0):.1f}% {SPEED_WORD[c["conclusion"]]} than the team median' if compared
                   and c["conclusion"] != "equal_to_team_median" else ("Level with the team median" if compared else "Not comparable"))
        rows.append(f'<h4>{escape(_labels(c["labels"]))}</h4>' + _dl([
            ("Editor median", f'{_h(c["editor_median_seconds"])} · n={c["editor_sample_size"]}'),
            ("Team median", (f'{_h(c["team_median_seconds"])} · n={c["team_sample_size"] if c["team_sample_size"] is not None else "—"}'
                             f'{" · " + _plural(c["team_editor_count"], "Editor") if c["team_editor_count"] else ""}')),
            ("Result", escape(verdict)), ("Why", escape(STATUS_TEXT.get(c["comparison_status"], c["comparison_status"])))]))
    intro = (f'<p>Work duration runs from the first In Progress to the first Ready For Approval. Each Video Type is compared only with the '
             f'{escape(speed["benchmark_statistic"])} of every eligible Editor in the same exact Video Type (this Editor included). A comparison needs at least '
             f'{speed["minimum_editor_sample_size"]} of this Editor\'s projects and at least one other Editor.</p>')
    return template(f"speed-{s['editor_id']}", f"Speed · {s['display_name']}", intro + ("".join(rows) or '<p class="quiet">No measurable projects.</p>'))


def _dq_drawer(s: dict[str, Any]) -> str:
    d = s["deadline"]
    rows = _dl([("Classified", str(d["evaluated"])), ("ETA without a time", str(d.get("not_classifiable_insufficient_eta_precision") or 0)),
                ("No Requested ETA", str(d.get("not_classifiable_missing_eta") or 0)), ("Not evaluated for other reasons", str(d.get("not_evaluated_other") or 0))])
    notes = "".join(f"<li>{escape(w['text'])}</li>" for w in s["warnings"])
    return template(f"dq-{s['editor_id']}", f"Deadline data · {s['display_name']}",
                    '<p>A delivery is classified only when its Requested ETA has a date and a time. Atlas never guesses a missing time. '
                    'Delivery is compared with the ETA in effect at the first Ready For Approval; exactly at the ETA is on time.</p>'
                    + rows + (f"<h4>Data notes</h4><ul>{notes}</ul>" if notes else ""))


# ---------------------------------------------------------------- Editor Profile

def _metric_cards(s: dict[str, Any]) -> str:
    q, d, sample = s["quality"], s["deadline"], s["sample"]
    eid = s["editor_id"]
    compared = s["speed"]["compared_cohorts"]
    if compared:
        c = compared[0]
        word = SPEED_WORD[c["conclusion"]]
        relation = "level with" if word == "level" else f"{abs(c['editor_vs_team_median_pct'] or 0):.1f}% {word} than"
        speed = (f'<div class="v">{_h(c["editor_median_seconds"])}</div><div class="small">{escape(_labels(c["labels"]))} median</div>'
                 f'<div class="small quiet">{relation} team '
                 f'{_h(c["team_median_seconds"])} · n={c["editor_sample_size"]}</div>')
    else:
        speed = '<div class="v" style="font-size:24px;margin-top:10px">—</div><div class="small soft">No comparable Video Type yet</div>'
    deadline = (f'{deadline_strip(d, True)}<div class="small">{deadline_counts(d)}</div><div class="small quiet">{d["evaluated"]} classified</div>'
                if d["evaluated"] else '<div class="v" style="font-size:24px;margin-top:10px">—</div><div class="small soft">Deadline data unavailable</div>')
    issues = (f'<div class="v">{q["total_occurrences"]}</div><div class="small quiet">across {_plural(q["projects_with_issues"], "project")} of '
              f'{q["completed_projects_attributed"]}</div>' if q["total_occurrences"]
              else '<div class="v">0</div><div class="small soft">No issue labels recorded</div>')
    projects = (f'<div class="v">{sample["completed_projects"]}</div><div class="small quiet">completed · {sample["speed_eligible_projects"]} measurable for speed</div>')
    cards = [("alert", "Issue signals", issues, f"quality-{eid}"), ("speed", "Speed vs team", speed, f"speed-{eid}"),
             ("clock", "Deadlines", deadline, f"dq-{eid}"), ("layers", "Projects", projects, f"cov-{eid}")]
    return '<div class="metrics">' + "".join(
        f'<button type="button" class="card metric" data-drawer="{tid}"><span class="eyebrow" style="display:flex;gap:6px;align-items:center">{icon(ic, 13)}{k}</span>{v}</button>'
        for ic, k, v, tid in cards) + "</div>"


def _quality_drawer(s: dict[str, Any]) -> str:
    q = s["quality"]
    rows = "".join(f'<h4>{escape(row["label"])} · {row["occurrences"]}</h4>{_project_list(s, row["monday_item_ids"])}' for row in q["by_label"])
    return template(f"quality-{s['editor_id']}", f"Issue signals · {s['display_name']}",
                    '<p>Labels from the Monday Performance Issues column. Each label counts once; there are no severity weights, and no cause is inferred.</p>'
                    + (rows or '<p class="quiet">No issue labels recorded. This is not an assessment of quality.</p>'))


def _coverage_drawer(s: dict[str, Any]) -> str:
    sample = s["sample"]
    reasons = "".join(f"<li><code>{escape(r)}</code> {n}</li>" for r, n in sample["exclusions_by_reason"].items()) or "<li>None</li>"
    return template(f"cov-{s['editor_id']}", f"Projects · {s['display_name']}",
                    _dl([("Completed", str(sample["completed_projects"])), ("Open", str(sample["open_projects"])),
                         ("Measurable for speed", str(sample["speed_eligible_projects"]))])
                    + f"<h4>Excluded from metrics</h4><ul>{reasons}</ul><h4>All projects</h4>{_project_list(s)}")


def _cohort_drawers(s: dict[str, Any]) -> str:
    return "".join(template(f"c-{s['editor_id']}-{c['cohort_key']}", _labels(c["labels"]), _dl([
        ("Editor median", f'{_h(c["editor_median_seconds"])} · n={c["editor_sample_size"]}'),
        ("Team median", _h(c["team_median_seconds"])), ("Team typical range", (f'{_h((c.get("team_typical_range_seconds") or {}).get("p25"))} – '
                                                                               f'{_h((c.get("team_typical_range_seconds") or {}).get("p75"))}'
                                                                               if c.get("team_typical_range_seconds") else "—")),
        ("Status", escape(STATUS_TEXT.get(c["comparison_status"], c["comparison_status"])))]) + "<h4>Projects</h4>" + _project_list(s, c["editor_project_ids"]))
        for c in s["speed"]["cohorts"])


def _speed_panel(s: dict[str, Any]) -> str:
    out = []
    for c in s["speed"]["cohorts"]:
        compared = c["conclusion"] in SPEED_WORD
        if compared and c["conclusion"] != "equal_to_team_median":
            verdict = f'<b>{abs(c["editor_vs_team_median_pct"] or 0):.1f}% {SPEED_WORD[c["conclusion"]]}</b> than team median'
        elif compared:
            verdict = "<b>Level</b> with team median"
        else:
            verdict = f'<span class="soft">Not comparable</span> · <span class="quiet">{escape(STATUS_TEXT.get(c["comparison_status"], ""))}</span>'
        out.append(f'<button type="button" class="card cohort{" cmp" if compared else ""}" data-drawer="c-{escape(s["editor_id"])}-{escape(c["cohort_key"])}">'
                   f'<span style="font-size:16px">{escape(_labels(c["labels"]))}</span><div class="nums"><div><b>{_h(c["editor_median_seconds"])}</b><span>Editor</span></div>'
                   f'<div><b>{_h(c["team_median_seconds"])}</b><span>Team</span></div></div><div class="small">{verdict}</div>'
                   f'<span class="tiny quiet">n = {c["editor_sample_size"]} Editor · {c["team_sample_size"] if c["team_sample_size"] is not None else "—"} team projects</span></button>')
    body = f'<div class="cohorts">{"".join(out)}</div>' if out else empty_state("No measurable projects")
    return ('<div class="sh"><div><h2>Speed by Video Type</h2><p>Each Video Type is compared only within itself — never pooled.</p></div>'
            + info_button("How speed is compared", f"speed-{s['editor_id']}") + f'</div>{body}')


def _deadline_panel(s: dict[str, Any]) -> str:
    d = s["deadline"]
    unclassified = (d.get("not_classifiable_insufficient_eta_precision") or 0) + (d.get("not_classifiable_missing_eta") or 0)
    if d["evaluated"]:
        top = (f'<div class="card">{deadline_strip(d, True)}<div style="font-size:20px">{deadline_counts(d)}</div>'
               f'<p class="small quiet" style="margin:6px 0 0">{d["evaluated"]} classified · median margin {_signed_h(d.get("median_delta_seconds"))} '
               f'(negative = before the ETA){f" · {unclassified} unclassified" if unclassified else ""}</p>'
               '<p class="tiny quiet" style="margin:14px 0 0"><span class="key e"></span>Early <span class="key o" style="margin-left:10px"></span>On time '
               '<span class="key l" style="margin-left:10px"></span>Late</p></div>')
    else:
        top = f'<div class="card">{empty_state("Deadline data unavailable", " No completed project has a Requested ETA with a time, so none can be classified.")}</div>'
    months = "".join(f'<div class="row"><div>{escape(m["month_name"])}{" <span class=quiet>· in progress</span>" if m["partial"] else ""}</div>'
                     f'<div>{deadline_strip(m["deadline"])}<div class="small">{deadline_counts(m["deadline"])} <span class="quiet">of {m["deadline"]["evaluated"]}</span></div></div>'
                     f'<div class="small quiet">late {_pct(m["deadline"]["late_rate"])}</div></div>' for m in s["monthly"] if m["deadline"])
    groups = "".join(f'<button type="button" class="ghost" data-drawer="dl-{escape(s["editor_id"])}-{r}">{RESULT_TEXT[r]} projects</button> '
                     for r in ("early", "on_time", "late") if d.get(r))
    return ('<div class="sh"><div><h2>Deadline performance</h2><p>First Ready For Approval against the Requested ETA in effect at that moment.</p></div>'
            + info_button("Classification coverage", f"dq-{s['editor_id']}") + f'</div>{top}'
            f'<div style="margin-top:12px">{groups}</div>'
            + (f'<div class="card hist" style="margin-top:16px"><p class="eyebrow" style="margin:0">By month</p>{months}</div>' if months else ""))


def _deadline_group_drawers(s: dict[str, Any]) -> str:
    return "".join(template(f"dl-{s['editor_id']}-{r}", f"{RESULT_TEXT[r]} deliveries · {s['display_name']}",
                            _project_list(s, [row["monday_item_id"] for row in s["projects"] if row["deadline_result"] == r]))
                   for r in ("early", "on_time", "late"))


def _quality_panel(s: dict[str, Any]) -> str:
    q = s["quality"]
    if q["by_label"]:
        rows = "".join(f'<div><span style="font-size:16px">{escape(row["label"])}</span><span><b style="font-size:20px;font-weight:400">{row["occurrences"]}</b> '
                       f'<button type="button" class="info" data-drawer="ql-{escape(s["editor_id"])}-{i}">{_plural(len(set(row["monday_item_ids"])), "project")}</button></span></div>'
                       for i, row in enumerate(q["by_label"]))
        body = (f'<div class="card"><div class="rowlist">{rows}</div><p class="small quiet" style="margin:16px 0 0">Affected projects: '
                f'{q["projects_with_issues"]} / {q["completed_projects_attributed"]}</p></div>')
    else:
        body = f'<div class="card">{empty_state("No issue labels recorded", " This is not an assessment of quality — only that no Monday label was added.")}</div>'
    return (f'<div class="sh"><div><h2>Quality &amp; performance signals</h2><p>From the Monday Performance Issues column. No severity weights, no inferred causes.</p></div></div>'
            f'<div class="two">{body}<div class="card"><h3 style="margin:0 0 6px;font-weight:500;font-size:16px">Positive signals</h3>'
            f'{empty_state(NO_SIGNAL, " Recognition signals will appear here once supported by evidence.")}'
            f'<p class="tiny quiet" style="margin:14px 0 0">For Bonus labels on {_plural(q["for_bonus_context_projects"], "project")} — shown as context, not as a signal.</p></div></div>')


def _quality_label_drawers(s: dict[str, Any]) -> str:
    return "".join(template(f"ql-{s['editor_id']}-{i}", f"{row['label']} · {s['display_name']}", _project_list(s, row["monday_item_ids"]))
                   for i, row in enumerate(s["quality"]["by_label"]))


def _revision_panel(s: dict[str, Any]) -> str:
    r = s["revisions"]
    tiles = (f'<div class="metrics" style="margin-top:0"><div class="card"><span class="eyebrow">Client revision events</span><div class="metric"><span class="v">{r["client_revision_events"]}</span></div></div>'
             f'<div class="card"><span class="eyebrow">Projects with client revisions</span><div class="metric"><span class="v">{r["projects_with_client_revisions"]}'
             f'</span><span class="small quiet">of {r["completed_projects"]} completed</span></div></div>'
             f'<div class="card"><span class="eyebrow">Internal revision events</span><div class="metric"><span class="v">{r["internal_revision_events"] if r["internal_revision_events"] is not None else "—"}</span></div></div></div>')
    listing = (f'<button type="button" class="ghost" data-drawer="rv-{escape(s["editor_id"])}">Projects with client revisions</button>'
               if r["monday_item_ids_with_client_revisions"] else "")
    return (f'<div class="sh"><div><h2>Client revision context</h2><p>Context only. Revisions do not imply Editor fault and never affect any metric.</p></div></div>'
            f'{tiles}<div style="margin-top:12px">{listing}</div>')


def _revision_drawer(s: dict[str, Any]) -> str:
    return template(f"rv-{s['editor_id']}", f"Client revision context · {s['display_name']}",
                    '<p>Projects where a client asked for changes. Their cause is not known, and they are not a performance signal.</p>'
                    + _project_list(s, s["revisions"]["monday_item_ids_with_client_revisions"]))


def _snapshot(s: dict[str, Any]) -> str:
    heads = ["Doing well", "May need a look", "Evidence", "Over time", "Current work"]
    out = []
    for head, block in zip(heads, s["snapshot"]):
        facts = block["facts"] or []
        items = "".join(f"<li>{escape(f)}</li>" for f in facts) or f'<li class="quiet" style="list-style:none;margin-left:-18px">{NO_SIGNAL}</li>'
        judged = f'<div class="j">{escape(block["judgement"]["label"])}: {NOT_EVALUATED}</div>' if block["judgement"] else '<div class="j">&nbsp;</div>'
        out.append(f'<div class="card"><h3>{escape(head)}</h3>{judged}<ul>{items}</ul></div>')
    return f'<div class="qa">{"".join(out)}</div>'


def editor_profile(s: dict[str, Any], retrieved: str | None, url: str | None) -> str:
    eid = s["editor_id"]
    tabs = [("overview", "Overview"), ("quality", "Quality"), ("speed", "Speed"), ("deadlines", "Deadlines"), ("revisions", "Revisions"), ("evidence", "Evidence")]
    pills = "".join(f'<button type="button" class="pill" role="tab" data-pill="t-{eid}-{k}" aria-selected="{"true" if i == 0 else "false"}">{v}</button>'
                    for i, (k, v) in enumerate(tabs))
    overview = (f'<div class="sh"><div><h2>Performance timeline</h2><p>Deliveries and issue labels, in the order they happened.</p></div></div>'
                f'<div class="card pulse">{timeline([s], retrieved, f"pt-{eid}", show_names=False)}</div>'
                f'<section style="margin-top:32px"><div class="sh"><div><h2>Snapshot</h2><p>Facts from the Atlas engine. Judgements appear once their rules are approved.</p></div></div>{_snapshot(s)}</section>'
                f'<section style="margin-top:32px"><div class="card" style="display:flex;gap:16px;align-items:center">{icon("spark", 22)}<div><b style="font-weight:500">Suggested action</b>'
                f'<div class="small quiet">Not available yet. Management actions will appear here once Atlas has approved rules for them.</div></div></div></section>')
    evidence = (f'<div class="sh"><div><h2>Evidence</h2><p>Every completed and open project attributed to {escape(s["display_name"])}, most recent first. Select one for its Monday events.</p></div>'
                f'<button type="button" class="ghost" data-drawer="report-{eid}">{icon("doc", 14)} Complete evidence report</button></div>'
                f'<div class="card">{_project_list(s)}</div>')
    panels = {"overview": overview, "quality": _quality_panel(s), "speed": _speed_panel(s), "deadlines": _deadline_panel(s),
              "revisions": _revision_panel(s), "evidence": evidence}
    body = "".join(f'<div id="t-{eid}-{k}" class="panel" role="tabpanel" {"" if i == 0 else "hidden"}>{panels[k]}</div>' for i, (k, _) in enumerate(tabs))
    last_month = next((m["month_name"] for m in s["monthly"]), None)
    header = (f'<div class="phead">{avatar(s["display_name"], "xl")}<div><span class="eyebrow">Editor</span><h1>{escape(s["display_name"])}</h1>'
              f'<div class="facts" style="margin-top:12px"><div><span>Current work</span>{workload_chips(s["current_workload"], 4)}</div>'
              f'<div><span>Period</span><b>{escape(last_month or "—")}</b></div><div><span>Data updated</span><b>{escape(_date(retrieved, False))}</b></div></div></div>'
              f'{overall_placeholder()}</div>')
    report = template(f"report-{eid}", f"Complete evidence report · {s['display_name']}",
                      '<p>The full Editor Profile as produced by the Atlas engine, with every project, exclusion and Monday event ID.</p>'
                      f'<iframe title="Complete evidence report" data-report="{escape(eid)}"></iframe>')
    drawers = (_project_templates(s, url) + _event_templates(s) + _speed_drawer(s) + _dq_drawer(s) + _quality_drawer(s) + _coverage_drawer(s)
               + _cohort_drawers(s) + _deadline_group_drawers(s) + _quality_label_drawers(s) + _revision_drawer(s) + report)
    return (f'<div data-view="editor:{escape(eid)}" hidden><a class="back" href="#/">{icon("back", 15)} Editor team</a>{header}{_metric_cards(s)}'
            f'<div class="tabs"><div class="pills" role="tablist" data-pills>{pills}</div></div>{body}{drawers}</div>')


# ---------------------------------------------------------------- Data & System

def data_system(doc: dict[str, Any]) -> str:
    source = doc["source"]
    window = source.get("activity_log_window") or {}
    snapshot = _dl([("Monday data retrieved", escape(_date(source.get("retrieved_at")))),
                    ("Activity window", f'{escape(_date(window.get("since")))} → {escape(_date(window.get("until")))}'),
                    ("Executable contract", f'<code>{escape(str(source.get("executable_contract_version")))}</code>'),
                    ("Dashboard document", f'<code>{escape(doc["dashboard_version"])}</code>'), ("Generated", escape(_date(doc["generated_at"])))])
    first = doc["editors"][0] if doc["editors"] else None
    approved = ""
    if first:
        approved = ("<ul>"
                    f'<li><b>Speed</b> — elapsed time from first In Progress to first Ready For Approval; compared with the {escape(first["speed"]["benchmark_statistic"])} '
                    f'of every eligible Editor in the same exact Video Type; a conclusion needs {first["speed"]["minimum_editor_sample_size"]}+ Editor projects and another Editor.</li>'
                    f'<li><b>Deadlines</b> — rule <code>{escape(str(first["deadline"]["rule_version"]))}</code>: first Ready For Approval against the Requested ETA in effect at that moment; '
                    'no tolerance; a date-only or missing ETA is never classified.</li>'
                    '<li><b>Quality</b> — Monday Performance Issues labels; 1 occurrence = 1 label; no severity weights.</li>'
                    '<li><b>Revisions</b> — context only; never a performance signal.</li></ul>')
    pending = "".join(f'<tr><td>{escape(rule["label"])}</td><td>{NOT_EVALUATED}</td><td>{escape(rule["reason"])}</td></tr>' for rule in PENDING_RULES.values())
    editors = "".join(f'<tr><td>{escape(s["display_name"])}</td><td><code>{escape(s["editor_id"])}</code></td><td>{escape(str(s["monday_label"]))}</td>'
                      f'<td><code>{escape(str(s["mapping_version"]))}</code></td><td><code>{escape(s["profile_contract_version"])}</code></td>'
                      f'<td>{s["sample"]["completed_projects"]}</td></tr>' for s in doc["editors"])
    notes = "".join(f'<tr><td>{escape(s["display_name"])}</td><td>{escape(w["text"])}</td><td><code>{escape(w["source"])}</code></td></tr>'
                    for s in doc["editors"] for w in s["warnings"])
    excluded = "".join(f'<tr><td>{escape(s["display_name"])}</td><td><code>{escape(r)}</code></td><td>{n}</td></tr>'
                       for s in doc["editors"] for r, n in s["sample"]["exclusions_by_reason"].items())
    speed_rows = "".join(f'<tr><td>{escape(s["display_name"])}</td><td>{escape(_labels(c["labels"]))}</td><td>{c["editor_sample_size"]}</td>'
                         f'<td>{c["team_sample_size"] if c["team_sample_size"] is not None else "—"}</td><td>{"yes" if c["benchmark_eligible"] else "no"}</td>'
                         f'<td>{escape(STATUS_TEXT.get(c["comparison_status"], c["comparison_status"]))}</td></tr>' for s in doc["editors"] for c in s["speed"]["cohorts"])
    coverage = doc.get("attribution_coverage")
    cov = ""
    if coverage:
        reasons = "".join(f"<tr><td><code>{escape(r)}</code></td><td>{n}</td></tr>" for r, n in coverage["not_attributed_by_reason"].items())
        cov = (f'<div class="card"><h3>Editor attribution coverage</h3><p class="small soft">{coverage["attributed"]} of {coverage["completed"]} completed projects in this '
               f'snapshot have a verified Editor. The others are not shown on any Editor; unverified labels stay quarantined until confirmed.</p>'
               f'<table><thead><tr><th>Reason not attributed</th><th>Projects</th></tr></thead><tbody>{reasons}</tbody></table></div>')
    missing = "".join(f'<tr><td>{escape(e["display_name"])}</td><td><code>{escape(e["editor_id"])}</code></td><td>{escape(str(e["monday_label"]))}</td></tr>'
                      for e in doc["editors_without_attributable_data"])
    presentation = ("<ul><li>Editor card headline: the first comparable Video Type speed result; otherwise deadlines if any are classified; otherwise the "
                    "project count. A fixed display order, not a judgement.</li><li>Timelines place each project at its first Ready For Approval and each issue "
                    "label at the time it was added. Revision events are not dated in the Editor Profile, so they appear only as context on each project.</li>"
                    "<li>Month pills group dated facts by UTC calendar month.</li></ul>")

    def table(head: list[str], rows: str) -> str:
        return (f'<div style="overflow-x:auto"><table><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead>'
                f'<tbody>{rows or "<tr><td colspan=9 class=quiet>None</td></tr>"}</tbody></table></div>')

    return (f'<div data-view="system" class="sys" hidden><div class="hello"><div><span class="eyebrow">Atlas</span><h1>Data &amp; System</h1>'
            '<p>Where every figure comes from, which rules apply, and what Atlas does not evaluate yet.</p></div></div>'
            f'<div class="card"><h3>Snapshot</h3>{snapshot}</div>'
            f'<div class="card"><h3>Approved rules in use</h3>{approved}</div>'
            f'<div class="card"><h3>Not evaluated yet</h3>{table(["Field", "State", "Reason"], pending)}</div>'
            f'<div class="card"><h3>Editors and identity</h3>{table(["Editor", "Atlas ID", "Monday label", "Mapping", "Profile", "Completed"], editors)}</div>'
            f'<div class="card"><h3>Data-quality notes</h3>{table(["Editor", "Note", "Profile field"], notes)}</div>'
            f'<div class="card"><h3>Speed benchmark eligibility</h3>{table(["Editor", "Video Type", "Editor n", "Team n", "Eligible", "Status"], speed_rows)}</div>'
            f'<div class="card"><h3>Projects excluded from metrics</h3>{table(["Editor", "Reason", "Projects"], excluded)}</div>'
            f'{cov}<div class="card"><h3>Mapped Editors without attributable projects</h3>{table(["Editor", "Atlas ID", "Monday label"], missing)}</div>'
            f'<div class="card"><h3>Presentation notes</h3>{presentation}</div></div>')


# ---------------------------------------------------------------- page

def render_dashboard_html(doc: dict[str, Any], profile_pages: dict[str, str], monday_item_url: str | None = None) -> str:
    """Render the dashboard. ``profile_pages`` maps editor_id -> the full Editor Profile report HTML, embedded unchanged as the audit view."""
    source = doc["source"]
    retrieved = source.get("retrieved_at")
    month = str(retrieved)[:7] if retrieved else None
    blob = json.dumps(profile_pages).replace("</", "<\\/")
    editors = doc["editors"]
    cards = "".join(editor_card(s) for s in editors) or empty_state("No Editor has attributable projects in this snapshot")
    meta = ((f'<span><b>{escape(month_name(month))}</b> · in progress</span>' if month else "")
            + f'<span><b>{len(editors)}</b> Editors</span><span>Updated {escape(_date(retrieved))}</span>')
    home = (f'<div data-view="team"><div class="hello"><div><span class="eyebrow">Atlas</span><h1 id="greeting">Editing team overview</h1>'
            f'<p>Here’s your editing team today.</p></div><div class="meta">{meta}</div></div>'
            f'{management_focus(doc)}'
            f'<section aria-labelledby="team-h"><div class="sh"><div><h2 id="team-h">Editor Team</h2><p>Current performance evidence across the editing team.</p></div></div>'
            f'<div class="grid-ed">{cards}</div></section>'
            f'<section aria-labelledby="pulse-h"><div class="sh"><div><h2 id="pulse-h">Team Pulse</h2><p>What happened, day by day. Select a marker for its evidence.</p></div></div>'
            f'<div class="card pulse">{timeline(editors, retrieved, "pulse")}</div></section>'
            f'<section aria-label="Team context"><div class="ctx">{issue_activity(doc, month)}{patterns_card()}{workload_card(doc)}</div></section>'
            f'<section aria-labelledby="hist-h"><div class="sh"><div><h2 id="hist-h">Performance History</h2><p>Month by month, most recent first.</p></div></div>{history(doc)}</section>'
            + "".join(_speed_drawer(s) + _dq_drawer(s) for s in editors) + "</div>")
    profiles = "".join(editor_profile(s, retrieved, monday_item_url) for s in editors)
    # The home view and each profile view declare their own speed/deadline drawers; keep one copy of each id.
    body = _dedupe_templates(home + profiles)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Atlas</title><style>{CSS}</style></head><body><div class=\"shell\">"
            f'<header class="topbar"><a class="brand" href="#/"><i></i>Atlas</a><nav class="nav" aria-label="Main">'
            f'<a href="#/" data-nav="team" aria-current="page">Editor team</a><a href="#/system" data-nav="system">Data &amp; System</a></nav></header>'
            f'<main>{body}{data_system(doc)}</main></div>'
            '<div class="scrim"></div><aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="drawer-title">'
            f'<header><h2 id="drawer-title"></h2><button type="button" class="x" aria-label="Close">{icon("x")}</button></header><div class="body"></div></aside>'
            f'<script type="application/json" id="atlas-reports">{blob}</script><script>{SCRIPT}</script></body></html>')


def _dedupe_templates(html: str) -> str:
    seen: set[str] = set()
    out, cursor = [], 0
    while True:
        start = html.find('<template id="', cursor)
        if start < 0:
            out.append(html[cursor:])
            return "".join(out)
        end = html.find("</template>", start) + len("</template>")
        tid = html[start + 14: html.find('"', start + 14)]
        out.append(html[cursor:start])
        if tid not in seen:
            seen.add(tid)
            out.append(html[start:end])
        cursor = end
