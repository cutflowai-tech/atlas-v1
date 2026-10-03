"""Static assets of the reasoning-first dashboard (Phase 16), served by ``web_app`` from these constants.

They are external files (``/reasoning/assets/…``) so the pages can run under a strict Content-Security-Policy with no inline script or
style. The script does two presentation things only: it submits ``form[data-json]`` forms as JSON with the ``X-Atlas-CSRF`` header to the
management API (the server enforces every rule), and it opens a collapsed section that a link points into. It reads no reasoning data,
computes nothing and writes messages with ``textContent`` only.
"""

from __future__ import annotations

CSS = r"""
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#5b5b57;--line:#d9d8d2;--focus:#1a56db;--atlas:#2f4f8a;--mgmt:#7a4b00;--evid:#1f6b4f;
--warn-bg:#fff4d6;--warn-ink:#5c4300;--bad:#9b1c1c;font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Arabic",Tahoma,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.55;font-size:16px}
a{color:var(--atlas)}
a:focus-visible,button:focus-visible,summary:focus-visible,textarea:focus-visible,input:focus-visible,select:focus-visible,[tabindex]:focus-visible{
outline:3px solid var(--focus);outline-offset:2px;border-radius:2px}
.rv-skip{position:absolute;inset-inline-start:-9999px;top:0;background:var(--panel);padding:8px 12px;z-index:10}
.rv-skip:focus{inset-inline-start:8px}
.rv-visually-hidden{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.rv-top{background:var(--panel);border-block-end:1px solid var(--line)}
.rv-nav{max-width:1100px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center}
.rv-brand{font-weight:700;text-decoration:none;color:var(--ink)}
.rv-lang{margin-inline-start:auto}
.rv-main{max-width:1100px;margin:0 auto;padding:16px}
.rv-main:focus{outline:none}
h1{font-size:1.6rem;line-height:1.25;margin:.4em 0}
h2{font-size:1.25rem;margin:1.4em 0 .5em}
h3{font-size:1.05rem;margin:1em 0 .35em}
h4{font-size:1rem;margin:.8em 0 .3em}
.rv-lede,.rv-muted{color:var(--muted)}
.rv-cards{list-style:none;padding:0;margin:0;display:grid;gap:14px}
.rv-card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;border-inline-start:6px solid var(--atlas)}
.rv-card[data-lifecycle=cooling]{border-inline-start-style:dashed}
.rv-card[data-lifecycle=resolved],.rv-card[data-lifecycle=superseded]{border-inline-start-color:var(--line)}
.rv-title{margin:.2em 0}
.rv-title a{text-decoration:none}
.rv-title a:hover{text-decoration:underline}
.rv-subject{margin:0;color:var(--muted);font-size:.9rem}
.rv-badges{display:flex;flex-wrap:wrap;gap:6px 10px;margin:.4em 0;align-items:center}
.rv-life,.rv-conf,.rv-ver,.rv-tag,.rv-updated{display:inline-flex;gap:4px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:1px 10px;
font-size:.85rem;background:var(--bg)}
.rv-life{font-weight:600}
.rv-life[data-lifecycle=new]{border-color:var(--atlas)}
.rv-life[data-lifecycle=updated]{border-color:var(--atlas);border-style:double}
.rv-life[data-lifecycle=cooling]{border-style:dashed}
.rv-life[data-lifecycle=resolved],.rv-life[data-lifecycle=superseded]{color:var(--muted)}
.rv-life-help{display:block;width:100%;font-size:.85rem;color:var(--muted)}
.rv-mark{font-size:.9em}
.rv-k{color:var(--muted);font-weight:400}
.rv-summary{font-size:1.02rem}
.rv-links{display:flex;flex-wrap:wrap;gap:6px 16px;margin:.5em 0 0}
.rv-notices{list-style:none;padding:0;margin:.5em 0;display:grid;gap:6px}
.rv-notice,.rv-banner{background:var(--warn-bg);color:var(--warn-ink);border:1px solid #e9cf8a;border-radius:8px;padding:8px 12px;margin:.5em 0}
.rv-notice::before{content:"ⓘ ";}
.rv-ok{color:var(--evid)}
.rv-error{color:var(--bad);font-weight:600}
.rv-empty,.rv-unavailable{color:var(--muted);font-style:italic}
.rv-src{border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:14px 0;background:var(--panel)}
.rv-src-atlas_reasoning{border-inline-start:6px solid var(--atlas)}
.rv-src-management_context{border-inline-start:6px solid var(--mgmt)}
.rv-src-deterministic_evidence{border-inline-start:6px solid var(--evid)}
.rv-src-title{margin-top:.2em}
.rv-src-label{font-size:.85rem;font-weight:600;letter-spacing:.02em;color:var(--muted);margin-top:0}
.rv-claims,.rv-list{padding-inline-start:1.2em}
.rv-claims>li{margin-block-end:.6em}
.rv-claim{margin:0}
.rv-refs{margin:.2em 0;font-size:.85rem;display:flex;flex-wrap:wrap;gap:4px 8px}
.rv-ref-broken{color:var(--bad)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.85em;overflow-wrap:anywhere;unicode-bidi:isolate}
.rv-dl{display:grid;grid-template-columns:minmax(140px,max-content) 1fr;gap:4px 14px;margin:.5em 0}
.rv-dl>div{display:contents}
.rv-dl dt{color:var(--muted)}
.rv-dl dd{margin:0;min-width:0}
details{margin:.5em 0}
summary{cursor:pointer;font-weight:600;padding:4px 0}
.rv-finding{border:1px solid var(--line);border-radius:8px;padding:6px 12px;background:var(--bg)}
.rv-side{font-weight:600}
.rv-scroll{overflow-x:auto;max-width:100%}
.rv-table{border-collapse:collapse;width:100%;min-width:560px;font-size:.88rem;margin:.4em 0}
.rv-records{min-width:1100px}
.rv-records code{overflow-wrap:normal;word-break:normal}
.rv-table th,.rv-table td{border:1px solid var(--line);padding:4px 8px;text-align:start;vertical-align:top}
.rv-table th{background:var(--bg)}
.rv-crumbs{font-size:.9rem;margin-block-end:.5em}
.rv-diagnostics{border-block-start:1px solid var(--line);margin-top:2em}
.manager-interpretation,.atlas-questions,.teach-atlas{margin:.6em 0}
.mi-label,.qa-label,.ta-label{font-size:.85rem;color:var(--mgmt);font-weight:600}
.mi-note,.qa-question{border:1px solid var(--line);border-radius:8px;padding:6px 10px;margin:.4em 0;list-style:none}
.mi-notes,.qa-list,.qa-answers{padding:0}
.mi-meta,.qa-meta,.qa-state,.qa-why{font-size:.85rem;color:var(--muted)}
.qa-conflict,.ta-flag{color:var(--bad);font-weight:600}
form{display:grid;gap:4px;margin:.4em 0;max-width:640px}
label{font-size:.9rem}
textarea,input,select{font:inherit;padding:6px;border:1px solid #9a998f;border-radius:6px;width:100%}
input[type=checkbox]{width:auto}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--atlas);background:var(--atlas);color:#fff;cursor:pointer;justify-self:start}
.qa-dismiss button,.ta-actions button{background:var(--panel);color:var(--atlas)}
.rv-form-status{font-size:.85rem}
.rv-form-status[data-state=failed]{color:var(--bad)}
.rv-exec{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:14px 0;border-inline-start:6px solid var(--ink)}
.rv-exec-section h3{margin-top:1.1em}
.rv-exec-statements{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.rv-exec-statement{border:1px solid var(--line);border-radius:8px;padding:8px 12px;background:var(--bg)}
.rv-exec-text{margin:0 0 .3em;font-size:1.02rem}
.rv-exec-based{font-size:.85rem;margin:.3em 0 .1em}
.rv-exec-refs{padding-inline-start:1.2em;margin:.2em 0;font-size:.9rem}
.rv-exec-ref{margin:.25em 0}
.rv-exec-ref>a,.rv-exec-ref .rv-ver{margin-inline-end:8px}
.rv-exec-status{display:inline-flex;flex-wrap:wrap;gap:4px 8px;margin-inline-start:4px}
.rv-exec-state{color:var(--warn-ink);font-size:.85rem}
@media (max-width:640px){.rv-dl{grid-template-columns:1fr}.rv-dl dt{margin-top:.4em}h1{font-size:1.35rem}.rv-lang{margin-inline-start:0}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""

JS = r"""
(function () {
  "use strict";
  var body = document.body;
  function message(key) { return body.getAttribute("data-msg-" + key) || ""; }
  function status(form) {
    var node = form.querySelector(".rv-form-status");
    if (!node) {
      node = document.createElement("p");
      node.className = "rv-form-status";
      node.setAttribute("role", "status");
      node.setAttribute("aria-live", "polite");
      form.appendChild(node);
    }
    return node;
  }
  function payload(form) {
    var data = {};
    Array.prototype.forEach.call(form.elements, function (field) {
      if (!field.name || field.disabled) { return; }
      if (field.type === "checkbox") { data[field.name] = field.checked; return; }
      if (field.value === "") { return; }
      data[field.name] = field.getAttribute("data-type") === "integer" ? parseInt(field.value, 10) : field.value;
    });
    return data;
  }
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.matches || !form.matches("form[data-json]")) { return; }
    event.preventDefault();
    var node = status(form);
    node.removeAttribute("data-state");
    node.textContent = message("saving");
    var buttons = form.querySelectorAll("button");
    Array.prototype.forEach.call(buttons, function (b) { b.disabled = true; });
    fetch(form.getAttribute("action"), {
      method: form.getAttribute("data-method") || "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-Atlas-CSRF": form.getAttribute("data-csrf") || ""},
      body: JSON.stringify(payload(form))
    }).then(function (response) {
      if (response.ok) { node.textContent = message("saved"); window.location.reload(); return; }
      return response.json().catch(function () { return {}; }).then(function (error) {
        node.setAttribute("data-state", "failed");
        node.textContent = message("failed") + (error && error.error ? " (" + String(error.error) + ")" : "");
        Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      });
    }).catch(function () {
      node.setAttribute("data-state", "failed");
      node.textContent = message("failed");
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
    });
  });
  function reveal() {
    var id = "";
    try { id = decodeURIComponent(window.location.hash.slice(1)); } catch (error) { return; }
    var target = id ? document.getElementById(id) : null;
    if (!target) { return; }
    for (var node = target.parentElement; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") { node.open = true; }
    }
    target.scrollIntoView();
    if (target.getAttribute("tabindex") !== null) { target.focus(); }
  }
  window.addEventListener("hashchange", reveal);
  reveal();
}());
"""
