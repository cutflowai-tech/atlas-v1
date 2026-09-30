await wait(350);
const out = {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, clipped: [], overlap: []};
const shown = el => el.offsetParent !== null || getComputedStyle(el).position === 'fixed';
const scope = document.querySelectorAll('.v-page *, #vprofile *, [data-view="system"]:not([hidden]) .v-rule *, [data-view="system"]:not([hidden]) .v-dec *, header.top *');
for (const el of scope) {
  if (!shown(el)) continue;
  const cs = getComputedStyle(el);
  const hides = /hidden|clip/.test(cs.overflowX) || cs.textOverflow === 'ellipsis';
  if (hides && el.scrollWidth > el.clientWidth + 1) out.clipped.push((el.className || el.tagName) + ': ' + el.textContent.trim().slice(0, 40));
  if (el.children.length) continue;
  const r = el.getBoundingClientRect();
  if (r.width > 0 && (r.right > document.documentElement.clientWidth + 1 || r.left < -1) && cs.position !== 'fixed' && !el.closest('#vprofile[aria-hidden="true"]'))
    out.clipped.push('off-screen ' + (el.className || el.tagName) + ': ' + el.textContent.trim().slice(0, 40));
}
for (const group of document.querySelectorAll('.v-grid, .v-kpis, .v-rail-list, .v-prof-metrics, .v-md-decisions, .v-layout')) {
  if (!shown(group)) continue;
  const items = [...group.children].filter(shown).map(e => e.getBoundingClientRect());
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j];
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (w > 1 && h > 1) out.overlap.push(group.className + ' #' + i + '/#' + j);
  }
}
out.clipped = out.clipped.slice(0, 8); out.overlap = out.overlap.slice(0, 8);
return out;
