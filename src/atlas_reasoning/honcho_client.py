"""Honcho transport for contextual memory (``REV/10``). The only module that knows Honcho's API (v3, https://api.honcho.dev).

Calls (``Authorization: Bearer <key>``, JSON):

=====================================================================  ===============================================
``POST /v3/workspaces``                                                get or create the environment's workspace
``POST /v3/workspaces/{w}/peers``                                      get or create a peer (``atlas``, ``manager-<hash>``)
``POST /v3/workspaces/{w}/sessions``                                   get or create a session (with its peer)
``POST /v3/workspaces/{w}/sessions/{s}/messages``                      write one memory copy (content + provenance metadata)
``GET  /v3/workspaces/{w}/sessions/{s}/messages/{m}``                  read one copy's metadata (before retiring it)
``PUT  /v3/workspaces/{w}/sessions/{s}/messages/{m}``                  retire a copy (metadata ``atlas_retired: true``)
``POST /v3/workspaces/{w}/sessions/{s}/messages/list?reverse=true``    read the newest copies of one session
=====================================================================  ===============================================

Every get-or-create is idempotent and cached per client. Errors map to ``memory.MemoryUnavailable`` (network, timeout, 408, 429,
5xx: retry later) or ``memory.MemoryRejected`` (401/403/4xx: the request itself is wrong; 404 is ``MemoryNotFound``, which ``read``
and ``retire`` treat as "no memory" — a session nothing was written to yet is not an outage); messages are redacted and never
contain the key. Live calls happen only when ``ATLAS_REASONING_MEMORY=on`` and a key is configured; tests inject ``http`` or use
``fake_honcho``.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from atlas_reasoning.memory import (
    ATLAS_PEER,
    MemoryBackendError,
    MemoryNotFound,
    MemoryRecord,
    MemoryRejected,
    MemoryUnavailable,
    RetrievedMemory,
    check_record,
    honcho_session_id,
)
from atlas_reasoning.provider import redact
from atlas_reasoning.settings import HonchoSettings


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes


Http = Callable[[str, str, Mapping[str, str], bytes | None, float], HttpResult]


def urllib_http(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float) -> HttpResult:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status, response.read())
    except urllib.error.HTTPError as error:
        return HttpResult(error.code, error.read() or b"")


class HonchoClient:
    """``memory.MemoryBackend`` over Honcho. One workspace per environment (``HonchoSettings.workspace_id``)."""

    name = "honcho"

    def __init__(self, settings: HonchoSettings, *, http: Http = urllib_http) -> None:
        self._settings = settings
        self._http = http
        self._lock = threading.Lock()
        self._ready: set[str] = set()   # workspace / peer / session IDs known to exist

    def __repr__(self) -> str:
        return f"HonchoClient(base_url={self._settings.base_url!r}, workspace={self.workspace_id!r})"

    @property
    def workspace_id(self) -> str:
        return self._settings.workspace_id

    # --- HTTP ---------------------------------------------------------------------------------------------------------------

    def _clean(self, text: str) -> str:
        return redact(text, (self._settings.api_key,))[:300]

    def _call(self, method: str, path: str, payload: Any = None, query: Mapping[str, Any] | None = None) -> Any:
        url = f"{self._settings.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": f"Bearer {self._settings.api_key}", "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode()
        try:
            result = self._http(method, url, headers, body, self._settings.timeout_seconds)
        except TimeoutError:
            raise MemoryUnavailable(f"Honcho did not answer within {self._settings.timeout_seconds:g}s") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise MemoryUnavailable(f"Honcho did not answer within {self._settings.timeout_seconds:g}s") from None
            raise MemoryUnavailable(self._clean(f"cannot reach Honcho: {error.reason}")) from None
        except (OSError, http.client.HTTPException) as error:
            raise MemoryUnavailable(self._clean(f"cannot reach Honcho: {type(error).__name__}")) from None
        if result.status in (408, 429) or result.status >= 500:
            raise MemoryUnavailable(f"Honcho unavailable (HTTP {result.status})")
        if result.status in (401, 403):
            raise MemoryRejected(f"Honcho refused the credentials (HTTP {result.status})")
        if result.status == 404:
            raise MemoryNotFound("Honcho has no such session or message")
        if not 200 <= result.status < 300:
            raise MemoryRejected(f"Honcho refused the request (HTTP {result.status})")
        try:
            return json.loads(result.body or b"null")
        except ValueError:
            raise MemoryUnavailable("Honcho returned a body that is not JSON") from None

    def _ensure(self, key: str, method: str, path: str, payload: Any) -> None:
        with self._lock:
            if key in self._ready:
                return
        self._call(method, path, payload)
        with self._lock:
            self._ready.add(key)

    def _workspace(self) -> str:
        workspace = self.workspace_id
        self._ensure(f"w:{workspace}", "POST", "/v3/workspaces", {"id": workspace, "metadata": {"atlas": "reasoning-v3"}})
        return workspace

    def _peer(self, peer_id: str) -> None:
        workspace = self._workspace()
        self._ensure(f"p:{peer_id}", "POST", f"/v3/workspaces/{workspace}/peers", {"id": peer_id})

    def _session(self, key: str, peer_id: str | None = None) -> str:
        workspace = self._workspace()
        session_id = honcho_session_id(key)
        self._ensure(f"s:{session_id}", "POST", f"/v3/workspaces/{workspace}/sessions",
                     {"id": session_id, "metadata": {"atlas_session_key": key}, "peers": {ATLAS_PEER: {}}})
        if peer_id is not None and peer_id != ATLAS_PEER:
            self._ensure(f"sp:{session_id}:{peer_id}", "POST", f"/v3/workspaces/{workspace}/sessions/{session_id}/peers", {peer_id: {}})
        return session_id

    # --- MemoryBackend ------------------------------------------------------------------------------------------------------

    def write(self, record: MemoryRecord) -> str:
        record = check_record(record)
        self._peer(record.peer_id)
        session_id = self._session(record.session_key, record.peer_id)
        message = {"content": record.body, "peer_id": record.peer_id, "metadata": record.provenance()}
        reply = self._call("POST", f"/v3/workspaces/{self.workspace_id}/sessions/{session_id}/messages", {"messages": [message]})
        rows = reply if isinstance(reply, list) else reply.get("messages") if isinstance(reply, Mapping) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping) or not rows[0].get("id"):
            raise MemoryUnavailable("Honcho did not return the stored message")
        return str(rows[0]["id"])

    def retire(self, session_key: str, memory_ref: str) -> None:
        """Mark one copy retired (Honcho has no per-message delete): its own metadata plus ``atlas_retired: true``."""
        session_id = honcho_session_id(session_key)
        path = f"/v3/workspaces/{self.workspace_id}/sessions/{session_id}/messages/{urllib.parse.quote(memory_ref, safe='')}"
        try:
            current = self._call("GET", path)
        except MemoryNotFound:
            return          # nothing left to retire
        metadata = dict(current["metadata"]) if isinstance(current, Mapping) and isinstance(current.get("metadata"), Mapping) else {}
        if isinstance(current, Mapping) and current.get("id") not in (None, memory_ref):
            raise MemoryUnavailable("Honcho returned a different message")
        self._call("PUT", path, {"metadata": {**metadata, "atlas_retired": True}})

    def read(self, session_key: str, *, limit: int) -> Sequence[RetrievedMemory]:
        session_id = honcho_session_id(session_key)
        try:
            page = self._call("POST", f"/v3/workspaces/{self.workspace_id}/sessions/{session_id}/messages/list", {},
                              {"reverse": "true", "page": 1, "size": max(1, min(100, limit))})
        except MemoryNotFound:
            return []       # a session nothing was ever written to: no memory, not an outage
        if page is None:
            return []
        items = page.get("items") if isinstance(page, Mapping) else None
        if not isinstance(items, list):
            raise MemoryUnavailable("Honcho returned an unexpected message page")
        found = []
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("content"), str) or not item.get("id"):
                continue
            metadata: Mapping[str, Any] = item["metadata"] if isinstance(item.get("metadata"), Mapping) else {}
            if metadata.get("atlas_retired"):
                continue
            found.append(RetrievedMemory(str(item["id"]), session_key, item["content"], dict(metadata),
                                         str(item["created_at"]) if item.get("created_at") else None))
        return found

    def health(self) -> dict[str, Any]:
        """One get-or-create of the workspace: proves credentials and reachability without writing memory."""
        try:
            self._workspace()
        except MemoryBackendError as error:
            return {"ok": False, "workspace": self.workspace_id, "error_class": error.error_class, "error": str(error)}
        return {"ok": True, "workspace": self.workspace_id}


def backend_from_env(env: Mapping[str, str] | None = None, *, http: Http = urllib_http) -> HonchoClient | None:
    """The configured memory backend, or ``None`` when ``ATLAS_REASONING_MEMORY`` is off (canonical context only)."""
    from atlas_reasoning.settings import honcho_settings, memory_enabled

    if not memory_enabled(env):
        return None
    return HonchoClient(honcho_settings(env), http=http)
