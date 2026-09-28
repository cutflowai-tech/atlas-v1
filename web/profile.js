// Editor Profile view model and renderer.
//
// This module only fetches and displays the EditorProfile contract
// (contracts/editor-profile.schema.json). It never derives, aggregates or
// re-evaluates a metric: every value shown comes verbatim from the API
// response. Grouping speed metrics by their canonical Video Type and
// converting seconds to hours/minutes for display are the only
// transformations applied.

export const CONTRACT_VERSION = "1.0.0";

const EDITOR_ID_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;
const PROFILE_KEYS = ["contract_version", "subject_type", "editor", "work_cycles", "metrics", "generated_at"];
const EDITOR_KEYS = ["editor_id", "monday_person_id", "display_name", "mapping_version", "resolution"];
const METRIC_KINDS = ["speed", "deadline", "quality"];

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const esc = escapeHtml;

export function profileUrl(editorId) {
  return `/api/editors/${encodeURIComponent(editorId)}`;
}

// Structural checks only: the UI refuses to display a response that does not
// look like the EditorProfile contract rather than guessing at missing parts.
export function contractProblems(body, requestedEditorId) {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return ["Response is not a JSON object."];
  }
  const problems = [];
  for (const key of PROFILE_KEYS) {
    if (!(key in body)) problems.push(`Missing required field "${key}".`);
  }
  if ("contract_version" in body && body.contract_version !== CONTRACT_VERSION) {
    problems.push(`Unsupported contract_version "${body.contract_version}" (expected ${CONTRACT_VERSION}).`);
  }
  if ("subject_type" in body && body.subject_type !== "editor") {
    problems.push(`subject_type must be "editor".`);
  }
  const editor = body.editor;
  if (editor && typeof editor === "object") {
    for (const key of EDITOR_KEYS) {
      if (typeof editor[key] !== "string" || editor[key] === "") problems.push(`editor.${key} is missing.`);
    }
    if (editor.resolution !== undefined && editor.resolution !== "canonical_monday_id") {
      problems.push("editor.resolution is not canonical_monday_id.");
    }
    if (requestedEditorId && editor.editor_id !== undefined && editor.editor_id !== requestedEditorId) {
      problems.push(`Response is for editor "${editor.editor_id}", not the requested "${requestedEditorId}".`);
    }
  } else if ("editor" in body) {
    problems.push("editor must be an object.");
  }
  if ("work_cycles" in body && !Array.isArray(body.work_cycles)) problems.push("work_cycles must be an array.");
  const metrics = body.metrics;
  if (metrics && typeof metrics === "object") {
    for (const kind of METRIC_KINDS) {
      if (!Array.isArray(metrics[kind])) problems.push(`metrics.${kind} must be an array.`);
    }
  } else if ("metrics" in body) {
    problems.push("metrics must be an object.");
  }
  return problems;
}

// Loads one profile and returns a view state. Never throws.
export async function loadProfile(editorId, fetchImpl) {
  const id = (editorId ?? "").trim();
  if (!id) return { status: "missing_id" };
  if (!EDITOR_ID_PATTERN.test(id)) return { status: "invalid_id", editorId: id };

  let response;
  try {
    response = await fetchImpl(profileUrl(id), { headers: { Accept: "application/json" } });
  } catch (error) {
    return { status: "error", editorId: id, message: `Network error: ${error?.message ?? error}` };
  }
  const dataMode = response.headers?.get?.("X-Atlas-Data-Mode") ?? null;
  if (response.status === 404) return { status: "not_found", editorId: id, dataMode };
  if (!response.ok) {
    return { status: "error", editorId: id, dataMode, message: `API responded with HTTP ${response.status}.` };
  }
  let body;
  try {
    body = await response.json();
  } catch {
    return { status: "error", editorId: id, dataMode, message: "API response was not valid JSON." };
  }
  const problems = contractProblems(body, id);
  if (problems.length) return { status: "contract_error", editorId: id, dataMode, problems };
  return { status: "ready", editorId: id, dataMode, profile: body };
}

// ---------------------------------------------------------------- formatting

export function formatDuration(seconds) {
  if (!Number.isInteger(seconds) || seconds < 0) return "Not provided";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const human = `${hours}h ${String(minutes).padStart(2, "0")}m`;
  return `${human} (${seconds.toLocaleString("en-US")} s)`;
}

function text(value, fallback = "Not provided") {
  return value === null || value === undefined || value === "" ? `<span class="unknown">${esc(fallback)}</span>` : esc(value);
}

function timestamp(value, fallback = "Not provided") {
  // Timestamps are displayed exactly as Monday/the API supplied them (UTC).
  return value ? `<time datetime="${esc(value)}">${esc(value)}</time>` : `<span class="unknown">${esc(fallback)}</span>`;
}

function literal(value) {
  return typeof value === "string" ? esc(value) : `<code>${esc(JSON.stringify(value))}</code>`;
}

function list(values) {
  if (!Array.isArray(values) || values.length === 0) return `<span class="unknown">None recorded</span>`;
  return values.map((value) => `<code>${esc(value)}</code>`).join(", ");
}

function keyValues(object, emptyText) {
  if (!object || typeof object !== "object" || Object.keys(object).length === 0) {
    return `<span class="unknown">${esc(emptyText)}</span>`;
  }
  const rows = Object.entries(object)
    .map(([key, value]) => `<tr><th scope="row">${esc(key)}</th><td>${literal(value)}</td></tr>`)
    .join("");
  return `<table class="kv">${rows}</table>`;
}

// ------------------------------------------------------------------ evidence

function evidenceProblem(evidence) {
  if (!evidence || typeof evidence !== "object") return "No source evidence was supplied.";
  if (evidence.source !== "monday") return `Evidence source "${evidence.source ?? "unknown"}" is not Monday.`;
  if (!evidence.monday_item_id || !evidence.monday_board_id) return "Evidence does not reference a Monday board item.";
  return null;
}

function renderEvidence(evidence, label) {
  return `<details class="evidence" data-evidence-for="${esc(label)}">
  <summary>Source evidence <span class="muted">(Monday item ${esc(evidence.monday_item_id)})</span></summary>
  <dl>
    <dt>Source</dt><dd>${esc(evidence.source)}</dd>
    <dt>Monday board</dt><dd><code>${esc(evidence.monday_board_id)}</code></dd>
    <dt>Monday item</dt><dd><code>${esc(evidence.monday_item_id)}</code></dd>
    <dt>Columns</dt><dd>${list(evidence.column_ids)}</dd>
    <dt>Events</dt><dd>${list(evidence.event_ids)}</dd>
    <dt>Source timestamps</dt><dd>${list(evidence.source_timestamps)}</dd>
    <dt>Source values</dt><dd>${keyValues(evidence.source_values, "None recorded")}</dd>
    <dt>Rule version</dt><dd><code>${text(evidence.rule_version)}</code></dd>
    <dt>Calculated at</dt><dd>${timestamp(evidence.calculated_at)}</dd>
  </dl>
</details>`;
}

// A metric without Monday evidence is withheld rather than displayed.
function withEvidence(metric, label, body) {
  const problem = evidenceProblem(metric.evidence);
  if (problem) {
    return `<div class="metric withheld" role="note"><strong>Value withheld.</strong> ${esc(problem)}</div>`;
  }
  return `${body}\n${renderEvidence(metric.evidence, label)}`;
}

// ------------------------------------------------------------------ sections

function renderQuality(metrics) {
  const intro = `<p class="rule">Quality is the approved Monday Performance Label, shown verbatim. Revisions are context only and never change it.</p>`;
  if (metrics.length === 0) {
    return `${intro}<p class="empty" data-empty="quality">No approved Monday Performance Label has been recorded for this editor.</p>`;
  }
  const items = metrics
    .map((metric, index) => {
      const label = `quality-${index}`;
      const body = `<div class="metric-head"><span class="label-value">${text(metric.performance_label)}</span>
  <span class="muted">Item <code>${text(metric.evidence?.monday_item_id)}</code></span></div>
  <dl class="facts">
    <dt>Label column</dt><dd><code>${text(metric.label_column_id)}</code></dd>
    <dt>Label mapping version</dt><dd><code>${text(metric.label_mapping_version)}</code></dd>
    <dt>Revision context <span class="tag">context only</span></dt><dd>${keyValues(metric.revision_context, "No revision context")}</dd>
  </dl>`;
      return `<li class="metric" data-metric="${label}">${withEvidence(metric, label, body)}</li>`;
    })
    .join("\n");
  return `${intro}<ul class="metrics">${items}</ul>`;
}

function renderSpeed(metrics) {
  const intro = `<p class="rule">Duration runs from <em>In Progress</em> to <em>Ready For Approval</em>. Cohort medians compare only within the same canonical Video Type.</p>`;
  if (metrics.length === 0) {
    return `${intro}<p class="empty" data-empty="speed">No speed metrics are available for this editor.</p>`;
  }
  const groups = new Map();
  metrics.forEach((metric, index) => {
    const key = typeof metric.video_type === "string" && metric.video_type ? metric.video_type : null;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ metric, index });
  });
  const keys = [...groups.keys()].sort((a, b) => (a === null ? 1 : b === null ? -1 : a.localeCompare(b)));
  return (
    intro +
    keys
      .map((videoType) => {
        const rows = groups
          .get(videoType)
          .map(({ metric, index }) => {
            const label = `speed-${index}`;
            let cohort;
            if (metric.cohort_video_type !== metric.video_type) {
              cohort = `<span class="violation">Cohort Video Type "${esc(metric.cohort_video_type ?? "unknown")}" does not match; comparison hidden.</span>`;
            } else if (Number.isInteger(metric.cohort_median_seconds)) {
              cohort = `${formatDuration(metric.cohort_median_seconds)} <span class="muted">(${esc(metric.cohort_video_type)} cohort)</span>`;
            } else {
              cohort = `<span class="unknown">Not available for this Video Type cohort</span>`;
            }
            const body = `<dl class="facts">
    <dt>Monday item</dt><dd><code>${text(metric.evidence?.monday_item_id)}</code></dd>
    <dt>Duration</dt><dd class="value">${formatDuration(metric.duration_seconds)}</dd>
    <dt>Same-type cohort median</dt><dd>${cohort}</dd>
  </dl>`;
            return `<li class="metric" data-metric="${label}">${withEvidence(metric, label, body)}</li>`;
          })
          .join("\n");
        const heading = videoType === null ? `<span class="violation">Video Type missing</span>` : esc(videoType);
        return `<section class="video-type" data-video-type="${esc(videoType ?? "")}">
  <h3>Video Type: ${heading}</h3>
  <ul class="metrics">${rows}</ul>
</section>`;
      })
      .join("\n")
  );
}

const DEADLINE_RESULTS = { on_time: "On time", late: "Late" };

function renderDeadline(metrics, workCycles) {
  const intro = `<p class="rule">On time means <em>Ready For Approval</em> at or before the Monday <em>Requested ETA</em>. A missing ETA is never estimated.</p>`;
  const missingEta = workCycles.filter((cycle) => cycle && cycle.requested_eta === null);
  const missingNote = missingEta.length
    ? `<div class="not-evaluated" data-not-evaluated="deadline"><p>Not evaluated — Requested ETA missing in Monday:</p><ul>${missingEta
        .map((cycle) => `<li>Cycle <code>${text(cycle.cycle_id)}</code>, item <code>${text(cycle.monday_item_id)}</code></li>`)
        .join("")}</ul></div>`
    : "";
  if (metrics.length === 0) {
    return `${intro}<p class="empty" data-empty="deadline">No deadline metrics are available for this editor.</p>${missingNote}`;
  }
  const items = metrics
    .map((metric, index) => {
      const label = `deadline-${index}`;
      const result = DEADLINE_RESULTS[metric.result];
      const badge = result
        ? `<span class="result result-${esc(metric.result)}">${result}</span>`
        : `<span class="violation">Unrecognized result "${esc(metric.result ?? "missing")}"</span>`;
      const body = `<div class="metric-head">${badge} <span class="muted">Item <code>${text(metric.evidence?.monday_item_id)}</code></span></div>
  <dl class="facts">
    <dt>Ready For Approval</dt><dd>${timestamp(metric.ready_for_approval_at)}</dd>
    <dt>Requested ETA</dt><dd>${timestamp(metric.requested_eta)}</dd>
  </dl>`;
      return `<li class="metric" data-metric="${label}">${withEvidence(metric, label, body)}</li>`;
    })
    .join("\n");
  return `${intro}<ul class="metrics">${items}</ul>${missingNote}`;
}

function renderWorkCycles(workCycles) {
  const intro = `<p class="rule">Revision counts are shown for context only. They are not a quality penalty and feed no metric.</p>`;
  if (workCycles.length === 0) {
    return `${intro}<p class="empty" data-empty="work_cycles">No completed In Progress → Ready For Approval work cycles.</p>`;
  }
  const rows = workCycles
    .map(
      (cycle) => `<tr data-cycle="${esc(cycle.cycle_id)}">
  <td><code>${text(cycle.cycle_id)}</code></td>
  <td><code>${text(cycle.monday_item_id)}</code></td>
  <td>${text(cycle.video_type)}</td>
  <td>${timestamp(cycle.in_progress_at)}</td>
  <td>${timestamp(cycle.ready_for_approval_at)}</td>
  <td>${timestamp(cycle.requested_eta, "Missing in Monday")}</td>
  <td>${keyValues(cycle.revision_context, "None recorded")}</td>
</tr>`,
    )
    .join("\n");
  return `${intro}<div class="table-wrap"><table class="cycles">
<thead><tr><th>Cycle</th><th>Monday item</th><th>Video Type</th><th>In Progress</th><th>Ready For Approval</th><th>Requested ETA</th><th>Revision context</th></tr></thead>
<tbody>${rows}</tbody>
</table></div>`;
}

function dataModeBanner(dataMode) {
  if (dataMode === "fixture") {
    return `<div class="banner fixture" role="note" data-mode="fixture"><strong>FIXTURE DATA</strong> — served by the Atlas mock API for development. Not real Monday data.</div>`;
  }
  if (dataMode) {
    return `<div class="banner" role="note" data-mode="${esc(dataMode)}">Data mode: ${esc(dataMode)}</div>`;
  }
  return `<div class="banner unknown-mode" role="note" data-mode="unknown">Data mode not declared by the API.</div>`;
}

function statusPanel(kind, title, detail) {
  return `<section class="state state-${kind}" data-state="${kind}" role="${kind === "loading" ? "status" : "alert"}">
  <h2>${esc(title)}</h2>
  ${detail}
</section>`;
}

export function renderView(state) {
  switch (state.status) {
    case "loading":
      return statusPanel("loading", "Loading editor profile…", `<p>Requesting <code>${esc(profileUrl(state.editorId ?? ""))}</code>.</p>`);
    case "missing_id":
      return statusPanel("missing_id", "No editor selected", `<p>Enter a canonical editor ID to load a profile.</p>`);
    case "invalid_id":
      return statusPanel("invalid_id", "Invalid editor ID", `<p><code>${esc(state.editorId)}</code> is not a valid canonical editor ID.</p>`);
    case "not_found":
      return dataModeBanner(state.dataMode) + statusPanel("not_found", "Editor not found", `<p>No profile exists for editor <code>${esc(state.editorId)}</code>.</p>`);
    case "error":
      return (
        (state.dataMode !== undefined ? dataModeBanner(state.dataMode) : "") +
        statusPanel("error", "Could not load editor profile", `<p>${esc(state.message)}</p><p>No values are shown because none were received.</p>`)
      );
    case "contract_error":
      return (
        dataModeBanner(state.dataMode) +
        statusPanel(
          "contract_error",
          "Profile does not match the EditorProfile contract",
          `<p>The response was rejected and nothing from it is displayed.</p><ul>${state.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`,
        )
      );
    case "ready":
      return renderProfile(state.profile, state.dataMode);
    default:
      return statusPanel("error", "Unknown view state", `<p>${esc(state.status)}</p>`);
  }
}

// ai_annotation is intentionally never rendered: AI is not a source of truth.
export function renderProfile(profile, dataMode) {
  const { editor, metrics } = profile;
  const workCycles = profile.work_cycles;
  return `${dataModeBanner(dataMode)}
<article class="profile" data-state="ready" data-editor-id="${esc(editor.editor_id)}">
<header class="identity">
  <h2>${esc(editor.display_name)}</h2>
  <dl class="facts">
    <dt>Editor ID</dt><dd><code>${esc(editor.editor_id)}</code></dd>
    <dt>Monday person ID</dt><dd><code>${esc(editor.monday_person_id)}</code></dd>
    <dt>Identity mapping</dt><dd><code>${esc(editor.mapping_version)}</code> (${esc(editor.resolution)})</dd>
    <dt>Profile generated</dt><dd>${timestamp(profile.generated_at)}</dd>
  </dl>
</header>
<section class="panel" data-section="quality"><h2>Quality</h2>
${renderQuality(metrics.quality)}
</section>
<section class="panel" data-section="speed"><h2>Speed by Video Type</h2>
${renderSpeed(metrics.speed)}
</section>
<section class="panel" data-section="deadline"><h2>Deadline</h2>
${renderDeadline(metrics.deadline, workCycles)}
</section>
<section class="panel" data-section="revisions"><h2>Work cycles &amp; revision context</h2>
${renderWorkCycles(workCycles)}
</section>
<footer class="provenance">Source of truth: Monday.com. Each metric is shown separately with its source evidence; metrics are not combined into an overall rating.</footer>
</article>`;
}
