"""Atlas CEO Dashboard and Editor Profile pages: static, self-contained HTML in English or Arabic (presentation only).

Rendered from the dashboard document (``atlas_commander.dashboard``). The page formats values that
are already in that document: durations, percentages, dates, and marker positions on a timeline. It
computes no metric, comparison or conclusion. Management judgements with no approved rule
(``atlas_commander.management``) appear as calm empty states; their reasons are listed under
Data & System.

Both languages are rendered by the same functions from the same document; only the locale
(:class:`atlas_commander.i18n.Loc`) differs. Every Atlas-owned string comes from the catalogue;
Monday values (Editor names, Video Types, statuses, issue labels, IDs) are shown exactly as recorded,
direction-isolated in ``<bdi>``/``<code>``.

Presentation-only choices, documented so they are never mistaken for business rules:

- Editor card headline: the first comparable Video Type speed result (cohorts in the profile's order,
  largest Editor sample first); otherwise the deadline results, if any are classified; otherwise the
  completed-project count. This is a fixed display order, not a judgement of which metric matters most.
- Timelines place each completed project at its first Ready For Approval, and each Monday Performance
  Issues label at the time it was added. The profile does not date revision events, so revisions
  appear only as neutral context on their project. Time always runs left (earlier) to right (later),
  also on Arabic pages: the direction of the text is not the direction of time.
- Month pills group those dated facts by their UTC calendar month.
"""

from __future__ import annotations

import calendar
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from html import escape
from typing import Any

from atlas_commander.capabilities import capabilities
from atlas_commander.i18n import EN, Html, Loc
from atlas_commander.interpretation_html import CSS as IA_CSS
from atlas_commander.interpretation_html import interpretation_section, overall_badge, window_caption
from atlas_commander.management import PENDING_RULES, V15_PENDING_SLOTS, V15_REASONS

SPEED_WORD = {"faster_than_team_median": "faster", "slower_than_team_median": "slower", "equal_to_team_median": "level"}
RESULTS = ("early", "on_time", "late")

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
.fchip{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:var(--r-pill);font-size:13px;margin:0;margin-inline-end:6px;margin-block-end:6px;background:var(--dark-2);color:var(--on-dark)}
.fchip.cal{background:transparent;border:1px dashed #56574d;color:var(--on-dark-2)}
.grid-ed{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:var(--s-4)}
.ed{position:relative;display:flex;flex-direction:column;gap:var(--s-4);transition:transform var(--t),box-shadow var(--t),border-color var(--t)}
.ed:hover{transform:translateY(-2px);box-shadow:var(--shadow-2);border-color:var(--line-2)}
.ed .stretch::after{content:"";position:absolute;inset:0;border-radius:var(--r-lg)}
.ed .above{position:relative;z-index:1}
.who{display:flex;align-items:center;gap:var(--s-3)}.who h3{margin:0;font-size:20px;font-weight:500;letter-spacing:-.01em}
.avatar{flex:none;width:46px;height:46px;border-radius:50%;background:var(--surface-3);color:var(--ink);display:grid;place-items:center;font-size:15px;letter-spacing:.02em;font-weight:500}
.avatar.xl{width:84px;height:84px;font-size:28px}
.overall{margin-inline-start:auto;text-align:end}.overall b{display:block;font-size:22px;font-weight:300;line-height:1}.overall span{font-size:11.5px;color:var(--ink-3)}
.hero{background:var(--surface-2);border-radius:var(--r-md);padding:var(--s-4) var(--s-5);display:flex;flex-direction:column;gap:6px}
.hero .big{font-size:44px;font-weight:300;letter-spacing:-.03em;line-height:1}.hero .big small{font-size:15px;letter-spacing:.06em;text-transform:uppercase;margin-inline-start:6px;font-weight:500}
.hero .pair{display:flex;gap:var(--s-5);margin-top:4px}.hero .pair div b{display:block;font-size:17px;font-weight:500}.hero .pair div span{font-size:12px;color:var(--ink-3)}
.line{display:grid;grid-template-columns:108px 1fr;gap:var(--s-3);align-items:start;font-size:14px}
.line>.k{color:var(--ink-3);font-size:12.5px;padding-top:2px;display:flex;align-items:center;gap:6px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:var(--r-pill);background:var(--surface-2);font-size:12.5px;color:var(--ink-2)}
.chip{white-space:nowrap}.chip b{font-weight:500;color:var(--ink)}.chip.context{background:transparent;border:1px dashed var(--line-2)}
.strip{display:flex;gap:3px;height:8px;border-radius:var(--r-pill);overflow:hidden;background:var(--surface-3);margin:4px 0 6px}
.strip.lg{height:14px}.strip i{display:block;height:100%}.strip .e{background:var(--ink)}.strip .o{background:var(--ink-3)}.strip .l{background:var(--late)}
.key{display:inline-block;width:9px;height:9px;border-radius:3px;margin-inline-end:5px;vertical-align:-1px}.key.e{background:var(--ink)}.key.o{background:var(--ink-3)}.key.l{background:var(--late)}
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
.tl{overflow-x:auto;direction:ltr}.tl-inner{min-width:680px}
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
.metric{text-align:start;cursor:pointer;display:flex;flex-direction:column;gap:6px;transition:box-shadow var(--t),border-color var(--t)}
.metric:hover{box-shadow:var(--shadow-1);border-color:var(--line-2)}
.metric .v{font-size:40px;font-weight:300;letter-spacing:-.03em;line-height:1.05}.metric .v small{font-size:14px;letter-spacing:.04em;text-transform:uppercase;margin-inline-start:4px}
.tabs{position:sticky;top:0;z-index:5;background:var(--shell);padding:var(--s-3) 0;margin-top:var(--s-6)}
.panel{margin-top:var(--s-4)}.two{display:grid;grid-template-columns:1.4fr 1fr;gap:var(--s-4)}
.qa{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:var(--s-4)}
.qa h3{font-size:14px;font-weight:500;margin:0 0 4px}.qa .j{font-size:12.5px;color:var(--ink-3);margin-bottom:8px}.qa ul{margin:0;padding-inline-start:18px;font-size:14px;color:var(--ink-2)}
.cohorts{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:var(--s-3)}
.cohort{text-align:start;cursor:pointer;display:flex;flex-direction:column;gap:8px;border-radius:var(--r-md);padding:var(--s-4) var(--s-5)}
.cohort .nums{display:flex;gap:var(--s-5)}.cohort .nums b{display:block;font-size:20px;font-weight:400}.cohort .nums span{font-size:12px;color:var(--ink-3)}
.cohort.cmp{border-color:var(--ink)}
.list{display:flex;flex-direction:column}.list button{all:unset;cursor:pointer;display:grid;grid-template-columns:130px 1fr 110px 1fr 90px;gap:var(--s-3);padding:12px 6px;border-bottom:1px solid var(--line);font-size:13.5px;align-items:center}
.list button:hover{background:var(--surface-2)}.list button:focus-visible{outline:2px solid var(--ink)}
.res-early{color:var(--ink)}.res-late{color:var(--late)}.res-on_time{color:var(--ink)}
.sys table{width:100%;border-collapse:collapse;font-size:13.5px}.sys th,.sys td{text-align:start;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.sys th{font-weight:500;color:var(--ink-3);font-size:12.5px}.sys .card{margin-top:var(--s-4)}.sys h3{margin:0 0 var(--s-3);font-size:17px;font-weight:500}
.sys code,.drawer code{font-size:12px;background:var(--surface-2);padding:1px 6px;border-radius:6px;word-break:break-all}
.status-head{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s-4);margin:var(--s-3) 0 var(--s-4)}
.status-head>div,.status-detail{border:1px solid var(--line);border-radius:var(--r-md);padding:var(--s-4)}
.status-head span{display:block;color:var(--ink-3);font-size:12.5px}.status-head b{display:block;margin-top:4px;font-size:20px;font-weight:500}
.status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s-4);margin-top:var(--s-4)}
.status-detail h4{margin:0 0 var(--s-3);font-size:14px;font-weight:500}.status-detail dl{grid-template-columns:minmax(120px,170px) 1fr}
.scrim{position:fixed;inset:0;background:rgba(29,30,24,.28);opacity:0;pointer-events:none;transition:opacity var(--t);z-index:20}
.drawer{position:fixed;top:12px;inset-inline-end:12px;bottom:12px;width:min(520px,calc(100vw - 24px));background:var(--surface);border-radius:var(--r-lg);box-shadow:var(--shadow-2);
transform:translateX(calc(100% + 24px));transition:transform var(--t);z-index:21;display:flex;flex-direction:column}
body.drawer-open .scrim{opacity:1;pointer-events:auto}body.drawer-open .drawer{transform:none}
.drawer header{display:flex;justify-content:space-between;align-items:center;padding:var(--s-5) var(--s-5) var(--s-3)}
.drawer header h2{margin:0;font-size:20px;font-weight:500}.drawer .body{overflow:auto;padding:0 var(--s-5) var(--s-5)}
.drawer .x{border:0;background:var(--surface-2);width:36px;height:36px;border-radius:50%;cursor:pointer;display:grid;place-items:center}
.drawer dl,.sys dl{display:grid;grid-template-columns:170px 1fr;gap:8px 12px;margin:0;font-size:13.5px}.drawer dt,.sys dt{color:var(--ink-3)}.drawer dd,.sys dd{margin:0}
.drawer h4{margin:var(--s-5) 0 var(--s-2);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:500}
.drawer iframe{width:100%;height:70vh;border:1px solid var(--line);border-radius:var(--r-md)}
.drawer p{font-size:14px;color:var(--ink-2)}.drawer ul{padding-inline-start:18px;font-size:14px}
[hidden]{display:none!important}
@media (max-width:1080px){.ctx{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}}
@media (max-width:760px){.shell{margin:0;border-radius:0;padding:var(--s-4) var(--s-4) var(--s-7)}.focus{grid-template-columns:1fr;padding:var(--s-5)}
.grid-ed{grid-template-columns:1fr}.ctx{grid-template-columns:1fr}.hist .row{grid-template-columns:1fr;gap:var(--s-2)}.phead{grid-template-columns:auto 1fr}
.phead .overall{grid-column:1/-1;text-align:start;margin:0}.metrics{grid-template-columns:1fr 1fr}.line{grid-template-columns:96px 1fr}
.list button{grid-template-columns:1fr 1fr;row-gap:2px}.metric .v{font-size:32px}.topbar{margin-bottom:var(--s-5)}.status-head,.status-grid{grid-template-columns:1fr}}
/* ---- language and direction (structural; the same design in both languages) */
.topnav{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.lang{padding:8px 16px;border-radius:var(--r-pill);border:1px solid var(--line-2);background:var(--surface);text-decoration:none;font-size:14px;color:var(--ink)}
.lang:hover{background:var(--surface-2)}
[dir=rtl] .flip{transform:scaleX(-1)}
[dir=rtl] .drawer{transform:translateX(calc(-100% - 24px))}
bdi,code{unicode-bidi:isolate}
:root[lang=ar]{--font:"Segoe UI","Noto Sans Arabic","Noto Naskh Arabic","Geeza Pro","Arabic UI Text","Tahoma",system-ui,sans-serif}
[lang=ar] body{line-height:1.75}
[lang=ar] .eyebrow,[lang=ar] .focus .col h3,[lang=ar] .drawer h4,[lang=ar] .hero .big small,[lang=ar] .metric .v small{letter-spacing:0;text-transform:none}
[lang=ar] h1,[lang=ar] h2,[lang=ar] h3,[lang=ar] .hero .big,[lang=ar] .metric .v,[lang=ar] .brand{letter-spacing:0}
[lang=ar] .hello h1,[lang=ar] .phead h1{line-height:1.3}[lang=ar] .focus h2{line-height:1.45}
[lang=ar] .line{grid-template-columns:132px 1fr}[lang=ar] .chip{white-space:normal}
@media (max-width:760px){[lang=ar] .line{grid-template-columns:112px 1fr}}
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
    var keep = e.target.closest('a[data-keep-hash]');
    if (keep) { keep.setAttribute('href', keep.getAttribute('href').split('#')[0] + location.hash); return; }
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
  if (hello) { var hr = new Date().getHours(); hello.textContent = hello.getAttribute(hr < 12 ? 'data-morning' : hr < 18 ? 'data-afternoon' : 'data-evening'); }
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
# Direction-bearing icons point the other way on RTL pages (the CSS mirrors them); the others are symmetric.
DIRECTIONAL = {"arrow", "back"}


def icon(name: str, size: int = 16) -> str:
    flip = ' class="flip"' if name in DIRECTIONAL else ""
    return (f'<svg{flip} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


# ---------------------------------------------------------------- formatting (presentation only)

def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _initials(name: str) -> str:
    words = [w for w in name.replace("(", " ").replace(")", " ").split() if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def _item(item_id: str, url: str | None, loc: Loc) -> str:
    text = loc.tech(item_id)
    return f'<a href="{escape(url.format(item_id=item_id))}" target="_blank" rel="noopener">{text}</a>' if url else text


def _attr(text: str) -> str:
    return escape(text, quote=True)


# ---------------------------------------------------------------- primitives

def avatar(name: str, size: str = "") -> str:
    return f'<span class="avatar {size}" aria-hidden="true"><bdi>{escape(_initials(name))}</bdi></span>'


def empty_state(title: str, detail: str = "") -> str:
    """``title`` and ``detail`` are already-rendered HTML (catalogue text)."""
    return f'<div class="empty"><b>{title}</b>{detail}</div>'


def info_button(text: str, drawer_id: str) -> str:
    return f'<button type="button" class="info above" data-drawer="{escape(drawer_id)}">{icon("info", 14)}{text}</button>'


def overall_placeholder(loc: Loc = EN) -> str:
    not_evaluated = loc.t("common.not_evaluated")
    return (f'<div class="overall" title="{_attr(loc.text("overall.aria"))}"><span>{loc.t("overall.label")}</span>'
            f'<b aria-label="{_attr(loc.text("overall.aria"))}">—</b><span>{not_evaluated}</span></div>')


def _overall(s: dict[str, Any], loc: Loc) -> str:
    """Contract 1.5 shows the real Overall Status (or the reason there is none); earlier contracts keep the placeholder."""
    return overall_badge(s["interpretation"], loc) if "interpretation" in s else overall_placeholder(loc)


def deadline_strip(d: dict[str, Any], large: bool = False, loc: Loc = EN) -> str:
    total = (d.get("early") or 0) + (d.get("on_time") or 0) + (d.get("late") or 0)
    if not total:
        return ""
    label = _attr(loc.text("deadline.strip_label", early=d["early"], on_time=d["on_time"], late=d["late"], total=total))
    parts = "".join(f'<i class="{cls}" style="flex:{n}"></i>' for cls, n in (("e", d["early"]), ("o", d["on_time"]), ("l", d["late"])) if n)
    return f'<div class="strip{" lg" if large else ""}" role="img" aria-label="{label}" title="{label}">{parts}</div>'


def deadline_counts(d: dict[str, Any], loc: Loc = EN) -> str:
    return f'<span>{loc.t("deadline.counts", early=_b(loc.num(d["early"])), on_time=_b(loc.num(d["on_time"])), late=_b(loc.num(d["late"])))}</span>'


def _b(fragment: str) -> Html:
    return Html(f"<b>{fragment}</b>")


def template(tid: str, title: str, content: str) -> str:
    """``title`` is plain text (shown by the drawer script with textContent)."""
    return f'<template id="{escape(tid)}" data-title="{_attr(title)}">{content}</template>'


def _dl(rows: Sequence[tuple[str, str]]) -> str:
    return "<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def _n_or_dash(value: Any, loc: Loc) -> Html:
    return loc.num(value) if value is not None else Html("—")


# ---------------------------------------------------------------- evidence drawer contents

def _project_tid(editor_id: str, item_id: str) -> str:
    return f"p-{editor_id}-{item_id}"


def project_evidence(editor_name: str, row: dict[str, Any], url: str | None, loc: Loc = EN) -> str:
    result = row["deadline_result"]
    if result:
        deadline = loc.t("evidence.deadline_result", result=loc.t(f"result.{result}"), delta=loc.hours(row["deadline_delta_seconds"], signed=True))
    else:
        issue = row["requested_eta_issue"]
        # A technical code with no catalogue entry is shown as the code itself (never as English prose).
        reason = (loc.t(f"eta_issue.{issue}") if loc.has(f"eta_issue.{issue}") else loc.tech(issue)) if issue else loc.t("common.not_classified")
        deadline = loc.t("evidence.deadline_unclassified", reason=reason)
    ids = row["evidence_event_ids"] or {}
    set_at = (f' <span class="quiet">{loc.t("evidence.eta_set_at", date=loc.date(row["requested_eta_observed_at"]))}</span>'
              if row.get("requested_eta_observed_at") else "")
    duration = loc.hours(row["duration_seconds"]) + ("" if row["speed_eligible"] else Html(" · " + loc.t("evidence.not_used_for_speed")))
    content = _dl([
        (loc.t("field.editor"), loc.src(editor_name)),
        (loc.t("field.monday_item"), _item(row["monday_item_id"], url, loc)),
        (loc.t("field.video_type"), loc.labels(row["cohort_labels"])),
        (loc.t("field.work_started"), escape(loc.date(row["in_progress_at"]))),
        (loc.t("field.ready_for_approval"), escape(loc.date(row["ready_for_approval_at"]))),
        (loc.t("field.work_duration"), duration),
        (loc.t("field.requested_eta"), escape(loc.date(row["requested_eta"])) + set_at),
        (loc.t("field.deadline"), deadline),
    ])
    ignored = row.get("requested_eta_changes_ignored_after_ready_for_approval") or 0
    notes = f'<p>{loc.count("noun.later_eta_change", ignored)}</p>' if ignored else ""
    labels = "".join(f'<span class="chip">{loc.src(label)}</span>' for label in row["quality_labels"]) or f'<span class="quiet">{loc.t("evidence.none_recorded")}</span>'
    evidence = "".join(f"<dt>{loc.t(f'event.{k}')}</dt><dd>{loc.tech(v)}</dd>" for k, v in ids.items() if v)
    status = (loc.comma().join(loc.tech(reason) for reason in row["exclusions"]) if row["exclusions"] else loc.t("evidence.included"))
    return (content + notes
            + f'<h4>{loc.t("evidence.issues_heading")}</h4><div class="chips">{labels}</div>'
            + f'<h4>{loc.t("revisions.context_heading")}</h4><p>{loc.t("evidence.revision_context", events=loc.count("noun.client_revision_event", row["client_revision_events"]))}</p>'
            + f'<h4>{loc.t("evidence.metric_status")}</h4><p>{status}</p>'
            + (f'<p class="tiny quiet">{loc.t("evidence.flags", flags=Html(loc.comma().join(loc.tech(f) for f in row["flags"])))}</p>' if row["flags"] else "")
            + f"<h4>{loc.t('evidence.monday_events')}</h4><dl>{evidence}</dl>")


def _project_templates(s: dict[str, Any], url: str | None, loc: Loc) -> str:
    return "".join(template(_project_tid(s["editor_id"], row["monday_item_id"]), loc.text("evidence.project_title", item=row["monday_item_id"]),
                            project_evidence(s["display_name"], row, url, loc)) for row in s["projects"])


def _project_list(s: dict[str, Any], item_ids: list[str] | None = None, loc: Loc = EN) -> str:
    rows = [row for row in s["projects"] if item_ids is None or row["monday_item_id"] in set(item_ids)]
    if not rows:
        return f'<p class="quiet">{loc.t("evidence.no_projects")}</p>'
    out = []
    for row in rows:
        result = row["deadline_result"]
        deadline = (f'<span class="res-{result}">{loc.t(f"result.{result}")} {loc.hours(row["deadline_delta_seconds"], signed=True)}</span>' if result
                    else f'<span class="quiet">{loc.t("common.not_classified_lower")}</span>')
        out.append(f'<button type="button" data-drawer="{escape(_project_tid(s["editor_id"], row["monday_item_id"]))}">'
                   f'<span>{escape(loc.date(row["ready_for_approval_at"], False))}</span><span>{loc.labels(row["cohort_labels"])}</span>'
                   f'<span>{deadline}</span><span class="soft">{loc.comma().join(loc.src(label) for label in row["quality_labels"])}</span>'
                   f'<span class="quiet">{loc.hours(row["duration_seconds"])}</span></button>')
    return f'<div class="list">{"".join(out)}</div>'


# ---------------------------------------------------------------- Editor card (CEO home)

def _hero(s: dict[str, Any], loc: Loc = EN) -> tuple[str, str]:
    """Headline block for the card and which section it shows (fixed display order, see module docstring)."""
    speed, deadline = s["speed"], s["deadline"]
    if speed["compared_cohorts"]:
        c = speed["compared_cohorts"][0]
        labels = loc.labels(c["labels"])
        if c["conclusion"] == "equal_to_team_median":
            big = loc.t("hero.level_big", big=loc.t("hero.level"), small=Html(f"<small>{loc.t('hero.level_small')}</small>"))
        else:
            word = Html(f"<small>{loc.t('hero.word.' + SPEED_WORD[c['conclusion']])}</small>")
            big = loc.t("hero.speed_big", pct=loc.pct_value(abs(c["editor_vs_team_median_pct"] or 0)), word=word)
        team_n = c["team_sample_size"]
        sample = loc.t("hero.sample", e=loc.num(c["editor_sample_size"]), t=_n_or_dash(team_n, loc), name=loc.src(s["display_name"]),
                       e_projects=loc.count("noun.project", c["editor_sample_size"]),
                       t_projects=loc.count("noun.project", team_n) if team_n is not None else Html("—"),
                       editors=loc.count("noun.editor", c["team_editor_count"] or 0), labels=labels)
        return ("speed", (f'<div class="hero"><span class="eyebrow">{icon("speed", 13)} {loc.t("hero.speed_eyebrow", labels=labels)}</span>'
                f'<div class="big">{big}</div>'
                f'<div class="pair"><div><b>{loc.hours(c["editor_median_seconds"])}</b><span>{loc.t("hero.editor_median", name=loc.src(s["display_name"]))}</span></div>'
                f'<div><b>{loc.hours(c["team_median_seconds"])}</b><span>{loc.t("common.team_median")}</span></div></div>'
                f'<span class="tiny quiet">{sample}</span></div>'))
    if deadline["evaluated"]:
        return ("deadline", (f'<div class="hero"><span class="eyebrow">{icon("clock", 13)} {loc.t("common.deadlines")}</span>{deadline_strip(deadline, True, loc)}'
                f'<div style="font-size:17px">{deadline_counts(deadline, loc)}</div><span class="tiny quiet">'
                f'{loc.count("noun.classified_delivery", deadline["evaluated"])}</span></div>'))
    completed = s["sample"]["completed_projects"]
    return ("projects", (f'<div class="hero"><span class="eyebrow">{icon("layers", 13)} {loc.t("common.projects")}</span><div class="big">{loc.num(completed)}'
            f'<small>{loc.plural("hero.completed_small", completed)}</small></div></div>'))


def _speed_line(s: dict[str, Any], loc: Loc = EN) -> str:
    speed = s["speed"]
    compared = speed["compared_cohorts"]
    others = len(speed["cohorts"]) - len(compared)
    more = []
    if len(compared) > 1:
        more.append(loc.t("speed.more_comparable", n=loc.num(len(compared) - 1)))
    if others:
        more.append(loc.t("speed.more_not_comparable", n=loc.num(others)))
    link = info_button(" · ".join(more), f"speed-{s['editor_id']}") if more else ""
    if not compared:
        return f'<span class="soft">{loc.t("speed.none_comparable")}</span> ' + info_button(loc.t("common.why"), f"speed-{s['editor_id']}")
    c = compared[0]
    head = loc.t("speed.line", labels=loc.labels(c["labels"]), editor=loc.hours(c["editor_median_seconds"]), team=loc.hours(c["team_median_seconds"]))
    return f"{head} {link}"


def _unclassified(d: dict[str, Any]) -> int:
    return (d.get("not_classifiable_insufficient_eta_precision") or 0) + (d.get("not_classifiable_missing_eta") or 0)


def _deadline_line(s: dict[str, Any], loc: Loc = EN) -> str:
    d = s["deadline"]
    unclassified = _unclassified(d)
    note = info_button(loc.count("noun.unclassified_project", unclassified), f"dq-{s['editor_id']}") if unclassified else ""
    if not d["evaluated"]:
        return f'<span class="soft">{loc.t("deadline.unavailable")}</span> ' + info_button(loc.t("common.why"), f"dq-{s['editor_id']}")
    return (f'{deadline_strip(d, False, loc)}<div class="small">{deadline_counts(d, loc)} '
            f'<span class="quiet">{loc.t("deadline.of_total", n=loc.num(d["evaluated"]))}</span> {note}</div>')


def _issue_line(s: dict[str, Any], loc: Loc = EN) -> str:
    q = s["quality"]
    if not q["total_occurrences"]:
        return f'<span class="soft">{loc.t("quality.none_recorded")}</span>'
    chips = "".join(f'<span class="chip">{loc.src(row["label"])} <b>{loc.t("common.times", n=loc.num(row["occurrences"]))}</b></span>' for row in q["by_label"][:3])
    extra = f'<span class="chip">+{loc.num(len(q["by_label"]) - 3)}</span>' if len(q["by_label"]) > 3 else ""
    summary = loc.t("issue.summary", signals=_b(loc.count("noun.issue_signal", q["total_occurrences"])),
                    projects=loc.count("noun.project", q["projects_with_issues"], case="gen"))
    return f'<div class="small">{summary}</div><div class="chips" style="margin-top:6px">{chips}{extra}</div>'


def workload_chips(w: dict[str, Any], limit: int | None = None, loc: Loc = EN) -> str:
    items = list(w["by_current_status"].items())
    if not items and not w.get("awaiting_approval_count"):
        return f'<span class="soft">{loc.t("workload.none")}</span>'
    shown = items[:limit] if limit else items
    chips = "".join(f'<span class="chip{" context" if "revision" in status.lower() else ""}"><b>{loc.num(n)}</b> {loc.src(status)}</span>' for status, n in shown)
    rest = len(items) - len(shown)
    awaiting = (f'<span class="chip context"><b>{loc.num(w["awaiting_approval_count"])}</b> {loc.t("workload.awaiting_approval")}</span>'
                if w.get("awaiting_approval_count") else "")
    return f'<div class="chips">{chips}{awaiting}{f"<span class=chip>+{loc.num(rest)}</span>" if rest > 0 else ""}</div>'


def editor_card(s: dict[str, Any], loc: Loc = EN) -> str:
    kind, hero = _hero(s, loc)
    lines = []
    if kind != "speed":
        lines.append(("speed", loc.t("common.speed"), _speed_line(s, loc)))
    else:
        more = _speed_line(s, loc)
        if "info" in more:
            lines.append(("speed", loc.t("common.speed"), more))
    if kind != "deadline":
        lines.append(("clock", loc.t("common.deadlines"), _deadline_line(s, loc)))
    lines.append(("alert", loc.t("common.issue_signals"), _issue_line(s, loc)))
    positive_count = (s["quality"].get("positive") or {}).get("total_occurrences", 0)
    positive = (f'<span class="small">{loc.num(positive_count)} · {loc.t("quality.positive_title")}</span>' if positive_count
                else f'<span class="quiet">— {loc.t("common.no_signal")}</span>')
    lines.append(("spark", loc.t("card.positive"), positive))
    lines.append(("stack", loc.t("common.current_work"), workload_chips(s["current_workload"], 3, loc)))
    body = "".join(f'<div class="line"><span class="k">{icon(ic, 13)}{k}</span><div>{v}</div></div>' for ic, k, v in lines)
    completed = loc.count("noun.completed_project", s["sample"]["completed_projects"])
    scope = ""
    if "interpretation" in s:
        # Contract 1.5: the project count covers all history; every line below it is the current Cairo window (D24, D42).
        completed = Html(f'{completed} · {loc.t("interp.all_history")}')
        scope = f'<p class="tiny quiet" data-scope="current-window">{window_caption(s["interpretation"], loc)}</p>'
    return (f'<article class="card ed" aria-label="{_attr(s["display_name"])}">'
            f'<div class="who">{avatar(s["display_name"])}<div><h3>{loc.src(s["display_name"])}</h3>'
            f'<span class="small quiet">{completed}</span></div>{_overall(s, loc)}</div>'
            f'{scope}{hero}{body}'
            f'<a class="cta stretch" href="#/editor/{escape(s["editor_id"])}">{loc.t("card.view_profile")} {icon("arrow", 15)}</a></article>')


# ---------------------------------------------------------------- timelines (Team Pulse and Editor Performance Timeline)

def _event_month(event: dict[str, Any]) -> str:
    return str(event["at"])[:7]


def _position(at: str, month: str) -> float:
    moment = _dt(at)
    assert moment is not None
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    return ((moment.day - 1) + (moment.hour * 3600 + moment.minute * 60 + moment.second) / 86400) / days * 100


def _marker_class(event: dict[str, Any], loc: Loc = EN) -> tuple[str, str]:
    """Marker style and its plain-text label (for aria-label/title)."""
    if event["kind"] == "issue_label":
        return "issue", loc.text("timeline.issue_marker", label=event["label"])
    if event["kind"] == "positive_label":
        return "early", str(event["label"])
    if event["kind"] == "context_label":
        return "unclassified", str(event["label"])
    result = event["deadline_result"]
    if result:
        return result, loc.text(f"timeline.delivery.{result}")
    return "unclassified", loc.text("timeline.delivery.unclassified")


def _event_tid(editor_id: str, index: int) -> str:
    return f"e-{editor_id}-{index}"


def _event_templates(s: dict[str, Any], loc: Loc) -> str:
    """Drawer content for quality-label events (deliveries open their project's evidence)."""
    out = []
    for index, event in enumerate(s["events"]):
        if not event["kind"].endswith("_label"):
            continue
        ids = "".join(f"<dd>{loc.tech(v)}</dd>" for v in event["event_ids"])
        out.append(template(_event_tid(s["editor_id"], index), event["label"], _dl([
            (loc.t("field.editor"), loc.src(s["display_name"])), (loc.t("field.label_added"), escape(loc.date(event["at"]))),
            (loc.t("field.monday_item"), loc.tech(event["monday_item_id"])),
            (loc.t("field.source"), loc.tech(event["column_id"]) if "column_id" in event else loc.t("quality.source_column"))])
            + f"<h4>{loc.t('evidence.monday_events')}</h4><dl><dt>{loc.t('common.evidence')}</dt>{ids}</dl>"
            + f'<p><button type="button" class="ghost" data-drawer="{escape(_project_tid(s["editor_id"], event["monday_item_id"]))}">{loc.t("evidence.open_project")}</button></p>'))
    return "".join(out)


def _lane(s: dict[str, Any], month: str, retrieved: str | None, show_name: bool, loc: Loc = EN) -> str:
    markers: list[str] = []
    rows_last: dict[int, float] = {}
    events = [(i, e) for i, e in enumerate(s["events"]) if _event_month(e) == month]
    for index, event in events:
        pos = _position(event["at"], month)
        row = 0
        while row in rows_last and pos - rows_last[row] < 1.3:
            row += 1
        rows_last[row] = pos
        cls, label = _marker_class(event, loc)
        tid = _project_tid(s["editor_id"], event["monday_item_id"]) if event["kind"] == "delivery" else _event_tid(s["editor_id"], index)
        aria = loc.text("timeline.marker_aria", name=s["display_name"], label=label, date=loc.date(event["at"]), item=event["monday_item_id"])
        markers.append(f'<button type="button" class="mk {cls}" style="left:{pos:.2f}%;top:{14 + row * 16}px" data-drawer="{escape(tid)}" '
                       f'aria-label="{_attr(aria)}" title="{_attr(aria)}"><i></i></button>')
    height = 28 + (max(rows_last) + 1 if rows_last else 1) * 16
    now = f'<span class="now" style="left:{_position(retrieved, month):.2f}%"></span>' if retrieved and retrieved[:7] == month else ""
    name = (f'<div class="ln">{avatar(s["display_name"])}<span>{loc.src(s["display_name"])}</span></div>' if show_name
            else f'<div class="ln"><span class="quiet small">{loc.t("timeline.events")}</span></div>')
    empty = '' if markers else f'<span class="tiny quiet" style="position:absolute;left:8px;top:10px">{loc.t("timeline.no_events_month")}</span>'
    return f'<div class="lane">{name}<div class="track" style="height:{height}px">{now}{empty}{"".join(markers)}</div></div>'


def _axis(month: str, retrieved: str | None, loc: Loc = EN) -> str:
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    label = loc.month_short(month)
    ticks = "".join(f'<span style="left:{(day - 1) / days * 100:.2f}%">{loc.t("timeline.tick", month=label, day=f"{day:02d}")}</span>'
                    for day in (1, 8, 15, 22) if day <= days)
    if retrieved and retrieved[:7] == month:
        ticks += f'<span class="today" style="left:{_position(retrieved, month):.2f}%">{loc.t("timeline.updated")}</span>'
    return f'<div class="axis">{ticks}</div>'


def legend(loc: Loc = EN) -> str:
    items = [("early", "result.early"), ("on_time", "result.on_time"), ("late", "result.late"), ("unclassified", "common.not_classified"),
             ("issue", "timeline.legend_issue")]
    keys = "".join(f'<span><span class="mk {cls}"><i></i></span> {loc.t(key)}</span>' for cls, key in items)
    return f'<div class="legend">{keys}<span>{loc.t("timeline.legend_note")}</span><span>{loc.t("timeline.direction_note")}</span></div>'


def timeline(summaries: list[dict[str, Any]], retrieved: str | None, prefix: str, show_names: bool = True, loc: Loc = EN) -> str:
    months = sorted({_event_month(e) for s in summaries for e in s["events"]}, reverse=True)
    if not months:
        return empty_state(loc.t("timeline.no_events"))
    pills = "".join(f'<button type="button" class="pill" role="tab" data-pill="{prefix}-{m}" aria-selected="{"true" if i == 0 else "false"}">'
                    f'{escape(loc.month(m))}</button>' for i, m in enumerate(months))
    # The time axis is always left (earlier) to right (later), whatever the page direction.
    panels = "".join(f'<div id="{prefix}-{m}" role="tabpanel" {"" if i == 0 else "hidden"}><div class="tl" dir="ltr"><div class="tl-inner">{_axis(m, retrieved, loc)}'
                     f'{"".join(_lane(s, m, retrieved, show_names, loc) for s in summaries)}</div></div></div>' for i, m in enumerate(months))
    return f'<div class="pills" role="tablist" data-pills style="margin-bottom:12px">{pills}</div>{panels}{legend(loc)}'


# ---------------------------------------------------------------- CEO home sections

AVAILABLE_NOW = ("focus.available.speed", "focus.available.deadlines", "focus.available.issues", "focus.available.current_work", "focus.available.history")
CALIBRATING = ("focus.calibrating.attention", "focus.calibrating.recognition", "focus.calibrating.trends", "focus.calibrating.patterns",
               "focus.calibrating.overall")


def management_focus(doc: dict[str, Any], loc: Loc = EN) -> str:
    n = len(doc["editors"])
    return (f'<section class="focus" aria-labelledby="focus-h"><div><span class="eyebrow"><i></i>{loc.t("focus.eyebrow")}</span>'
            f'<h2 id="focus-h">{loc.t("focus.title")}</h2><p>{loc.count("focus.body", n)}</p></div>'
            f'<div><div class="col"><h3>{loc.t("focus.available")}</h3>' + "".join(f'<span class="fchip">{loc.t(k)}</span>' for k in AVAILABLE_NOW) + '</div>'
            f'<div class="col"><h3>{loc.t("focus.calibrating")}</h3>' + "".join(f'<span class="fchip cal">{loc.t(k)}</span>' for k in CALIBRATING) + '</div>'
            f'<div class="col"><a href="#/system">{loc.t("focus.how_atlas_evaluates")}</a></div></div></section>')


def issue_activity(doc: dict[str, Any], month: str | None, loc: Loc = EN) -> str:
    counts: dict[str, Counter[str]] = {}
    for s in doc["editors"]:
        for event in s["events"]:
            if event["kind"] == "issue_label" and month and _event_month(event) == month:
                counts.setdefault(event["label"], Counter())[s["display_name"]] += 1
    rows = "".join(f'<div><span>{loc.src(label)}</span><span class="chips">'
                   + "".join(f'<span class="chip">{loc.src(name)} <b>{loc.t("common.times", n=loc.num(n))}</b></span>'
                             for name, n in sorted(c.items(), key=lambda p: (-p[1], p[0])))
                   + "</span></div>" for label, c in sorted(counts.items(), key=lambda p: (-sum(p[1].values()), p[0])))
    body = (f'<div class="rowlist">{rows}</div>' if rows
            else empty_state(loc.t("activity.empty_title"), " " + loc.t("activity.empty_detail")))
    period = escape(loc.month(month)) if month else loc.t("activity.this_period")
    return (f'<div class="card"><h3>{icon("alert")}{loc.t("activity.title")}</h3><p class="sub">{loc.t("activity.sub", period=Html(period))}</p>{body}'
            f'<p class="tiny quiet" style="margin-top:14px">{loc.t("activity.footer")}</p></div>')


def patterns_card(loc: Loc = EN) -> str:
    return (f'<div class="card"><h3>{icon("layers")}{loc.t("patterns.title")}</h3><p class="sub">{loc.t("patterns.sub")}</p>'
            + empty_state(loc.t("patterns.empty_title"), " " + loc.t("patterns.empty_detail"))
            + "</div>")


def workload_card(doc: dict[str, Any], loc: Loc = EN) -> str:
    rows = "".join(f'<div><span>{loc.src(s["display_name"])}</span>{workload_chips(s["current_workload"], None, loc)}</div>' for s in doc["editors"])
    return (f'<div class="card"><h3>{icon("stack")}{loc.t("common.current_work")}</h3><p class="sub">{loc.t("workload.sub")}</p><div class="rowlist">{rows}</div>'
            f'<p class="tiny quiet" style="margin-top:14px">{loc.t("workload.footer")}</p></div>')


def history(doc: dict[str, Any], loc: Loc = EN) -> str:
    months = sorted({m["month"] for s in doc["editors"] for m in s["monthly"]})
    if not months:
        return empty_state(loc.t("history.empty"))
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
        label = loc.month_short(m) + ("" if m[:4] == last[:4] else f" {m[:4]}")
        disabled = "" if has else f' disabled title="{_attr(loc.text("history.no_data"))}"'
        pills.append(f'<button type="button" class="pill" role="tab" data-pill="hist-{m}" aria-selected="{"true" if selected else "false"}"'
                     f'{disabled}>{escape(label)}</button>')
        if not has:
            continue
        rows = []
        for s in doc["editors"]:
            entry = next((x for x in s["monthly"] if x["month"] == m), None)
            if not entry:
                rows.append(f'<div class="row"><div class="who">{avatar(s["display_name"])}<span>{loc.src(s["display_name"])}</span></div>'
                            f'<div class="quiet">{loc.t("history.no_figures")}</div><div></div></div>')
                continue
            d = entry["deadline"]
            dl = (f'{deadline_strip(d, False, loc)}<div class="small">{deadline_counts(d, loc)} <span class="quiet">'
                  f'{loc.t("history.late_of", late=loc.num(d["late"]), n=loc.num(d["evaluated"]))}</span></div>'
                  if d else f'<span class="quiet">{loc.t("history.no_deadlines")}</span>')
            sp = "<br>".join(f'{loc.labels(c["labels"], c["cohort_key"])} <b>{loc.hours(c["median_seconds"])}</b> <span class="quiet">{loc.t("common.sample_n", n=loc.num(c["projects"]))}</span>'
                             for c in sorted(entry["speed_by_cohort"], key=lambda c: -c["projects"])[:4]) or '<span class="quiet">—</span>'
            more = len(entry["speed_by_cohort"]) - 4
            more_html = f'<br><span class="quiet">{loc.t("common.more", n=loc.num(more))}</span>' if more > 0 else ""
            rows.append(f'<div class="row"><div class="who">{avatar(s["display_name"])}<span>{loc.src(s["display_name"])}</span></div><div>{dl}</div>'
                        f'<div class="small"><span class="tiny quiet">{loc.t("history.median_duration")}</span><br>{sp}{more_html}</div></div>')
        partial = next((x["partial"] for s in doc["editors"] for x in s["monthly"] if x["month"] == m), False)
        panels.append(f'<div id="hist-{m}" role="tabpanel" {"" if selected else "hidden"}><p class="small quiet" style="margin:0 0 4px">{escape(loc.month(m))}'
                      f'{" · " + loc.t("common.month_in_progress") if partial else ""}</p><div class="hist">{"".join(rows)}</div></div>')
    return (f'<div class="pills" role="tablist" data-pills style="margin-bottom:12px">{"".join(pills)}</div><div class="card">{"".join(panels)}'
            f'<p class="tiny quiet" style="margin:14px 0 0">{loc.t("history.footer")}</p></div>')


# ---------------------------------------------------------------- drawers shared by home and profile

def _verdict(c: dict[str, Any], loc: Loc) -> Html:
    """The comparison stated as a relation to the team median in one Video Type (never a claim about the person)."""
    conclusion = c["conclusion"]
    if conclusion == "equal_to_team_median":
        return loc.t("speed.verdict.level")
    if conclusion in SPEED_WORD:
        return loc.t(f"speed.verdict.{SPEED_WORD[conclusion]}", pct=loc.pct_value(abs(c["editor_vs_team_median_pct"] or 0)))
    return loc.t("conclusion.not_comparable")


def _status(code: str, loc: Loc) -> Html:
    return loc.t(f"status.{code}")


def _speed_drawer(s: dict[str, Any], loc: Loc = EN) -> str:
    speed = s["speed"]
    rows = []
    for c in speed["cohorts"]:
        team = (loc.t("speed.team_value", median=loc.hours(c["team_median_seconds"]), n=_n_or_dash(c["team_sample_size"], loc))
                + (Html(" · " + loc.count("noun.editor", c["team_editor_count"])) if c["team_editor_count"] else ""))
        rows.append(f'<h4>{loc.labels(c["labels"])}</h4>' + _dl([
            (loc.t("common.editor_median"), loc.t("speed.editor_value", median=loc.hours(c["editor_median_seconds"]), n=loc.num(c["editor_sample_size"]))),
            (loc.t("common.team_median"), team),
            (loc.t("common.result"), _verdict(c, loc)), (loc.t("common.why"), _status(c["comparison_status"], loc))]))
    minimum = speed.get("minimum_editor_sample_size")
    intro_text = (loc.t("common.not_evaluated") if minimum is None
                  else loc.t("speed.drawer_intro", stat=loc.t("stat." + speed["benchmark_statistic"]),
                             min=loc.num(minimum), min_projects=loc.count("noun.project", minimum)))
    intro = f"<p>{intro_text}</p>"
    return template(f"speed-{s['editor_id']}", loc.text("speed.drawer_title", name=s["display_name"]),
                    intro + ("".join(rows) or f'<p class="quiet">{loc.t("speed.no_measurable")}</p>'))


def warning_text(w: dict[str, Any], loc: Loc = EN) -> Html:
    """A data-confidence note, rendered from its code and parameters (the view model's English ``text`` is not reused)."""
    p = w.get("params") or {}
    code = w["code"]
    if code == "SMALL_SAMPLE":
        return loc.t("warning.small_sample", n=loc.num(p["completed_projects"]), completed=loc.count("noun.completed_project", p["completed_projects"]),
                     min=loc.num(p["minimum"]))
    if code == "NO_SPEED_COMPARISON":
        return loc.t("warning.no_speed_comparison")
    if code == "DEADLINE_NOT_CLASSIFIABLE":
        return loc.t("warning.deadline_not_classifiable", n=loc.num(p["unclassified"]), completed=loc.count("noun.completed_project", p["unclassified"]))
    if code == "PROJECTS_EXCLUDED":
        reasons = Html(loc.comma().join(f"{loc.tech(r)} {loc.num(n)}" for r, n in p["reasons"].items()))
        return loc.t("warning.projects_excluded", n=loc.num(p["excluded"]), projects=loc.count("noun.project", p["excluded"]), reasons=reasons)
    if code == "PARTIAL_MONTH":
        return loc.t("warning.partial_month", month=loc.month(p["month"]), retrieved=loc.date(p["retrieved_at"]))
    return loc.tech(code)   # a code with no rendering is shown as the code itself, never as the English text


def _dq_drawer(s: dict[str, Any], loc: Loc = EN) -> str:
    d = s["deadline"]
    rows = _dl([(loc.t("deadline.classified"), loc.num(d["evaluated"])),
                (loc.t("deadline.eta_without_time"), loc.num(d.get("not_classifiable_insufficient_eta_precision") or 0)),
                (loc.t("deadline.no_eta"), loc.num(d.get("not_classifiable_missing_eta") or 0)),
                (loc.t("deadline.other_reasons"), loc.num(d.get("not_evaluated_other") or 0))])
    notes = "".join(f"<li>{warning_text(w, loc)}</li>" for w in s["warnings"])
    return template(f"dq-{s['editor_id']}", loc.text("deadline.drawer_title", name=s["display_name"]),
                    f'<p>{loc.t("deadline.drawer_intro")}</p>' + rows + (f"<h4>{loc.t('deadline.data_notes')}</h4><ul>{notes}</ul>" if notes else ""))


# ---------------------------------------------------------------- Editor Profile

def _metric_cards(s: dict[str, Any], loc: Loc = EN) -> str:
    q, d, sample = s["quality"], s["deadline"], s["sample"]
    eid = s["editor_id"]
    compared = s["speed"]["compared_cohorts"]
    if compared:
        c = compared[0]
        word = SPEED_WORD[c["conclusion"]]
        key = "metric.speed_level" if word == "level" else f"metric.speed_{word}"
        relation = loc.t(key, pct=loc.pct_value(abs(c["editor_vs_team_median_pct"] or 0)), team=loc.hours(c["team_median_seconds"]),
                         n=loc.num(c["editor_sample_size"]), projects=loc.count("noun.project", c["editor_sample_size"]))
        speed = (f'<div class="v">{loc.hours(c["editor_median_seconds"])}</div><div class="small">{loc.t("metric.speed_median", labels=loc.labels(c["labels"]))}</div>'
                 f'<div class="small quiet">{relation}</div>')
    else:
        speed = f'<div class="v" style="font-size:24px;margin-top:10px">—</div><div class="small soft">{loc.t("speed.none_comparable")}</div>'
    deadline = (f'{deadline_strip(d, True, loc)}<div class="small">{deadline_counts(d, loc)}</div><div class="small quiet">{loc.count("noun.classified_project", d["evaluated"])}</div>'
                if d["evaluated"] else f'<div class="v" style="font-size:24px;margin-top:10px">—</div><div class="small soft">{loc.t("deadline.unavailable")}</div>')
    issues = (f'<div class="v">{loc.num(q["total_occurrences"])}</div><div class="small quiet">'
              f'{loc.t("metric.issues_across", projects=loc.count("noun.project", q["projects_with_issues"], case="gen"), total=loc.num(q["completed_projects_attributed"]))}</div>'
              if q["total_occurrences"] else f'<div class="v">{loc.num(0)}</div><div class="small soft">{loc.t("quality.none_recorded")}</div>')
    projects = (f'<div class="v">{loc.num(sample["completed_projects"])}</div><div class="small quiet">'
                f'{loc.t("metric.projects_detail", measurable=loc.num(sample["speed_eligible_projects"]))}</div>')
    cards = [("alert", loc.t("common.issue_signals"), issues, f"quality-{eid}"), ("speed", loc.t("focus.available.speed"), speed, f"speed-{eid}"),
             ("clock", loc.t("common.deadlines"), deadline, f"dq-{eid}"), ("layers", loc.t("common.projects"), projects, f"cov-{eid}")]
    return '<div class="metrics">' + "".join(
        f'<button type="button" class="card metric" data-drawer="{tid}"><span class="eyebrow" style="display:flex;gap:6px;align-items:center">{icon(ic, 13)}{k}</span>{v}</button>'
        for ic, k, v, tid in cards) + "</div>"


def _quality_drawer(s: dict[str, Any], loc: Loc = EN) -> str:
    q = s["quality"]
    rows = "".join(f'<h4>{loc.src(row["label"])} · {loc.num(row["occurrences"])}</h4>{_project_list(s, row["monday_item_ids"], loc)}' for row in q["by_label"])
    return template(f"quality-{s['editor_id']}", loc.text("quality.drawer_title", name=s["display_name"]),
                    f'<p>{loc.t("quality.intro")}</p>'
                    + (rows or f'<p class="quiet">{loc.t("quality.none_recorded_sentence")} {loc.t("quality.not_an_assessment")}</p>'))


def _coverage_drawer(s: dict[str, Any], loc: Loc = EN) -> str:
    sample = s["sample"]
    reasons = "".join(f"<li>{loc.tech(r)} {loc.num(n)}</li>" for r, n in sample["exclusions_by_reason"].items()) or f"<li>{loc.t('common.none')}</li>"
    return template(f"cov-{s['editor_id']}", loc.text("coverage.drawer_title", name=s["display_name"]),
                    _dl([(loc.t("coverage.completed"), loc.num(sample["completed_projects"])), (loc.t("coverage.open"), loc.num(sample["open_projects"])),
                         (loc.t("coverage.measurable"), loc.num(sample["speed_eligible_projects"]))])
                    + f"<h4>{loc.t('coverage.excluded')}</h4><ul>{reasons}</ul><h4>{loc.t('coverage.all_projects')}</h4>{_project_list(s, None, loc)}")


def _typical_range(c: dict[str, Any], loc: Loc) -> Html:
    rng = c.get("team_typical_range_seconds")
    if not rng:
        return Html("—")
    return Html(f'{loc.hours(rng.get("p25"))} – {loc.hours(rng.get("p75"))}')


def _cohort_drawers(s: dict[str, Any], loc: Loc = EN) -> str:
    return "".join(template(f"c-{s['editor_id']}-{c['cohort_key']}", " + ".join(c["labels"]) or "—", _dl([
        (loc.t("common.editor_median"), loc.t("speed.editor_value", median=loc.hours(c["editor_median_seconds"]), n=loc.num(c["editor_sample_size"]))),
        (loc.t("common.team_median"), loc.hours(c["team_median_seconds"])),
        (loc.t("speed.typical_range"), _typical_range(c, loc)),
        (loc.t("common.status"), _status(c["comparison_status"], loc))])
        + f'<p class="tiny quiet">{loc.t("speed.benchmark_is_descriptive")}</p>'
        + f"<h4>{loc.t('common.projects')}</h4>" + _project_list(s, c["editor_project_ids"], loc))
        for c in s["speed"]["cohorts"])


def _speed_panel(s: dict[str, Any], loc: Loc = EN) -> str:
    out = []
    for c in s["speed"]["cohorts"]:
        compared = c["conclusion"] in SPEED_WORD
        if compared and c["conclusion"] != "equal_to_team_median":
            strong = _b(loc.t(f"speed.panel.{SPEED_WORD[c['conclusion']]}", pct=loc.pct_value(abs(c["editor_vs_team_median_pct"] or 0))))
            verdict = loc.t("speed.panel.than", strong=strong)
        elif compared:
            verdict = loc.t("speed.panel.level", strong=_b(loc.t("hero.level")))
        else:
            verdict = Html(f'<span class="soft">{loc.t("conclusion.not_comparable")}</span> · <span class="quiet">{_status(c["comparison_status"], loc)}</span>')
        sample = loc.t("speed.panel.sample", e=loc.num(c["editor_sample_size"]), t=_n_or_dash(c["team_sample_size"], loc),
                       e_projects=loc.count("noun.project", c["editor_sample_size"]),
                       t_projects=loc.count("noun.project", c["team_sample_size"]) if c["team_sample_size"] is not None else Html("—"))
        out.append(f'<button type="button" class="card cohort{" cmp" if compared else ""}" data-drawer="c-{escape(s["editor_id"])}-{escape(c["cohort_key"])}">'
                   f'<span style="font-size:16px">{loc.labels(c["labels"])}</span><div class="nums"><div><b>{loc.hours(c["editor_median_seconds"])}</b><span>{loc.t("common.editor")}</span></div>'
                   f'<div><b>{loc.hours(c["team_median_seconds"])}</b><span>{loc.t("common.team")}</span></div></div><div class="small">{verdict}</div>'
                   f'<span class="tiny quiet">{sample}</span></button>')
    body = f'<div class="cohorts">{"".join(out)}</div>' if out else empty_state(loc.t("speed.no_measurable_title"))
    return (f'<div class="sh"><div><h2>{loc.t("speed.panel.title")}</h2><p>{loc.t("speed.panel.sub")}</p></div>'
            + info_button(loc.t("speed.how_compared"), f"speed-{s['editor_id']}") + f'</div>{body}')


def _deadline_panel(s: dict[str, Any], loc: Loc = EN) -> str:
    d = s["deadline"]
    unclassified = _unclassified(d)
    if d["evaluated"]:
        extra = Html(" · " + loc.count("noun.unclassified_project", unclassified)) if unclassified else ""
        top = (f'<div class="card">{deadline_strip(d, True, loc)}<div style="font-size:20px">{deadline_counts(d, loc)}</div>'
               f'<p class="small quiet" style="margin:6px 0 0">{loc.t("deadline.panel_summary", classified=loc.count("noun.classified_project", d["evaluated"]), margin=loc.hours(d.get("median_delta_seconds"), signed=True), unclassified=extra)}</p>'
               f'<p class="tiny quiet" style="margin:4px 0 0">{loc.t("deadline.negative_note")}</p>'
               f'<p class="tiny quiet" style="margin:14px 0 0"><span class="key e"></span>{loc.t("result.early")} <span class="key o" style="margin-inline-start:10px"></span>{loc.t("result.on_time")} '
               f'<span class="key l" style="margin-inline-start:10px"></span>{loc.t("result.late")}</p></div>')
    else:
        top = f'<div class="card">{empty_state(loc.t("deadline.unavailable"), " " + loc.t("deadline.unavailable_detail"))}</div>'
    months = "".join(f'<div class="row"><div>{escape(loc.month(m["month"]))}{" <span class=quiet>· " + loc.t("common.month_in_progress") + "</span>" if m["partial"] else ""}</div>'
                     f'<div>{deadline_strip(m["deadline"], False, loc)}<div class="small">{deadline_counts(m["deadline"], loc)} <span class="quiet">{loc.t("deadline.of_total", n=loc.num(m["deadline"]["evaluated"]))}</span></div></div>'
                     f'<div class="small quiet">{loc.t("deadline.late_rate", pct=loc.pct(m["deadline"]["late_rate"]))}</div></div>' for m in s["monthly"] if m["deadline"])
    groups = "".join(f'<button type="button" class="ghost" data-drawer="dl-{escape(s["editor_id"])}-{r}">{loc.t(f"deadline.group.{r}")}</button> '
                     for r in RESULTS if d.get(r))
    return (f'<div class="sh"><div><h2>{loc.t("deadline.panel_title")}</h2><p>{loc.t("deadline.panel_sub")}</p></div>'
            + info_button(loc.t("deadline.coverage_button"), f"dq-{s['editor_id']}") + f'</div>{top}'
            f'<div style="margin-top:12px">{groups}</div>'
            + (f'<div class="card hist" style="margin-top:16px"><p class="eyebrow" style="margin:0">{loc.t("common.by_month")}</p>{months}</div>' if months else ""))


def _deadline_group_drawers(s: dict[str, Any], loc: Loc = EN) -> str:
    return "".join(template(f"dl-{s['editor_id']}-{r}", loc.text(f"deadline.group_title.{r}", name=s["display_name"]),
                            _project_list(s, [row["monday_item_id"] for row in s["projects"] if row["deadline_result"] == r], loc))
                   for r in RESULTS)


def _quality_panel(s: dict[str, Any], loc: Loc = EN) -> str:
    q = s["quality"]
    if q["by_label"]:
        rows = "".join(f'<div><span style="font-size:16px">{loc.src(row["label"])}</span><span><b style="font-size:20px;font-weight:400">{loc.num(row["occurrences"])}</b> '
                       f'<button type="button" class="info" data-drawer="ql-{escape(s["editor_id"])}-{i}">{loc.count("noun.project", len(set(row["monday_item_ids"])))}</button></span></div>'
                       for i, row in enumerate(q["by_label"]))
        body = (f'<div class="card"><div class="rowlist">{rows}</div><p class="small quiet" style="margin:16px 0 0">'
                f'{loc.t("quality.affected", affected=loc.num(q["projects_with_issues"]), total=loc.num(q["completed_projects_attributed"]))}</p></div>')
    else:
        body = f'<div class="card">{empty_state(loc.t("quality.none_recorded_sentence"), " " + loc.t("quality.empty_detail"))}</div>'
    if not q.get("taxonomy_enabled"):
        # Contracts through 1.4: no positive signal exists and For Bonus is context only (D10).
        return (f'<div class="sh"><div><h2>{loc.t("quality.panel_title")}</h2><p>{loc.t("quality.intro")}</p></div></div>'
                f'<div class="two">{body}<div class="card"><h3 style="margin:0 0 6px;font-weight:500;font-size:16px">{loc.t("quality.positive_title")}</h3>'
                f'{empty_state(loc.t("common.no_signal"), " " + loc.t("quality.positive_detail"))}'
                f'<p class="tiny quiet" style="margin:14px 0 0">{loc.t("quality.for_bonus", projects=loc.count("noun.project", q["for_bonus_context_projects"], case="gen"))}</p></div></div>')
    positive, context = q["positive"], q["context"]

    def label_rows(block: dict[str, Any]) -> str:
        return "".join(
            f'<div><span>{loc.src(row["label"])}</span><b>{loc.num(row["occurrences"])}</b></div>'
            for row in block["by_label"]
        )

    positive_rows = label_rows(positive)
    context_rows = label_rows(context)
    positive_body = (f'<div class="rowlist">{positive_rows}</div>' if positive_rows
                     else empty_state(loc.t("common.no_signal"), " " + loc.t("quality.positive_detail_v15")))
    context_body = (f'<div class="rowlist">{context_rows}</div>' if context_rows
                    else f'<p class="tiny quiet">{loc.t("quality.context_none")}</p>')
    taxonomy = (f'<div class="card"><h3 style="margin:0 0 6px;font-weight:500;font-size:16px">{loc.t("quality.positive_title")}</h3>'
                f'{positive_body}<h3 style="margin:16px 0 6px;font-weight:500;font-size:16px">{loc.t("quality.context_title")}</h3>'
                f'{context_body}</div>')
    return (f'<div class="sh"><div><h2>{loc.t("quality.panel_title")}</h2><p>{loc.t("quality.intro")}</p></div></div>'
            f'<div class="two">{body}{taxonomy}</div>')


def _quality_label_drawers(s: dict[str, Any], loc: Loc = EN) -> str:
    return "".join(template(f"ql-{s['editor_id']}-{i}", f"{row['label']} · {s['display_name']}", _project_list(s, row["monday_item_ids"], loc))
                   for i, row in enumerate(s["quality"]["by_label"]))


def _revision_panel(s: dict[str, Any], loc: Loc = EN) -> str:
    r = s["revisions"]
    internal = r["internal_revision_events"]
    tiles = (f'<div class="metrics" style="margin-top:0"><div class="card"><span class="eyebrow">{loc.t("revisions.client_events")}</span><div class="metric"><span class="v">{loc.num(r["client_revision_events"])}</span></div></div>'
             f'<div class="card"><span class="eyebrow">{loc.t("revisions.projects_with")}</span><div class="metric"><span class="v">{loc.num(r["projects_with_client_revisions"])}'
             f'</span><span class="small quiet">{loc.t("revisions.of_completed", completed=loc.count("noun.completed_project", r["completed_projects"], case="gen"))}</span></div></div>'
             f'<div class="card"><span class="eyebrow">{loc.t("revisions.internal_events")}</span><div class="metric"><span class="v">{_n_or_dash(internal, loc)}</span></div></div></div>')
    listing = (f'<button type="button" class="ghost" data-drawer="rv-{escape(s["editor_id"])}">{loc.t("revisions.projects_with")}</button>'
               if r["monday_item_ids_with_client_revisions"] else "")
    return (f'<div class="sh"><div><h2>{loc.t("revisions.context_heading")}</h2><p>{loc.t("revisions.disclaimer")}</p></div></div>'
            f'{tiles}<div style="margin-top:12px">{listing}</div>')


def _revision_drawer(s: dict[str, Any], loc: Loc = EN) -> str:
    return template(f"rv-{s['editor_id']}", loc.text("revisions.drawer_title", name=s["display_name"]),
                    f'<p>{loc.t("revisions.drawer_intro")} {loc.t("revisions.disclaimer")}</p>'
                    + _project_list(s, s["revisions"]["monday_item_ids_with_client_revisions"], loc))


def fact_text(fact: dict[str, Any], loc: Loc = EN) -> Html:
    """One snapshot fact from the view model's structured ``fact_data`` (English ``facts`` stay in the JSON only)."""
    kind = fact["code"]
    if kind in ("speed_faster", "speed_slower"):
        return loc.t(f"fact.{kind}", labels=loc.labels(fact["labels"]), n=loc.num(fact["projects"]), projects=loc.count("noun.project", fact["projects"]))
    if kind == "issue_label":
        return loc.t("fact.issue_label", n=loc.num(fact["occurrences"]), label=loc.src(fact["label"]))
    if kind == "evidence_projects":
        return loc.t("fact.evidence_projects", n=loc.num(fact["completed"]), completed=loc.count("noun.completed_project", fact["completed"]),
                     measurable=loc.num(fact["measurable"]))
    if kind == "evidence_deadlines":
        return loc.t("fact.evidence_deadlines", n=loc.num(fact["evaluated"]), early=loc.num(fact["early"]), on_time=loc.num(fact["on_time"]),
                     late=loc.num(fact["late"]))
    if kind == "workload":
        return loc.t("fact.workload", n=loc.num(fact["count"]), projects=loc.count("noun.project", fact["count"]), status=loc.src(fact["status"]))
    return loc.t(f"fact.{kind}")


def pending_label(slot: str, loc: Loc = EN, v15: bool = False) -> Html:
    # Contract 1.5 uses the glossary's "Needs Attention Now" (a change-based concept), never "Needs attention" as a status.
    return loc.t(f"pending_v15.{slot}.label" if v15 and loc.has(f"pending_v15.{slot}.label") else f"pending.{slot}.label")


def _snapshot(s: dict[str, Any], loc: Loc = EN) -> str:
    out = []
    for block in s["snapshot"]:
        facts = block.get("fact_data") or []
        items = "".join(f"<li>{fact_text(f, loc)}</li>" for f in facts) or f'<li class="quiet" style="list-style:none;margin-inline-start:-18px">{loc.t("common.no_signal")}</li>'
        judged = (f'<div class="j">{pending_label(block["judgement"]["slot"], loc, "interpretation" in s)}: {loc.t("common.not_evaluated")}</div>' if block["judgement"]
                  else '<div class="j">&nbsp;</div>')
        out.append(f'<div class="card"><h3>{loc.t("snapshot.head." + block["key"])}</h3>{judged}<ul>{items}</ul></div>')
    return f'<div class="qa">{"".join(out)}</div>'


TABS = ("overview", "quality", "speed", "deadlines", "revisions", "evidence")


def editor_profile(s: dict[str, Any], retrieved: str | None, url: str | None, loc: Loc = EN) -> str:
    eid = s["editor_id"]
    pills = "".join(f'<button type="button" class="pill" role="tab" data-pill="t-{eid}-{k}" aria-selected="{"true" if i == 0 else "false"}">{loc.t("tab." + k)}</button>'
                    for i, k in enumerate(TABS))
    name = loc.src(s["display_name"])
    interpretation = interpretation_section(s["interpretation"], loc) + '<div style="margin-top:32px"></div>' if "interpretation" in s else ""
    overview = (f'{interpretation}<div class="sh"><div><h2>{loc.t("profile.timeline_title")}</h2><p>{loc.t("profile.timeline_sub")}</p></div></div>'
                f'<div class="card pulse">{timeline([s], retrieved, f"pt-{eid}", False, loc)}</div>'
                f'<section style="margin-top:32px"><div class="sh"><div><h2>{loc.t("profile.snapshot_title")}</h2><p>{loc.t("profile.snapshot_sub")}</p></div></div>{_snapshot(s, loc)}</section>'
                f'<section style="margin-top:32px"><div class="card" style="display:flex;gap:16px;align-items:center">{icon("spark", 22)}<div><b style="font-weight:500">{loc.t("profile.suggested_action")}</b>'
                f'<div class="small quiet">{loc.t("profile.suggested_action_detail")}</div></div></div></section>')
    evidence = (f'<div class="sh"><div><h2>{loc.t("common.evidence")}</h2><p>{loc.t("profile.evidence_sub", name=name)} {loc.t("profile.evidence_select")}</p></div>'
                f'<button type="button" class="ghost" data-drawer="report-{eid}">{icon("doc", 14)} {loc.t("profile.report_button")}</button></div>'
                f'<div class="card">{_project_list(s, None, loc)}</div>')
    panels = {"overview": overview, "quality": _quality_panel(s, loc), "speed": _speed_panel(s, loc), "deadlines": _deadline_panel(s, loc),
              "revisions": _revision_panel(s, loc), "evidence": evidence}
    body = "".join(f'<div id="t-{eid}-{k}" class="panel" role="tabpanel" {"" if i == 0 else "hidden"}>{panels[k]}</div>' for i, k in enumerate(TABS))
    last_month = next((m["month"] for m in s["monthly"]), None)
    header = (f'<div class="phead">{avatar(s["display_name"], "xl")}<div><span class="eyebrow">{loc.t("common.editor")}</span><h1>{name}</h1>'
              f'<div class="facts" style="margin-top:12px"><div><span>{loc.t("common.current_work")}</span>{workload_chips(s["current_workload"], 4, loc)}</div>'
              f'<div><span>{loc.t("profile.period")}</span><b>{escape(loc.month(last_month)) if last_month else "—"}</b></div>'
              f'<div><span>{loc.t("profile.data_updated")}</span><b>{escape(loc.date(retrieved, False))}</b></div></div></div>'
              f'{_overall(s, loc)}</div>')
    report = template(f"report-{eid}", loc.text("profile.report_title", name=s["display_name"]),
                      f'<p>{loc.t("profile.report_intro")}</p>'
                      f'<iframe title="{_attr(loc.text("profile.report_button"))}" data-report="{escape(eid)}"></iframe>')
    drawers = (_project_templates(s, url, loc) + _event_templates(s, loc) + _speed_drawer(s, loc) + _dq_drawer(s, loc) + _quality_drawer(s, loc)
               + _coverage_drawer(s, loc) + _cohort_drawers(s, loc) + _deadline_group_drawers(s, loc) + _quality_label_drawers(s, loc) + _revision_drawer(s, loc) + report)
    return (f'<div data-view="editor:{escape(eid)}" hidden><a class="back" href="#/">{icon("back", 15)} {loc.t("nav.team")}</a>{header}{_metric_cards(s, loc)}'
            f'<div class="tabs"><div class="pills" role="tablist" data-pills>{pills}</div></div>{body}{drawers}</div>')


# ---------------------------------------------------------------- Data & System

def _status_value(raw: Any, rendered: Any) -> Html:
    """Rendered status value carrying its unchanged language-neutral source for parity checks."""
    value = "" if raw is None else str(raw)
    return Html(f'<span data-status-value="{_attr(value)}">{rendered}</span>')


def _status_date(value: Any, loc: Loc) -> Html:
    return _status_value(value, escape(loc.date(value)))


def _status_code(value: Any, prefix: str, loc: Loc) -> Html:
    if value is None:
        value = "unknown"
    code = str(value).lower()
    key = f"{prefix}.{code}"
    rendered = loc.t(key) if loc.has(key) else loc.tech(value)
    return _status_value(value, rendered)


def _status_id(value: Any, loc: Loc) -> Html:
    return _status_value(value, loc.tech(value) if value else Html("—"))


def _status_attempt(title: Html, attempt: dict[str, Any] | None, loc: Loc) -> str:
    attempt = attempt or {}
    rows = [
        (loc.t("ops.attempt_id"), _status_id(attempt.get("attempt_id"), loc)),
        (loc.t("common.status"), _status_code(attempt.get("status"), "ops.attempt_state", loc)),
        (loc.t("ops.started_at"), _status_date(attempt.get("started_at"), loc)),
        (loc.t("ops.completed_at"), _status_date(attempt.get("finished_at") or attempt.get("completed_at") or attempt.get("failed_at"), loc)),
        (loc.t("ops.source_run"), _status_id(attempt.get("source_run_id"), loc)),
    ]
    error_category = attempt.get("error_category") or attempt.get("failure_category")
    if error_category:
        rows.append((loc.t("ops.failure_category"), _status_id(error_category, loc)))
    return f'<div class="status-detail"><h4>{title}</h4>{_dl(rows)}</div>'


def operational_status(snapshot: dict[str, Any] | None, loc: Loc = EN) -> str:
    """Render one injected Task 7 snapshot without deriving health or freshness.

    Accepted interface: top-level ``generated_at``, ``system_state`` and
    ``freshness_state``; ``current_publication``; ``freshness``; and either top-level or
    ``sync``-nested ``last_attempt`` and ``last_successful_attempt``.
    """
    if snapshot is None:
        return (f'<div class="card operational-status"><h3>{loc.t("ops.title")}</h3>'
                f'<p class="small soft">{loc.t("ops.unavailable")}</p></div>')

    current = snapshot.get("current_publication") or {}
    sync = snapshot.get("sync") or {}
    freshness = snapshot.get("freshness") or {}
    coverage = current.get("coverage") or {}
    last_attempt = snapshot.get("last_attempt") or sync.get("last_attempt")
    last_success = snapshot.get("last_successful_attempt") or sync.get("last_successful_attempt")
    retrieved_at = current.get("monday_retrieved_at") or current.get("retrieved_at")
    coverage_start = current.get("coverage_start") or coverage.get("history_start") or coverage.get("start") or coverage.get("since")
    coverage_end = current.get("coverage_end") or coverage.get("history_end") or coverage.get("end") or coverage.get("until")
    coverage_value = f"{coverage_start or ''}/{coverage_end or ''}"
    coverage_display = Html(f'{escape(loc.date(coverage_start))} <span dir="ltr">→</span> {escape(loc.date(coverage_end))}')
    snapshot_scope = str(snapshot.get("snapshot_scope") or "unknown").lower()
    scope_key = f"ops.scope_note.{snapshot_scope}"
    scope_note = loc.t(scope_key) if loc.has(scope_key) else loc.t("ops.scope_note.unknown")

    headline = (f'<div class="status-head"><div><span>{loc.t("ops.system_status")}</span>'
                f'<b>{_status_code(snapshot.get("system_state"), "ops.system_state", loc)}</b></div>'
                f'<div><span>{loc.t("ops.data_freshness")}</span>'
                f'<b>{_status_code(snapshot.get("freshness_state"), "ops.freshness_state", loc)}</b></div></div>')
    publication = _dl([
        (loc.t("ops.attempt_id"), _status_id(current.get("attempt_id"), loc)),
        (loc.t("ops.publication_id"), _status_id(current.get("publication_id"), loc)),
        (loc.t("ops.published_at"), _status_date(current.get("published_at"), loc)),
        (loc.t("ops.source_run"), _status_id(current.get("source_run_id"), loc)),
        (loc.t("ops.monday_retrieved"), _status_date(retrieved_at, loc)),
        (loc.t("ops.evidence_coverage"), _status_value(coverage_value, coverage_display)),
        (loc.t("system.contract"), _status_id(current.get("contract_version"), loc)),
        (loc.t("ops.board_id"), _status_id(current.get("board_id"), loc)),
    ])
    freshness_rows = _dl([
        (loc.t("ops.age_seconds"), _status_value(freshness.get("age_seconds"), loc.num(freshness.get("age_seconds")))),
        (loc.t("ops.expected_interval"), _status_value(freshness.get("expected_interval_seconds"), loc.num(freshness.get("expected_interval_seconds")))),
        (loc.t("ops.stale_after"), _status_value(freshness.get("stale_after_seconds"), loc.num(freshness.get("stale_after_seconds")))),
    ])
    attempts = (_status_attempt(loc.t("ops.last_attempt"), last_attempt, loc)
                + _status_attempt(loc.t("ops.last_success"), last_success, loc))
    return (f'<div class="card operational-status"><h3>{loc.t("ops.title")}</h3>{headline}'
            f'<p class="small soft">{loc.t("ops.snapshot_context", scope=_status_code(snapshot_scope, "ops.snapshot_scope", loc), date=_status_date(snapshot.get("generated_at"), loc))} {scope_note}</p>'
            f'<div class="status-grid"><div class="status-detail"><h4>{loc.t("ops.current_publication")}</h4>{publication}</div>'
            f'<div class="status-detail"><h4>{loc.t("ops.freshness_details")}</h4>{freshness_rows}</div>{attempts}</div></div>')


def data_system(doc: dict[str, Any], loc: Loc = EN, status_snapshot: dict[str, Any] | None = None) -> str:
    source = doc["source"]
    window = source.get("activity_log_window") or {}
    snapshot = _dl([(loc.t("system.retrieved"), escape(loc.date(source.get("retrieved_at")))),
                    (loc.t("system.window"), Html(f'{escape(loc.date(window.get("since")))} <span dir="ltr">→</span> {escape(loc.date(window.get("until")))}')),
                    (loc.t("system.contract"), loc.tech(source.get("executable_contract_version"))),
                    (loc.t("system.dashboard_document"), loc.tech(doc["dashboard_version"])), (loc.t("system.generated"), escape(loc.date(doc["generated_at"])))])
    first = doc["editors"][0] if doc["editors"] else None
    approved = ""
    if first:
        speed_minimum = first["speed"].get("minimum_editor_sample_size")
        speed_rule = (loc.t("common.not_evaluated") if speed_minimum is None
                      else loc.t("system.rule.speed", stat=loc.t("stat." + first["speed"]["benchmark_statistic"]),
                                 min=loc.num(speed_minimum), min_projects=loc.count("noun.project", speed_minimum)))
        rules = [("common.speed", speed_rule),
                 ("common.deadlines", loc.t("system.rule.deadlines", rule=loc.tech(first["deadline"]["rule_version"]))),
                 ("common.quality", loc.t("system.rule.quality")), ("common.revisions", loc.t("system.rule.revisions"))]
        approved = "<ul>" + "".join(f"<li><b>{loc.t(name)}</b> — {text}</li>" for name, text in rules) + "</ul>"
    v15 = capabilities(doc["source"]["executable_contract_version"]).editor_intelligence
    slots = [slot for slot in PENDING_RULES if not (v15 and slot not in V15_PENDING_SLOTS)]
    pending = "".join(f'<tr><td>{pending_label(slot, loc, v15)}</td><td>{loc.t("common.not_evaluated")}</td>'
                      f'<td>{loc.t(f"pending_v15.{slot}.reason" if v15 and slot in V15_REASONS else f"pending.{slot}.reason")}</td></tr>'
                      for slot in slots)
    editors = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{loc.tech(s["editor_id"])}</td><td>{loc.src(s["monday_label"])}</td>'
                      f'<td>{loc.tech(s["mapping_version"])}</td><td>{loc.tech(s["profile_contract_version"])}</td>'
                      f'<td>{loc.num(s["sample"]["completed_projects"])}</td></tr>' for s in doc["editors"])
    notes = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{warning_text(w, loc)}</td><td>{loc.tech(w["source"])}</td></tr>'
                    for s in doc["editors"] for w in s["warnings"])
    excluded = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{loc.tech(r)}</td><td>{loc.num(n)}</td></tr>'
                       for s in doc["editors"] for r, n in s["sample"]["exclusions_by_reason"].items())
    speed_rows = "".join(f'<tr><td>{loc.src(s["display_name"])}</td><td>{loc.labels(c["labels"])}</td><td>{loc.num(c["editor_sample_size"])}</td>'
                         f'<td>{_n_or_dash(c["team_sample_size"], loc)}</td><td>{loc.t("common.yes" if c["benchmark_eligible"] else "common.no")}</td>'
                         f'<td>{_status(c["comparison_status"], loc)}</td></tr>' for s in doc["editors"] for c in s["speed"]["cohorts"])
    coverage = doc.get("attribution_coverage")
    cov = ""
    if coverage:
        reasons = "".join(f"<tr><td>{loc.tech(r)}</td><td>{loc.num(n)}</td></tr>" for r, n in coverage["not_attributed_by_reason"].items())
        cov = (f'<div class="card"><h3>{loc.t("system.attribution_title")}</h3><p class="small soft">'
               f'{loc.t("system.attribution_text", attributed=loc.num(coverage["attributed"]), completed=loc.count("noun.completed_project", coverage["completed"], case="gen"))}</p>'
               f'<table><thead><tr><th>{loc.t("system.head.reason_not_attributed")}</th><th>{loc.t("common.projects")}</th></tr></thead><tbody>{reasons}</tbody></table></div>')
    missing = "".join(f'<tr><td>{loc.src(e["display_name"])}</td><td>{loc.tech(e["editor_id"])}</td><td>{loc.src(e["monday_label"])}</td></tr>'
                      for e in doc["editors_without_attributable_data"])
    presentation = "<ul>" + "".join(f"<li>{loc.t(k)}</li>" for k in ("system.presentation.headline", "system.presentation.timeline",
                                                                     "system.presentation.months", "system.presentation.languages")) + "</ul>"

    none_row = f'<tr><td colspan=9 class=quiet>{loc.t("common.none")}</td></tr>'

    def table(head: list[str], rows: str) -> str:
        return (f'<div style="overflow-x:auto"><table><thead><tr>{"".join(f"<th scope=col>{loc.t(h)}</th>" for h in head)}</tr></thead>'
                f'<tbody>{rows or none_row}</tbody></table></div>')

    return (f'<div data-view="system" class="sys" hidden><div class="hello"><div><span class="eyebrow">Atlas</span><h1>{loc.t("nav.system")}</h1>'
            f'<p>{loc.t("system.sub")}</p></div></div>'
            f'{operational_status(status_snapshot, loc)}'
            f'<div class="card"><h3>{loc.t("system.snapshot")}</h3>{snapshot}</div>'
            f'<div class="card"><h3>{loc.t("system.approved_rules")}</h3>{approved}</div>'
            f'<div class="card"><h3>{loc.t("common.not_evaluated")}</h3>{table(["system.head.field", "common.status", "common.reason"], pending)}</div>'
            f'<div class="card"><h3>{loc.t("system.editors_identity")}</h3>{table(["common.editor", "system.head.atlas_id", "system.head.monday_label", "system.head.mapping", "system.head.profile", "coverage.completed"], editors)}</div>'
            f'<div class="card"><h3>{loc.t("system.data_quality_notes")}</h3>{table(["common.editor", "system.head.note", "system.head.profile_field"], notes)}</div>'
            f'<div class="card"><h3>{loc.t("system.speed_eligibility")}</h3>{table(["common.editor", "field.video_type", "system.head.editor_n", "system.head.team_n", "system.head.eligible", "common.status"], speed_rows)}</div>'
            f'<div class="card"><h3>{loc.t("system.excluded")}</h3>{table(["common.editor", "common.reason", "common.projects"], excluded)}</div>'
            f'{cov}<div class="card"><h3>{loc.t("system.mapped_without")}</h3>{table(["common.editor", "system.head.atlas_id", "system.head.monday_label"], missing)}</div>'
            f'<div class="card"><h3>{loc.t("system.presentation_notes")}</h3>{presentation}</div></div>')


# ---------------------------------------------------------------- page

def language_switch(loc: Loc, href: str, keep_hash: bool = False) -> str:
    """Link to the same page in the other language (the equivalent dashboard view keeps its #route)."""
    other = loc.other()
    return (f'<a class="lang" href="{escape(href)}" hreflang="{other.code}" lang="{other.code}" dir="{other.dir}"'
            f'{" data-keep-hash" if keep_hash else ""} aria-label="{_attr(loc.text("lang.switch_label"))}">{escape(loc.text("lang.other_name"))}</a>')


def render_dashboard_html(doc: dict[str, Any], profile_pages: dict[str, str], monday_item_url: str | None = None, loc: Loc = EN,
                          switch_href: str | None = None, status_snapshot: dict[str, Any] | None = None) -> str:
    """Render the dashboard in ``loc``. ``profile_pages`` maps editor_id -> the full Editor Profile report HTML (same language), embedded
    unchanged as the audit view. ``switch_href`` links to the same dashboard in the other language (omitted: no language switch)."""
    source = doc["source"]
    v15 = capabilities(source["executable_contract_version"]).editor_intelligence
    publication = doc.get("publication") or {}
    release_id, snapshot_id = publication.get("release_id"), publication.get("snapshot_id")
    retrieved = source.get("retrieved_at")
    month = str(retrieved)[:7] if retrieved else None
    blob = json.dumps(profile_pages).replace("</", "<\\/")
    editors = doc["editors"]
    cards = "".join(editor_card(s, loc) for s in editors) or empty_state(loc.t("home.no_editors"))
    meta = ((f'<span><b>{escape(loc.month(month))}</b> · {loc.t("common.month_in_progress")}</span>' if month else "")
            + f'<span>{loc.count("meta.editors", len(editors))}</span><span>{loc.t("home.updated", date=Html(escape(loc.date(retrieved, False))))}</span>'
            + (f'<span>{loc.t("publication.release", release=loc.tech(release_id))}</span>' if release_id else ""))
    greeting = " ".join(f'data-{part}="{_attr(loc.text("home.greeting." + part))}"' for part in ("morning", "afternoon", "evening"))
    home = (f'<div data-view="team"><div class="hello"><div><span class="eyebrow">Atlas</span><h1 id="greeting" {greeting}>{loc.t("home.title")}</h1>'
            f'<p>{loc.t("home.sub")}</p></div><div class="meta">{meta}</div></div>'
            f'{management_focus(doc, loc)}'
            f'<section aria-labelledby="team-h"><div class="sh"><div><h2 id="team-h">{loc.t("home.team_title")}</h2><p>{loc.t("home.team_sub")}</p></div></div>'
            f'<div class="grid-ed">{cards}</div></section>'
            f'<section aria-labelledby="pulse-h"><div class="sh"><div><h2 id="pulse-h">{loc.t("home.pulse_title")}</h2><p>{loc.t("home.pulse_sub")}</p></div></div>'
            f'<div class="card pulse">{timeline(editors, retrieved, "pulse", True, loc)}</div></section>'
            f'<section aria-label="{_attr(loc.text("home.context_label"))}"><div class="ctx">{issue_activity(doc, month, loc)}{patterns_card(loc)}{workload_card(doc, loc)}</div></section>'
            f'<section aria-labelledby="hist-h"><div class="sh"><div><h2 id="hist-h">{loc.t("home.history_title")}</h2><p>{loc.t("home.history_sub")}</p></div></div>{history(doc, loc)}</section>'
            + "".join(_speed_drawer(s, loc) + _dq_drawer(s, loc) for s in editors) + "</div>")
    profiles = "".join(editor_profile(s, retrieved, monday_item_url, loc) for s in editors)
    # The home view and each profile view declare their own speed/deadline drawers; keep one copy of each id.
    body = _dedupe_templates(home + profiles)
    switch = language_switch(loc, switch_href, keep_hash=True) if switch_href else ""
    publication_meta = (f'<meta name="atlas-release-id" content="{escape(release_id)}"><meta name="atlas-snapshot-id" content="{escape(snapshot_id)}">'
                        if release_id and snapshot_id else "")
    publication_attrs = (f' data-atlas-release-id="{escape(release_id)}" data-atlas-snapshot-id="{escape(snapshot_id)}"'
                         if release_id and snapshot_id else "")
    return (f'<!doctype html><html lang="{loc.code}" dir="{loc.dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{publication_meta}<title>{loc.t("page.dashboard_title")}</title><style>{CSS}{IA_CSS if v15 else ""}</style></head><body{publication_attrs}><div class="shell">'
            f'<header class="topbar"><a class="brand" href="#/"><i></i>Atlas</a><div class="topnav"><nav class="nav" aria-label="{_attr(loc.text("nav.main_label"))}">'
            f'<a href="#/" data-nav="team" aria-current="page">{loc.t("nav.team")}</a><a href="#/system" data-nav="system">{loc.t("nav.system")}</a></nav>{switch}</div></header>'
            f'<main>{body}{data_system(doc, loc, status_snapshot)}</main></div>'
            '<div class="scrim"></div><aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="drawer-title">'
            f'<header><h2 id="drawer-title"></h2><button type="button" class="x" aria-label="{_attr(loc.text("common.close"))}">{icon("x")}</button></header><div class="body"></div></aside>'
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
