"""Design system of the contract 1.5 Atlas pages: one stylesheet and one small script, both inline (presentation only).

The pages are static and self-contained: no web font, no CDN, no network request. Colours are tokens defined once for light and
dark schemes. Layout uses logical properties (``inline-start``/``inline-end``) so English (LTR) and Arabic (RTL) share one design.

Colour semantics are deliberately calm (HANDOFF-V2 §23, fairness):

- Overall Status and component states use a muted green / amber / terracotta scale; "not classifiable" is a dashed, grey outline
  so missing evidence never looks like a negative result.
- Revisions and current work are always neutral slate, never a warning colour.
- Small samples are not styled more strongly than large ones; every figure carries its sample size in text.
"""

CSS = r"""
:root{color-scheme:light dark;
--bg:#f4f3ef;--surface:#fff;--surface-2:#f1efe9;--surface-3:#e8e5dc;--line:#e3e0d7;--line-2:#d3cfc3;
--ink:#1a1b16;--ink-2:#4f5048;--ink-3:#7f7f74;--brand:#d7f542;--focus:#3b5bdb;
--pos:#17603f;--pos-bg:#e1f0e7;--good:#3f7a33;--good-bg:#ebf3e1;--mix:#8a5c00;--mix-bg:#f8eed5;--neg:#a2432a;--neg-bg:#f7e5dd;
--neu:#4f5a68;--neu-bg:#e9edf2;--na:#7f7f74;
--early:#2b6c8c;--ontime:#8b9098;--late:#b0583b;
--r-lg:20px;--r-md:14px;--r-sm:10px;--r-pill:999px;
--shadow:0 1px 2px rgba(20,20,10,.05),0 8px 24px rgba(20,20,10,.06);--shadow-lg:0 12px 48px rgba(20,20,10,.18);
--t:180ms cubic-bezier(.2,.7,.2,1);
--font:"Inter","SF Pro Text","Segoe UI Variable","Segoe UI",system-ui,-apple-system,sans-serif;
--mono:"SF Mono","JetBrains Mono",ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{
--bg:#121310;--surface:#1b1c18;--surface-2:#23241f;--surface-3:#2d2e28;--line:#2f302a;--line-2:#3f4038;
--ink:#efeee8;--ink-2:#bdbcb2;--ink-3:#8e8d83;--focus:#8fa8ff;
--pos:#6fcf9a;--pos-bg:#16301f;--good:#a6d38a;--good-bg:#1f2c18;--mix:#e7b851;--mix-bg:#34290f;--neg:#f0957a;--neg-bg:#3a1f16;
--neu:#aab6c6;--neu-bg:#222a33;--na:#8e8d83;--early:#7fbfe0;--ontime:#9aa0a8;--late:#ef9a7c;
--shadow:0 1px 2px rgba(0,0,0,.4);--shadow-lg:0 16px 48px rgba(0,0,0,.55)}}
:root[lang=ar]{--font:"Segoe UI","Noto Sans Arabic","Noto Naskh Arabic","Geeza Pro","Arabic UI Text",Tahoma,system-ui,sans-serif}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;scroll-padding-top:120px}
body{margin:0;overflow-x:hidden;background:var(--bg);color:var(--ink);font:15px/1.55 var(--font);font-feature-settings:"tnum" 1;-webkit-font-smoothing:antialiased}
[lang=ar] body{line-height:1.8}
a{color:inherit}button,input{font:inherit;color:inherit}h1,h2,h3,h4{margin:0;font-weight:600;letter-spacing:-.01em}[lang=ar] :is(h1,h2,h3,h4){letter-spacing:0}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:6px}
bdi,code{unicode-bidi:isolate}code{font:12px/1.4 var(--mono);background:var(--surface-2);padding:1px 6px;border-radius:6px;word-break:break-all}
[hidden]{display:none!important}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.muted{color:var(--ink-3)}.soft{color:var(--ink-2)}.sm{font-size:13px}.xs{font-size:12px}.num{font-variant-numeric:tabular-nums}
[dir=rtl] .flip{transform:scaleX(-1)}

/* ---- shell */
.top{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line)}
.top-in{max-width:1480px;margin:0 auto;padding:10px clamp(16px,3vw,40px);display:flex;align-items:center;gap:16px}
.brand{display:flex;align-items:center;gap:9px;font-weight:650;font-size:17px;text-decoration:none;letter-spacing:-.01em}
.brand i{width:11px;height:11px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 3px var(--ink)}
.nav{display:flex;gap:4px;margin-inline-start:8px}
.nav a{white-space:nowrap;padding:7px 12px;border-radius:var(--r-pill);text-decoration:none;font-size:14px;color:var(--ink-2)}
.nav a:hover{background:var(--surface-2);color:var(--ink)}.nav a[aria-current=page]{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line-2)}
.top-end{margin-inline-start:auto;display:flex;align-items:center;gap:8px}
.fresh{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;color:var(--ink-2);text-decoration:none;padding:6px 10px;border-radius:var(--r-pill)}
.fresh:hover{background:var(--surface-2)}.fresh i{width:7px;height:7px;border-radius:50%;background:var(--pos)}
.lang{padding:6px 12px;border-radius:var(--r-pill);border:1px solid var(--line-2);text-decoration:none;font-size:13.5px;background:var(--surface)}
.lang:hover{background:var(--surface-2)}
.wrap{max-width:1480px;margin:0 auto;padding:28px clamp(16px,3vw,40px) 80px}

/* ---- headings */
.ph{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 24px;margin-bottom:20px}
.ph h1{font-size:clamp(26px,3vw,34px);letter-spacing:-.02em;line-height:1.15}.ph p{margin:6px 0 0;color:var(--ink-2);max-width:72ch}
.sec{margin-top:40px}.sec-h{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px;margin-bottom:14px}
.sec-h h2{font-size:20px}.sec-h p{margin:2px 0 0;color:var(--ink-3);font-size:13.5px;max-width:80ch}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);padding:20px}
.card h3{font-size:15px}.card+.card{margin-top:12px}
.note{margin:12px 0 0;color:var(--ink-3);font-size:12.5px;max-width:90ch}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
@media (max-width:980px){.grid2,.grid3{grid-template-columns:minmax(0,1fr)}}

/* ---- status, states, chips */
.st{display:inline-flex;align-items:center;gap:7px;padding:4px 11px 4px 9px;border-radius:var(--r-pill);font-size:13px;font-weight:600;white-space:nowrap;background:var(--surface-2);color:var(--ink-2)}
.st::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.st.lg{font-size:17px;padding:7px 16px 7px 13px}.st.lg::before{width:10px;height:10px}
.st.strong{background:var(--pos-bg);color:var(--pos)}.st.good{background:var(--good-bg);color:var(--good)}.st.mixed{background:var(--mix-bg);color:var(--mix)}
.st.below_expectations{background:var(--neg-bg);color:var(--neg)}
.st.none{background:transparent;color:var(--na);box-shadow:inset 0 0 0 1px var(--line-2);font-weight:500}.st.none::before{background:transparent;box-shadow:inset 0 0 0 1.5px currentColor}
.sc{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:550;white-space:nowrap}
.sc::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.sc.positive{color:var(--pos)}.sc.neutral{color:var(--neu)}.sc.negative{color:var(--neg)}
.sc.not_classifiable{color:var(--na);font-weight:450}.sc.not_classifiable::before{background:transparent;box-shadow:inset 0 0 0 1.5px currentColor}
.vd{display:inline-block;padding:2px 9px;border-radius:var(--r-pill);font-size:12px;font-weight:600;background:var(--surface-2);color:var(--ink-2)}
.vd.faster{background:var(--pos-bg);color:var(--pos)}.vd.slower{background:var(--neg-bg);color:var(--neg)}.vd.similar{background:var(--neu-bg);color:var(--neu)}
.vd.not_classifiable{background:transparent;color:var(--na);box-shadow:inset 0 0 0 1px var(--line-2);font-weight:500}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:var(--r-pill);background:var(--surface-2);font-size:12.5px;color:var(--ink-2);max-width:100%}
.chip b{font-weight:600;color:var(--ink)}.chip.pos{background:var(--pos-bg);color:var(--pos)}.chip.neg{background:var(--neg-bg);color:var(--neg)}
.chip.ctx{background:transparent;box-shadow:inset 0 0 0 1px var(--line-2)}
.chip.pos b,.chip.neg b{color:inherit}

/* ---- buttons */
.btn{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;border-radius:var(--r-pill);border:1px solid var(--line-2);background:var(--surface);font-size:13px;cursor:pointer;text-decoration:none;color:var(--ink);transition:background var(--t)}
.btn:hover{background:var(--surface-2)}.btn.dark{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.link{border:0;background:none;padding:0;cursor:pointer;color:var(--ink-2);font-size:12.5px;display:inline;text-decoration:underline;text-decoration-color:var(--line-2);text-underline-offset:3px}
.link:hover{color:var(--ink);text-decoration-color:currentColor}

/* ---- overview */
.tools{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:18px}
.search{position:relative;flex:1 1 260px;max-width:380px}
.search input{width:100%;padding:10px 14px;padding-inline-start:38px;border-radius:var(--r-pill);border:1px solid var(--line-2);background:var(--surface);font-size:14px}
.search input:focus{outline:2px solid var(--focus);outline-offset:1px}
.search svg{position:absolute;inset-inline-start:13px;top:50%;transform:translateY(-50%);color:var(--ink-3)}
.filters{display:flex;flex-wrap:wrap;gap:6px}
.filter{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:var(--r-pill);border:1px solid var(--line);background:var(--surface);font-size:13px;cursor:pointer;color:var(--ink-2)}
.filter:hover{border-color:var(--line-2);color:var(--ink)}.filter[aria-pressed=true]{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.filter .n{font-weight:650}.filter i{width:8px;height:8px;border-radius:50%;background:currentColor}
.filter.strong i{color:var(--pos)}.filter.good i{color:var(--good)}.filter.mixed i{color:var(--mix)}.filter.below_expectations i{color:var(--neg)}
.filter.none i{background:transparent;box-shadow:inset 0 0 0 1.5px var(--na)}
.filter[aria-pressed=true] i{color:inherit}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(320px,100%),1fr));gap:14px}
@media (min-width:1700px){.cards{grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}}
.ed{position:relative;display:flex;flex-direction:column;gap:14px;padding:18px;border-radius:var(--r-lg);background:var(--surface);border:1px solid var(--line);transition:box-shadow var(--t),border-color var(--t),transform var(--t)}
.ed:hover{box-shadow:var(--shadow);border-color:var(--line-2);transform:translateY(-1px)}
.ed-h{display:flex;align-items:center;gap:12px}.ed-h h3{font-size:17px;line-height:1.2}
.ed-h a{text-decoration:none}.ed-h a::after{content:"";position:absolute;inset:0;border-radius:var(--r-lg)}
.ed-h .sub{font-size:12.5px;color:var(--ink-3)}
.ed .st{align-self:flex-start}
.avatar{flex:none;width:40px;height:40px;border-radius:50%;display:grid;place-items:center;font-weight:600;font-size:14px;background:var(--surface-3);color:var(--ink)}
.avatar.xl{width:64px;height:64px;font-size:22px}
.comp{display:grid;gap:0;border-top:1px solid var(--line)}
.comp>div{display:grid;grid-template-columns:78px 1fr;gap:10px;align-items:baseline;padding:9px 0;border-bottom:1px solid var(--line);font-size:13.5px}
[lang=ar] .comp>div{grid-template-columns:96px 1fr}
.comp dt{color:var(--ink-3);font-size:12.5px}.comp dd{margin:0;display:flex;flex-direction:column;align-items:flex-start;gap:2px}
.comp .fact{color:var(--ink-2)}
.sig{display:flex;flex-direction:column;gap:6px;font-size:12.5px}
.sig>div{display:flex;gap:8px;align-items:baseline;color:var(--ink-2)}.sig .k{color:var(--ink-3);flex:none;min-width:78px}
[lang=ar] .sig .k{min-width:96px}
.ed-f{margin-top:auto;display:flex;justify-content:space-between;gap:10px;font-size:12px;color:var(--ink-3)}
.nomatch{padding:40px;text-align:center;color:var(--ink-3);border:1px dashed var(--line-2);border-radius:var(--r-lg)}

/* ---- tabs (segmented) */
.seg{display:inline-flex;flex-wrap:wrap;gap:4px;padding:4px;border-radius:var(--r-pill);background:var(--surface-2);margin-bottom:14px}
.seg button{border:0;background:none;padding:6px 14px;border-radius:var(--r-pill);font-size:13px;cursor:pointer;color:var(--ink-2)}
.seg button[aria-selected=true]{background:var(--surface);color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.seg button:disabled{opacity:.4;cursor:default}

/* ---- profile */
.back{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;color:var(--ink-2);text-decoration:none;margin-bottom:16px}.back:hover{color:var(--ink)}
.hero{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:16px}
@media (max-width:1080px){.hero{grid-template-columns:minmax(0,1fr)}}
.who{display:flex;gap:16px;align-items:center}.who h1{font-size:clamp(26px,3vw,34px);letter-spacing:-.02em;line-height:1.1}
.who .sub{margin-top:4px;font-size:13px;color:var(--ink-3)}
.status-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin:18px 0 6px}
.why{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:0;border-top:1px solid var(--line)}
.why li{display:grid;grid-template-columns:110px auto minmax(0,1fr);gap:10px;align-items:baseline;padding:9px 0;border-bottom:1px solid var(--line);font-size:13.5px}
[lang=ar] .why li{grid-template-columns:130px auto 1fr}
.why li b{font-weight:550}.why li .r{color:var(--ink-3);font-size:12.5px}
@media (max-width:600px){.why li{grid-template-columns:minmax(0,1fr) auto}.why li .r{grid-column:1/-1}.who{align-items:flex-start}.avatar.xl{width:48px;height:48px;font-size:18px}}
.kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-content:start}
.kpi{all:unset;box-sizing:border-box;cursor:pointer;display:flex;flex-direction:column;gap:4px;padding:14px 16px;border-radius:var(--r-md);background:var(--surface);border:1px solid var(--line);transition:border-color var(--t),box-shadow var(--t)}
.kpi:hover{border-color:var(--line-2);box-shadow:var(--shadow)}.kpi:focus-visible{outline:2px solid var(--focus)}
.kpi .k{font-size:12px;color:var(--ink-3);display:flex;justify-content:space-between;gap:8px;align-items:center}
.kpi .v{font-size:26px;font-weight:600;letter-spacing:-.02em;line-height:1.15}.kpi .d{font-size:12.5px;color:var(--ink-2)}
.jump{position:sticky;top:57px;z-index:5;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(8px);margin:24px calc(-1 * clamp(16px,3vw,40px)) 0;padding:8px clamp(16px,3vw,40px);border-bottom:1px solid var(--line);overflow-x:auto;white-space:nowrap;scrollbar-width:none}
.jump::-webkit-scrollbar{display:none}
.jump button{border:0;background:none;padding:6px 11px;border-radius:var(--r-pill);font-size:13px;color:var(--ink-2);cursor:pointer}
.jump a{display:inline-block;padding:6px 11px;border-radius:var(--r-pill);font-size:13px;color:var(--ink-2);text-decoration:none}
.jump button:hover,.jump a:hover{color:var(--ink)}.jump button[aria-current=true]{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line-2)}
.list-plain{list-style:none;margin:0;padding:0}
.facts{display:grid;gap:8px;list-style:none;margin:0;padding:0}
.facts li{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:10px 12px;border-radius:var(--r-sm);background:var(--surface-2);font-size:13.5px}
.facts li .link{flex:none}
.facts .empty{background:transparent;padding:4px 0;color:var(--ink-3)}
.sig-h{display:flex;align-items:center;gap:8px;margin-bottom:10px}.sig-h i{width:9px;height:9px;border-radius:50%}
.sig-h.pos i{background:var(--pos)}.sig-h.neg i{background:var(--neg)}
.change{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(250px,100%),1fr));gap:10px}
.chg{padding:14px 16px;border-radius:var(--r-md);background:var(--surface);border:1px solid var(--line);display:flex;flex-direction:column;gap:6px}
.chg .k{font-size:12.5px;color:var(--ink-2)}.chg .k small{display:block;color:var(--ink-3);font-size:11.5px}
.chg .row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--ink-3)}
.chg .row b{font-size:20px;font-weight:600;color:var(--ink);letter-spacing:-.01em}
.chg .delta{font-size:13px;font-weight:600;color:var(--ink-2)}
.chg .tr{font-size:12px;color:var(--ink-3)}
.stat{display:flex;flex-direction:column;gap:2px}.stat b{font-size:24px;font-weight:600;letter-spacing:-.02em;line-height:1.2}.stat span{font-size:12.5px;color:var(--ink-3)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(140px,100%),1fr));gap:16px}
.comp-h{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 16px;margin-bottom:14px}
.comp-h .r{color:var(--ink-3);font-size:12.5px}
.ev{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin-top:14px;padding-top:12px;border-top:1px dashed var(--line-2);font-size:12px;color:var(--ink-3)}
/* bars */
.bars{display:grid;gap:10px}
.bar{display:grid;grid-template-columns:minmax(120px,220px) 1fr auto;gap:12px;align-items:center;font-size:13.5px}
@media (max-width:600px){.bar{grid-template-columns:1fr auto}.bar .track{grid-column:1/-1}}
.track{height:8px;border-radius:var(--r-pill);background:var(--surface-2);overflow:hidden}.track i{display:block;height:100%;border-radius:inherit;background:var(--ink-3)}
.track.pos i{background:var(--pos)}.track.neg i{background:var(--neg)}.track.ctx i{background:var(--neu)}
.stack{display:flex;height:14px;border-radius:var(--r-pill);overflow:hidden;background:var(--surface-2);gap:2px}
.stack i{display:block;height:100%}.stack .early{background:var(--early)}.stack .on_time{background:var(--ontime)}.stack .late{background:var(--late)}
.key{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--ink-2);margin-top:10px}
.key span{display:inline-flex;align-items:center;gap:6px}.key i{width:9px;height:9px;border-radius:3px}
.key .early{background:var(--early)}.key .on_time{background:var(--ontime)}.key .late{background:var(--late)}
/* speed rows */
.vt{display:grid;grid-template-columns:minmax(140px,1fr) minmax(220px,2fr) 190px;gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line)}
.vt:last-child{border-bottom:0}
@media (max-width:760px){.vt{grid-template-columns:minmax(0,1fr)}}
.vt .name{font-weight:550}.vt .name small{display:block;font-weight:400;color:var(--ink-3);font-size:12px;margin-top:2px}
.cmp{display:grid;gap:6px}.cmp>div{display:grid;grid-template-columns:96px 1fr 64px;gap:10px;align-items:center;font-size:12.5px;color:var(--ink-2)}
[lang=ar] .cmp>div{grid-template-columns:110px 1fr 76px}
.cmp .track{height:10px}.cmp .me i{background:var(--ink)}.cmp .team i{background:var(--ink-3)}
.cmp .v{text-align:end;font-weight:600;color:var(--ink)}
.vt .res{display:flex;flex-direction:column;align-items:flex-end;gap:4px;text-align:end}.vt .res .r{font-size:12px;color:var(--ink-3)}
@media (max-width:760px){.vt .res{align-items:flex-start;text-align:start}}
.tally{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:6px}
/* tables */
.tbl{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:start;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:550;color:var(--ink-3);font-size:12px;background:var(--surface-2)}
tbody tr:last-child td{border-bottom:0}
td ul{margin:0;padding-inline-start:16px}
/* project list */
.plist{display:flex;flex-direction:column}
.plist button{all:unset;box-sizing:border-box;cursor:pointer;display:grid;grid-template-columns:110px minmax(0,1fr) 150px minmax(0,1fr) 70px;gap:12px;padding:11px 12px;border-bottom:1px solid var(--line);font-size:13px;align-items:center}
.plist button:hover{background:var(--surface-2)}.plist button:focus-visible{outline:2px solid var(--focus)}
.plist button:last-child{border-bottom:0}
.plist-h{display:grid;grid-template-columns:110px minmax(0,1fr) 150px minmax(0,1fr) 70px;gap:12px;padding:10px 12px;font-size:12px;color:var(--ink-3);border-bottom:1px solid var(--line)}
@media (max-width:760px){.plist button{grid-template-columns:1fr 1fr}.plist-h{display:none}}
.res-early{color:var(--early)}.res-late{color:var(--late)}.res-on_time{color:var(--ink-2)}
/* timeline */
.tl{overflow-x:auto;direction:ltr}.tl-in{min-width:680px}
.axis{position:relative;height:24px;margin-left:150px;border-bottom:1px solid var(--line)}
.axis span{position:absolute;bottom:5px;transform:translateX(-50%);font-size:11.5px;color:var(--ink-3);white-space:nowrap}.axis .today{color:var(--ink);font-weight:600}
.lane{display:flex;align-items:stretch;border-bottom:1px solid var(--line)}.lane:last-child{border-bottom:0}
.lane .ln{width:150px;flex:none;display:flex;align-items:center;gap:8px;font-size:13px;padding:8px 8px 8px 0}.lane .ln .avatar{width:24px;height:24px;font-size:10px}
.lane .trk{position:relative;flex:1;min-height:40px;background:linear-gradient(var(--line),var(--line)) center/100% 1px no-repeat}
.lane .now{position:absolute;top:0;bottom:0;width:0;border-left:1px dashed var(--ink-3)}
.mk{position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;border:0;padding:0;background:none;cursor:pointer;display:grid;place-items:center;border-radius:50%}
.mk i{display:block;width:10px;height:10px;border-radius:50%}
.mk:hover i{transform:scale(1.3)}.mk.early i{background:var(--early)}.mk.on_time i{background:var(--surface);box-shadow:inset 0 0 0 2px var(--ontime)}
.mk.late i{background:var(--late);border-radius:2px;transform:rotate(45deg);width:9px;height:9px}
.mk.unclassified i{width:7px;height:7px;background:var(--surface);box-shadow:inset 0 0 0 1.5px var(--ink-3)}
.mk.issue i{border-radius:2px;background:var(--surface);box-shadow:inset 0 0 0 2px var(--neg)}
.mk.positive i{border-radius:2px;background:var(--pos)}.mk.context i{border-radius:2px;background:var(--surface);box-shadow:inset 0 0 0 2px var(--neu)}
.mk.is-selected{box-shadow:0 0 0 2px var(--focus)}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:14px;font-size:12px;color:var(--ink-3);align-items:center}
.legend .mk{position:static;margin:0;display:inline-grid;cursor:default}
/* drawer */
.scrim{position:fixed;inset:0;background:rgba(10,10,5,.35);opacity:0;pointer-events:none;transition:opacity var(--t);z-index:30}
.drawer{position:fixed;top:10px;bottom:10px;inset-inline-end:10px;width:min(560px,calc(100vw - 20px));background:var(--surface);border-radius:var(--r-lg);box-shadow:var(--shadow-lg);
transform:translateX(calc(100% + 20px));transition:transform var(--t);z-index:31;display:flex;flex-direction:column}
[dir=rtl] .drawer{transform:translateX(calc(-100% - 20px))}
body.drawer-open .scrim{opacity:1;pointer-events:auto}body.drawer-open .drawer{transform:none}
.drawer header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 20px 10px;border-bottom:1px solid var(--line)}
.drawer header h2{font-size:17px}.drawer .body{overflow:auto;padding:14px 20px 24px;font-size:13.5px}
.drawer .x{border:0;background:var(--surface-2);width:34px;height:34px;border-radius:50%;cursor:pointer;display:grid;place-items:center;flex:none}
.drawer dl,.dl{display:grid;grid-template-columns:minmax(120px,170px) 1fr;gap:8px 14px;margin:0}.drawer dt,.dl dt{color:var(--ink-3)}.drawer dd,.dl dd{margin:0;min-width:0}
.drawer h4{margin:20px 0 8px;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
[lang=ar] .drawer h4{letter-spacing:0;text-transform:none;font-size:13px}
.drawer iframe{width:100%;height:72vh;border:1px solid var(--line);border-radius:var(--r-md);background:var(--bg)}
.drawer p{color:var(--ink-2)}.drawer ul{padding-inline-start:18px}
/* system */
.status-head{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}
.status-head>div,.status-detail{border:1px solid var(--line);border-radius:var(--r-md);padding:14px}
.status-head span{display:block;color:var(--ink-3);font-size:12.5px}.status-head b{display:block;margin-top:4px;font-size:18px;font-weight:600}
.status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:12px}
.status-detail h4{margin:0 0 10px;font-size:13.5px}.status-detail dl{display:grid;grid-template-columns:minmax(120px,170px) 1fr;gap:6px 12px;margin:0;font-size:13px}
.status-detail dt{color:var(--ink-3)}.status-detail dd{margin:0}
@media (max-width:760px){.status-head,.status-grid{grid-template-columns:1fr}}
.rules{display:grid;gap:8px;list-style:none;padding:0;margin:0}.rules li{display:flex;gap:12px;justify-content:space-between;align-items:baseline;padding:10px 12px;border-radius:var(--r-sm);background:var(--surface-2);font-size:13.5px}
.rules li span:last-child{color:var(--ink-3);font-size:12.5px;text-align:end;max-width:60%}
@media (max-width:760px){.rules li{flex-direction:column}.rules li span:last-child{text-align:start;max-width:none}}
details.more{margin-top:12px}details.more>summary{cursor:pointer;font-size:13px;color:var(--ink-2);list-style:none;display:inline-flex;gap:6px;align-items:center}
details.more>summary::-webkit-details-marker{display:none}details.more>summary::before{content:"+";display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;background:var(--surface-2);font-size:12px}
details.more[open]>summary::before{content:"−"}
/* Intelligence V2: top findings, evidence, confidence (presentation only) */
.iv{margin:0 0 30px}.iv-top-h{font-size:14px;color:var(--ink-2);margin:0 0 10px;font-weight:600}
.iv-grid{display:grid;gap:12px}.iv-list{display:grid;gap:10px}
.iv-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);padding:18px 20px;min-width:0}
.iv-card h3{font-size:16px;margin:10px 0 8px;overflow-wrap:anywhere}.iv-card.compact h3{font-size:15px}.iv-card p{margin:0;color:var(--ink-2);font-size:14px;overflow-wrap:anywhere}
.iv-h{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
.iv-rank{display:inline-grid;place-items:center;min-width:24px;height:24px;border-radius:50%;background:var(--ink);color:var(--surface);font-size:12px;font-weight:650}
.iv-cat,.iv-conf,.iv-rel{display:inline-flex;align-items:center;padding:2px 9px;border-radius:var(--r-pill);font-size:12px;font-weight:600;background:var(--surface-2);color:var(--ink-2);white-space:nowrap}
.iv-cat.adverse{background:var(--neg-bg);color:var(--neg)}.iv-cat.favourable{background:var(--pos-bg);color:var(--pos)}.iv-cat.mixed{background:var(--mix-bg);color:var(--mix)}
.iv-cat.neutral,.iv-cat.data_warning{background:var(--neu-bg);color:var(--neu)}
.iv-conf{background:transparent;border:1px solid var(--line-2)}.iv-conf.strong{border-color:var(--ink-2);color:var(--ink)}.iv-conf.weak{border-style:dashed;color:var(--ink-3)}
.iv-rel{background:transparent;color:var(--ink-3);font-weight:500}
.iv-dl{display:grid;grid-template-columns:minmax(120px,170px) minmax(0,1fr);gap:6px 16px;margin:6px 0 0;font-size:14px}
.iv-dl dt{color:var(--ink-3);font-size:12.5px;padding-top:2px}.iv-dl dd{margin:0;overflow-wrap:anywhere}
.iv-mixed{margin:12px 0 0;padding:10px 12px;border-radius:var(--r-sm);background:var(--mix-bg);color:var(--ink);font-size:13px}
.iv-mixed b{color:var(--mix);font-weight:600}.iv-mixed ul{margin:4px 0 0;padding-inline-start:18px}
.iv-ev{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:6px 14px;margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:12.5px;color:var(--ink-3)}
.iv-more ul{list-style:none;margin:6px 0 0;padding:0;display:grid;gap:6px}.iv-group{margin-top:12px}.iv-group h4{font-size:13px;color:var(--ink-2);font-weight:600}
.iv-row{all:unset;box-sizing:border-box;cursor:pointer;display:flex;gap:10px;align-items:center;width:100%;padding:9px 12px;border-radius:var(--r-sm);background:var(--surface-2);font-size:13.5px}
.iv-row:hover{background:var(--surface-3)}.iv-row span:last-child{overflow-wrap:anywhere;min-width:0}.iv-row:focus-visible{outline:2px solid var(--focus)}
.iv-items{max-height:320px;overflow:auto}.iv-items .chip{cursor:pointer;border:0}
@media (max-width:640px){.iv-dl{grid-template-columns:minmax(0,1fr)}.iv-dl dt{padding-top:6px}.iv-card{padding:16px}}
/* report (standalone, printable) */
.report .wrap{max-width:1100px}
@media print{.top,.jump,.lang,.btn{display:none!important}body{background:#fff}.card{break-inside:avoid;border-color:#ccc}details>*{display:block}}
@media (max-width:760px){.wrap{padding-top:18px}.nav a{padding:6px 9px}.fresh span{display:none}}
@media (max-width:600px){.kpis{grid-template-columns:minmax(0,1fr)}.nav{margin-inline-start:0}.nav a{white-space:nowrap}.top-in{gap:10px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

SCRIPT = r"""
(function(){
  var reportsEl = document.getElementById('atlas-reports');
  var reports = reportsEl ? JSON.parse(reportsEl.textContent) : {};
  var views = document.querySelectorAll('[data-view]');
  var drawer = document.getElementById('drawer');
  // Scroll: a new route opens at the top; Back and Forward return to where that history entry was left (ATLAS-MOBILE-002).
  // Each entry keeps its own position in history.state, so the browser's per-document restoration is switched off.
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  function saveScroll(){
    var state = history.state || {};
    if (state.atlasY === window.scrollY) return;
    try { history.replaceState(Object.assign({}, state, {atlasY: window.scrollY}), ''); } catch (err) {}
  }
  var saveTimer = null;
  window.addEventListener('scroll', function(){
    if (saveTimer) return;
    saveTimer = setTimeout(function(){ saveTimer = null; saveScroll(); }, 200);
  }, {passive: true});
  function route(){
    var h = location.hash || '#/', name = 'team', m;
    if (h === '#/system') name = 'system';
    else if ((m = h.match(/^#\/editor\/([^\/]+)/))) name = 'editor:' + decodeURIComponent(m[1]);
    var found = false;
    views.forEach(function(v){ var on = v.getAttribute('data-view') === name; v.hidden = !on; found = found || on; });
    if (!found) { name = 'team'; document.querySelector('[data-view="team"]').hidden = false; }
    document.querySelectorAll('.nav a').forEach(function(a){
      if (a.getAttribute('data-nav') === (name === 'system' ? 'system' : 'team')) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    closeDrawer(true);
    var state = history.state;
    window.scrollTo(0, state && typeof state.atlasY === 'number' ? state.atlasY : 0);
    spy();
  }
  document.addEventListener('click', function(e){
    if (e.target.closest('a[href^="#"]')) saveScroll();   // the entry being left keeps its exact position
    var keep = e.target.closest('a[data-keep-hash]');
    if (keep) { keep.setAttribute('href', keep.getAttribute('href').split('#')[0] + location.hash); return; }
    var tab = e.target.closest('[data-tab]');
    if (tab) {
      var group = tab.closest('[data-tabs]');
      group.querySelectorAll('[data-tab]').forEach(function(t){
        var on = t === tab; t.setAttribute('aria-selected', on ? 'true' : 'false');
        var panel = document.getElementById(t.getAttribute('data-tab')); if (panel) panel.hidden = !on;
      });
      return;
    }
    var jump = e.target.closest('[data-jump]');
    if (jump) { var target = document.getElementById(jump.getAttribute('data-jump')); if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'}); return; }
    var filter = e.target.closest('[data-filter]');
    if (filter) { document.querySelectorAll('[data-filter]').forEach(function(f){ f.setAttribute('aria-pressed', f === filter ? 'true' : 'false'); }); applyFilter(); return; }
    var opener = e.target.closest('[data-drawer]');
    if (opener) { e.preventDefault(); openDrawer(opener.getAttribute('data-drawer'), opener); }
  });
  // Overview: search and status filter (a filter, never a ranking).
  var search = document.getElementById('editor-search');
  function applyFilter(){
    var q = (search && search.value || '').trim().toLowerCase();
    var active = document.querySelector('[data-filter][aria-pressed="true"]');
    var status = active ? active.getAttribute('data-filter') : 'all';
    var shown = 0;
    document.querySelectorAll('[data-editor-card]').forEach(function(c){
      var ok = (!q || c.getAttribute('data-search').indexOf(q) >= 0) && (status === 'all' || c.getAttribute('data-status') === status);
      c.hidden = !ok; if (ok) shown++;
    });
    var none = document.getElementById('no-match'); if (none) none.hidden = shown > 0;
  }
  if (search) search.addEventListener('input', applyFilter);
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') closeDrawer();
    if (e.key === '/' && search && !search.closest('[hidden]') && document.activeElement.tagName !== 'INPUT') { e.preventDefault(); search.focus(); }
  });
  // Evidence drawer: content comes from a <template> next to the claim that opened it.
  var body = drawer.querySelector('.body'), title = drawer.querySelector('h2'), last = null;
  function openDrawer(id, trigger){
    var tpl = document.getElementById(id); if (!tpl) return;
    document.querySelectorAll('.mk.is-selected').forEach(function(m){ m.classList.remove('is-selected'); });
    if (trigger.classList.contains('mk')) trigger.classList.add('is-selected');
    title.textContent = tpl.getAttribute('data-title') || '';
    body.innerHTML = ''; body.appendChild(tpl.content.cloneNode(true)); body.scrollTop = 0;
    body.querySelectorAll('iframe[data-report]').forEach(function(f){ f.srcdoc = reports[f.getAttribute('data-report')] || ''; });
    last = trigger; document.body.classList.add('drawer-open'); drawer.setAttribute('aria-hidden', 'false'); drawer.querySelector('.x').focus();
  }
  // A route change closes the evidence drawer and empties it, so evidence from one page never sits over another
  // (ATLAS-MOBILE-003); focus then stays with the new page instead of returning to a trigger that is now hidden.
  function closeDrawer(routeChange){
    if (!document.body.classList.contains('drawer-open')) return;
    document.body.classList.remove('drawer-open'); drawer.setAttribute('aria-hidden', 'true');
    document.querySelectorAll('.mk.is-selected').forEach(function(m){ m.classList.remove('is-selected'); });
    if (routeChange === true) { body.innerHTML = ''; title.textContent = ''; last = null; return; }
    if (last) last.focus();
  }
  drawer.querySelector('.x').addEventListener('click', function(){ closeDrawer(); });
  document.querySelector('.scrim').addEventListener('click', function(){ closeDrawer(); });
  // Profile: highlight the section in view in the sticky section bar.
  var observer = null;
  function spy(){
    if (observer) observer.disconnect();
    var view = document.querySelector('[data-view^="editor:"]:not([hidden])'); if (!view || !('IntersectionObserver' in window)) return;
    var buttons = view.querySelectorAll('.jump [data-jump]');
    observer = new IntersectionObserver(function(entries){
      entries.forEach(function(en){ if (!en.isIntersecting) return;
        buttons.forEach(function(b){ b.setAttribute('aria-current', b.getAttribute('data-jump') === en.target.id ? 'true' : 'false'); }); });
    }, {rootMargin: '-130px 0px -60% 0px'});
    view.querySelectorAll('section[id]').forEach(function(s){ observer.observe(s); });
  }
  window.addEventListener('hashchange', route); route();
})();
"""
