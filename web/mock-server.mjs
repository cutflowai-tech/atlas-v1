// Fixture-mode mock of GET /api/editors/<editor_id> plus the static UI.
// Development only: every API response is labeled X-Atlas-Data-Mode: fixture.
//
//   node web/mock-server.mjs            # http://127.0.0.1:8787/?editor=editor-42
//   PORT=9000 node web/mock-server.mjs
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const WEB_ROOT = dirname(fileURLToPath(import.meta.url));
export const FIXTURE_DIR = join(WEB_ROOT, "mock", "editors");

const STATIC_FILES = {
  "/": ["index.html", "text/html; charset=utf-8"],
  "/index.html": ["index.html", "text/html; charset=utf-8"],
  "/app.js": ["app.js", "text/javascript; charset=utf-8"],
  "/profile.js": ["profile.js", "text/javascript; charset=utf-8"],
  "/styles.css": ["styles.css", "text/css; charset=utf-8"],
};

// Reserved IDs that simulate failure modes of the real API.
const SIMULATED = {
  "fixture-server-error": { status: 500, body: { error: "simulated_server_error" } },
  "fixture-bad-contract": { status: 200, body: { contract_version: "0.9.0", subject_type: "editor" } },
};

const EDITOR_ID = /^[A-Za-z0-9_.:-]{1,128}$/;

function send(res, status, contentType, body, extraHeaders = {}) {
  res.writeHead(status, { "Content-Type": contentType, "Cache-Control": "no-store", ...extraHeaders });
  res.end(body);
}

function sendJson(res, status, body) {
  send(res, status, "application/json; charset=utf-8", JSON.stringify(body), { "X-Atlas-Data-Mode": "fixture" });
}

async function handleEditor(res, editorId) {
  if (!EDITOR_ID.test(editorId)) return sendJson(res, 400, { error: "invalid_editor_id" });
  if (editorId in SIMULATED) return sendJson(res, SIMULATED[editorId].status, SIMULATED[editorId].body);
  try {
    const raw = await readFile(join(FIXTURE_DIR, `${editorId}.json`), "utf8");
    return send(res, 200, "application/json; charset=utf-8", raw, { "X-Atlas-Data-Mode": "fixture" });
  } catch (error) {
    if (error.code === "ENOENT") return sendJson(res, 404, { error: "editor_not_found" });
    throw error;
  }
}

export function createMockServer() {
  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");
      if (req.method !== "GET" && req.method !== "HEAD") return sendJson(res, 405, { error: "method_not_allowed" });
      const match = url.pathname.match(/^\/api\/editors\/([^/]+)$/);
      if (match) return await handleEditor(res, decodeURIComponent(match[1]));
      const file = STATIC_FILES[url.pathname];
      if (file) return send(res, 200, file[1], await readFile(join(WEB_ROOT, file[0])));
      return send(res, 404, "text/plain; charset=utf-8", "Not found");
    } catch {
      return sendJson(res, 500, { error: "mock_server_failure" });
    }
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const port = Number(process.env.PORT ?? 8787);
  createMockServer().listen(port, "127.0.0.1", () => {
    console.log(`Atlas Editor Profile (FIXTURE MODE): http://127.0.0.1:${port}/?editor=editor-42`);
    console.log("Other fixtures: editor-empty, editor-unknown (404), fixture-server-error, fixture-bad-contract. Ctrl+C to stop.");
  });
}
