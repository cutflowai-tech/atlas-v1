import { loadProfile, renderView } from "./profile.js";

const root = document.getElementById("app");
const form = document.getElementById("editor-form");
const editorId = new URLSearchParams(window.location.search).get("editor") ?? "";

form.elements.editor.value = editorId;

root.setAttribute("aria-busy", "true");
root.innerHTML = renderView({ status: "loading", editorId });

const state = await loadProfile(editorId, (url, init) => window.fetch(url, init));

root.innerHTML = renderView(state);
root.setAttribute("aria-busy", "false");
root.dataset.state = state.status;
