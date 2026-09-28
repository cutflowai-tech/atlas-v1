const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const value = v => v === null || v === undefined ? 'Unknown / not supplied' : escape(typeof v === 'object' ? JSON.stringify(v, null, 2) : v);
const field = (label, v) => `<div class="field"><dt>${escape(label)}</dt><dd>${value(v)}</dd></div>`;
const present = v => typeof v === 'string' && v.length > 0;
function evidenceValid(e) {
  return e?.source === 'monday' && ['monday_board_id','monday_item_id','rule_version','calculated_at'].every(k => present(e[k])) && ['column_ids','event_ids','source_timestamps'].every(k => Array.isArray(e[k]) && e[k].length && e[k].every(present)) && e.source_values && typeof e.source_values === 'object' && Object.keys(e.source_values).length;
}
function evidence(e) {
  return `<details><summary>Source evidence · ${escape(e.monday_item_id)}</summary><dl>${Object.entries(e).map(([k,v]) => field(k,v)).join('')}</dl></details>`;
}
function metric(m, kind, id) {
  if (m?.contract_version !== '1.0.0' || m.metric_name !== kind || m.editor_id !== id || !evidenceValid(m.evidence)) return '<article>Metric unavailable: missing or unsupported source evidence or identity.</article>';
  let fields;
  if (kind === 'speed') {
    if (!present(m.video_type) || m.video_type !== m.cohort_video_type) return '<article>Speed unavailable: canonical Video Type cohort mismatch.</article>';
    fields = [['Duration (seconds)',m.duration_seconds],['Cohort Video Type',m.cohort_video_type],['Cohort median (seconds)',m.cohort_median_seconds]];
  } else if (kind === 'quality') {
    if (!present(m.label_mapping_version) || !present(m.label_column_id) || !present(m.performance_label)) return '<article>Quality unavailable: missing Monday label mapping.</article>';
    fields = [['Monday Performance Label',m.performance_label],['Label column ID',m.label_column_id],['Label mapping version',m.label_mapping_version],['Revision context — no quality penalty',m.revision_context]];
  } else {
    if (!present(m.requested_eta) || !['on_time','late'].includes(m.result)) return '<article>Deadline unavailable: missing ETA or unsupported result.</article>';
    fields = [['API deadline result',m.result],['Ready For Approval',m.ready_for_approval_at],['Requested ETA',m.requested_eta]];
  }
  return `<article><dl>${fields.map(([k,v])=>field(k,v)).join('')}</dl>${evidence(m.evidence)}</article>`;
}
export function renderProfile(p, id) {
  if (p?.contract_version !== '1.0.0' || p.subject_type !== 'editor' || p.editor?.editor_id !== id || p.editor.resolution !== 'canonical_monday_id' || !present(p.editor.mapping_version) || !present(p.editor.monday_person_id) || !p.metrics || !['quality','speed','deadline'].every(k=>Array.isArray(p.metrics[k])) || !Array.isArray(p.work_cycles)) throw new Error('Unsupported profile contract or editor identity');
  const section = (title, text, body) => `<section><h2>${title}</h2><p>${text}</p>${body}</section>`;
  const rows = k => p.metrics[k].map(m=>metric(m,k,id)).join('') || '<p class="empty">No metrics supplied.</p>';
  const groups = new Map();
  for (const m of p.metrics.speed) {
    const key = present(m?.video_type) ? m.video_type : 'Unknown Video Type';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  const speed = [...groups].map(([key,ms])=>`<h3>Video Type · ${escape(key)}</h3>${ms.map(m=>metric(m,'speed',id)).join('')}`).join('') || '<p class="empty">No speed metrics supplied.</p>';
  const cycles = p.work_cycles.filter(c=>c.editor_id === id).map(c=>`<article><dl>${[['Cycle ID',c.cycle_id],['Monday board ID',c.monday_board_id],['Monday item ID',c.monday_item_id],['In Progress event ID',c.in_progress_event_id],['Ready For Approval event ID',c.ready_for_approval_event_id],['Requested ETA',c.requested_eta],['Revision context — no quality penalty',c.revision_context]].map(([k,v])=>field(k,v)).join('')}</dl></article>`).join('');
  return `<header><p>EDITOR PROFILE</p><h1>${value(p.editor.display_name)}</h1><dl>${field('Canonical editor ID',id)}${field('Monday person ID',p.editor.monday_person_id)}${field('Identity mapping version',p.editor.mapping_version)}${field('Generated at',p.generated_at)}</dl></header>` + section('Quality','Approved Monday labels, supplied by the API.',rows('quality')) + section('Speed','In Progress → Ready For Approval. Benchmarks use the same canonical Video Type only.',speed) + section('Deadline','Ready For Approval ≤ Requested ETA. Missing ETA has no metric; no fallback is inferred.',rows('deadline')) + section('Revision context','Context only. Revisions never apply an automatic quality penalty.',cycles || '<p class="empty">No work-cycle context supplied.</p>');
}
const requests = new WeakMap();
export async function loadProfile(root, id, fetcher = globalThis.fetch) {
  const request = {};
  requests.set(root, request);
  root.setAttribute('aria-busy','true');
  root.innerHTML = '<p role="status">Loading editor profile…</p>';
  try {
    if (!present(id)) throw new Error('Missing editor ID');
    const response = await fetcher(`/api/editors/${encodeURIComponent(id)}`, {headers:{Accept:'application/json'}});
    if (!response.ok) throw new Error(`Profile request failed (${response.status})`);
    const profile = await response.json();
    if (requests.get(root) === request) root.innerHTML = renderProfile(profile, id);
  } catch {
    if (requests.get(root) === request) root.innerHTML = '<p role="alert">Editor profile unavailable. The request failed or the supplied profile is unsupported. No metrics are shown.</p>';
  } finally { if (requests.get(root) === request) root.setAttribute('aria-busy','false'); }
}
