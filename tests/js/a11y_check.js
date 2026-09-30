// Accessibility checks run in the page (redesign T6.2); the accessible-name checks use Chrome's own accessibility tree (see a11y.py).
// Serious issues only, in the sense of axe-core's "serious"/"critical" impacts: text contrast (WCAG 2 AA), focusable content hidden from
// assistive technology, broken ARIA references, images without a text alternative, the document language, one h1 per shown view.
await wait(350);
const issues = [];
const shown = el => { const cs = getComputedStyle(el); return el.getClientRects().length > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
const label = el => (el.id ? '#' + el.id : el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : ''));

// --- contrast: every shown element with its own text
const rgba = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
const over = (top, under) => ({r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1});
function background(el) {
  const layers = [];
  for (let node = el; node; node = node.parentElement) {
    const cs = getComputedStyle(node);
    if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;          // an image or gradient: not computable, skipped
    const c = rgba(cs.backgroundColor);
    if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
  }
  let base = {r: 255, g: 255, b: 255, a: 1};
  for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
  return base;
}
function opacity(el) { let o = 1; for (let n = el; n; n = n.parentElement) o *= Number(getComputedStyle(n).opacity); return o; }
for (const el of document.querySelectorAll('body *')) {
  if (!shown(el) || el.closest('svg, script, style, template')) continue;
  const text = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  if (!text) continue;
  const cs = getComputedStyle(el), bg = background(el), fg = rgba(cs.color);
  if (!bg || !fg) continue;
  const color = over({...fg, a: fg.a * opacity(el)}, bg);
  const [l1, l2] = [lum(color), lum(bg)].sort((a, b) => b - a);
  const ratio = (l1 + 0.05) / (l2 + 0.05);
  const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
  const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
  if (ratio + 0.005 < need) issues.push(`contrast ${ratio.toFixed(2)} < ${need}: ${label(el)} "${text.slice(0, 30)}"`);
}

// --- focusable content inside aria-hidden (hidden from assistive technology but reachable by keyboard)
const focusable = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, summary, [tabindex]:not([tabindex="-1"])';
for (const el of document.querySelectorAll(focusable)) {
  if (shown(el) && el.closest('[aria-hidden="true"]') && !el.closest('[inert]')) issues.push('aria-hidden focusable: ' + label(el));
}
// --- ARIA references and unique IDs they point to
for (const el of document.querySelectorAll('[aria-labelledby], [aria-describedby], label[for]')) {
  const ids = (el.getAttribute('aria-labelledby') || el.getAttribute('aria-describedby') || el.getAttribute('for') || '').split(/\s+/).filter(Boolean);
  for (const id of ids) {
    const found = document.querySelectorAll('#' + CSS.escape(id)).length;
    if (found !== 1 && shown(el)) issues.push(`reference ${id} found ${found} times: ${label(el)}`);
  }
}
// --- images
for (const img of document.querySelectorAll('img')) if (!img.hasAttribute('alt') && shown(img)) issues.push('img without alt: ' + label(img));
// --- document language, one h1 in the shown view
if (!document.documentElement.lang || !document.documentElement.dir) issues.push('html lang/dir missing');
const h1 = [...document.querySelectorAll('h1')].filter(shown).length;
if (h1 !== 1 && !document.body.classList.contains('profile-open')) issues.push(`${h1} shown h1`);
return issues;
