import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { contractProblems, escapeHtml, formatDuration, loadProfile, renderView } from "../profile.js";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = (name) => JSON.parse(readFileSync(join(WEB, "mock", "editors", `${name}.json`), "utf8"));

function fakeFetch(status, body, headers = { "X-Atlas-Data-Mode": "fixture" }) {
  const calls = [];
  const impl = async (url) => {
    calls.push(url);
    return {
      status,
      ok: status >= 200 && status < 300,
      headers: new Headers(headers),
      json: async () => (typeof body === "string" ? JSON.parse(body) : structuredClone(body)),
    };
  };
  impl.calls = calls;
  return impl;
}

async function renderFor(profile, headers) {
  const state = await loadProfile(profile.editor.editor_id, fakeFetch(200, profile, headers));
  assert.equal(state.status, "ready");
  return renderView(state);
}

const count = (html, needle) => html.split(needle).length - 1;

test("fetches /api/editors/<editor_id> with the id URL-encoded", async () => {
  const fetchImpl = fakeFetch(200, fixture("editor-42"));
  await loadProfile("editor-42", fetchImpl);
  assert.deepEqual(fetchImpl.calls, ["/api/editors/editor-42"]);
});

test("displays quality labels verbatim with mapping version and evidence", async () => {
  const html = await renderFor(fixture("editor-42"));
  assert.match(html, /Meets Expectations/);
  assert.match(html, /Exceeds Expectations/);
  assert.match(html, /quality-label-v1/);
  assert.match(html, /data-evidence-for="quality-0"/);
  assert.match(html, /data-evidence-for="quality-1"/);
});

test("groups speed by canonical Video Type and shows the supplied same-type cohort median", async () => {
  const html = await renderFor(fixture("editor-42"));
  const longForm = html.indexOf('data-video-type="long-form"');
  const shortForm = html.indexOf('data-video-type="short-form"');
  assert.ok(longForm > -1 && shortForm > longForm, "video type groups are present and sorted");
  const shortSection = html.slice(shortForm);
  assert.equal(count(shortSection.split("</section>")[0], 'data-metric="speed-'), 2);
  assert.match(html, /2h 00m \(7,200 s\)/);
  assert.match(html, /2h 30m \(9,000 s\) <span class="muted">\(short-form cohort\)/);
  assert.match(html, /Not available for this Video Type cohort/, "null cohort median is shown as unavailable");
});

test("shows deadline results from the API and lists missing-ETA cycles as not evaluated", async () => {
  const html = await renderFor(fixture("editor-42"));
  assert.match(html, /result-on_time">On time/);
  assert.match(html, /result-late">Late/);
  assert.match(html, /Not evaluated — Requested ETA missing in Monday/);
  assert.match(html, /Cycle <code>cycle-103<\/code>/);
});

test("revision context is displayed as context only", async () => {
  const html = await renderFor(fixture("editor-42"));
  assert.match(html, /Revision counts are shown for context only/);
  assert.match(html, /data-cycle="cycle-102"[\s\S]*?<th scope="row">count<\/th><td><code>3<\/code>/);
  assert.match(html, /Revision context <span class="tag">context only<\/span>/);
});

test("every displayed metric has an expandable Monday evidence block", async () => {
  const profile = fixture("editor-42");
  const html = await renderFor(profile);
  const metricCount = profile.metrics.speed.length + profile.metrics.deadline.length + profile.metrics.quality.length;
  assert.equal(count(html, 'class="metric"'), metricCount);
  assert.equal(count(html, '<details class="evidence"'), metricCount);
  for (const event of ["event-1010", "event-1011", "event-1021", "event-1022"]) assert.match(html, new RegExp(event));
  assert.match(html, /speed-v1/);
  assert.match(html, /deadline-v1/);
});

test("metric with missing or non-Monday evidence is withheld", async () => {
  const profile = fixture("editor-42");
  delete profile.metrics.quality[0].evidence;
  profile.metrics.deadline[0].evidence.source = "ai";
  const html = await renderFor(profile);
  assert.equal(count(html, "Value withheld."), 2);
  assert.doesNotMatch(html, /Meets Expectations/);
  assert.doesNotMatch(html, /result-on_time/);
});

test("UI does not calculate metrics: it trusts API values even when inputs would disagree", async () => {
  const profile = fixture("editor-42");
  // Tampered payload: result says on_time although timestamps say late,
  // and duration does not match the cycle. The UI must not re-derive either.
  profile.metrics.deadline[1].result = "on_time";
  profile.metrics.speed[1].duration_seconds = 60;
  const html = await renderFor(profile);
  assert.equal(count(html, "result-on_time"), 2);
  assert.doesNotMatch(html, /result-late/);
  assert.match(html, /0h 01m \(60 s\)/);
});

test("no aggregates, composite score, rankings or AI text are rendered", async () => {
  const profile = fixture("editor-42");
  profile.ai_annotation = "AI_NARRATIVE_SENTINEL";
  const html = await renderFor(profile);
  assert.doesNotMatch(html, /AI_NARRATIVE_SENTINEL/);
  assert.doesNotMatch(html, /score/i);
  assert.doesNotMatch(html, /%/);
  assert.doesNotMatch(html, /\b(average|faster|slower|rank|percentile)\b/i);
});

test("renderer source contains no metric arithmetic or time comparison", () => {
  const source = readFileSync(join(WEB, "profile.js"), "utf8");
  assert.doesNotMatch(source, /new Date|Date\.parse|\.reduce\(|Math\.(max|min|round|abs)|\.ai_annotation/);
  const renderSection = source.slice(source.indexOf("// ------------------------------------------------------------------ evidence"));
  assert.doesNotMatch(renderSection, /Math\./, "only formatDuration may use Math");
});

test("cross-Video-Type cohort is flagged, not compared", async () => {
  const profile = fixture("editor-42");
  profile.metrics.speed[0].cohort_video_type = "long-form";
  const html = await renderFor(profile);
  assert.match(html, /Cohort Video Type "long-form" does not match; comparison hidden/);
});

test("empty profile states are honest", async () => {
  const html = await renderFor(fixture("editor-empty"));
  for (const kind of ["quality", "speed", "deadline", "work_cycles"]) assert.match(html, new RegExp(`data-empty="${kind}"`));
  assert.match(html, /No approved Monday Performance Label has been recorded/);
  assert.doesNotMatch(html, /<details/);
});

test("fixture data is clearly labeled; undeclared mode is not presented as real", async () => {
  assert.match(await renderFor(fixture("editor-42")), /FIXTURE DATA/);
  const undeclared = await renderFor(fixture("editor-42"), {});
  assert.match(undeclared, /Data mode not declared by the API/);
  assert.doesNotMatch(undeclared, /FIXTURE DATA/);
});

test("loading, missing, invalid, not-found, error and contract states", async () => {
  assert.match(renderView({ status: "loading", editorId: "editor-42" }), /data-state="loading"[\s\S]*Loading editor profile/);
  assert.equal((await loadProfile("", fakeFetch(200, {}))).status, "missing_id");
  assert.equal((await loadProfile("../etc", fakeFetch(200, {}))).status, "invalid_id");

  const notFound = await loadProfile("editor-x", fakeFetch(404, { error: "editor_not_found" }));
  assert.equal(notFound.status, "not_found");
  assert.match(renderView(notFound), /Editor not found/);

  const serverError = await loadProfile("editor-42", fakeFetch(500, {}));
  assert.equal(serverError.status, "error");
  assert.match(renderView(serverError), /HTTP 500/);

  const network = await loadProfile("editor-42", async () => {
    throw new TypeError("connection refused");
  });
  assert.equal(network.status, "error");
  assert.match(renderView(network), /connection refused/);

  const badJson = await loadProfile("editor-42", fakeFetch(200, "{not json"));
  assert.equal(badJson.status, "error");

  const wrongEditor = await loadProfile("editor-99", fakeFetch(200, fixture("editor-42")));
  assert.equal(wrongEditor.status, "contract_error");
  assert.match(renderView(wrongEditor), /not the requested/);
  assert.doesNotMatch(renderView(wrongEditor), /Fixture Editor/);
});

test("contractProblems rejects wrong versions and shapes", () => {
  assert.deepEqual(contractProblems(fixture("editor-42"), "editor-42"), []);
  assert.ok(contractProblems({ contract_version: "0.9.0" }).length > 0);
  const noQuality = fixture("editor-42");
  delete noQuality.metrics.quality;
  assert.deepEqual(contractProblems(noQuality, "editor-42"), ["metrics.quality must be an array."]);
});

test("all API strings are HTML-escaped", async () => {
  const profile = fixture("editor-42");
  profile.editor.display_name = '<img src=x onerror="alert(1)">';
  profile.metrics.quality[0].evidence.source_values.performance_label = "<script>x</script>";
  const html = await renderFor(profile);
  assert.doesNotMatch(html, /<img|<script/);
  assert.equal(escapeHtml(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
});

test("formatDuration is display-only unit conversion", () => {
  assert.equal(formatDuration(43200), "12h 00m (43,200 s)");
  assert.equal(formatDuration(null), "Not provided");
});
