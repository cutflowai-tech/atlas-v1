"""Bounded board-history reads. Raw response bytes are retained before validation."""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

QUERY = """query Probe($boards: [ID!], $from: ISO8601DateTime!, $to: ISO8601DateTime!, $page: Int!, $limit: Int!) {
  boards(ids: $boards) { id activity_logs(from: $from, to: $to, page: $page, limit: $limit) {
    id event entity data user_id created_at
  } }
}"""
FIELDS = {"id", "event", "entity", "data", "user_id", "created_at"}


class ProbeError(Exception):
    """Safe diagnostic without source values or credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("Redirect refused")


def retain(raw: bytes, directory: Path) -> dict:
    """Content-addressed, exclusive writes; refuse any directory inside a git tree."""
    directory = directory.resolve()
    if any((parent / ".git").exists() for parent in (directory, *directory.parents)):
        raise ProbeError("Raw storage must be outside git")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / (digest + ".raw")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != raw:
            raise ProbeError("Raw hash collision or unsafe storage") from None
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    return {"sha256": digest, "bytes": len(raw), "file": path.name}


def inspect_response(raw: bytes, board: str) -> tuple[list, dict]:
    try:
        response = json.loads(raw)
        if response.get("errors"):
            raise ProbeError("GraphQL errors; inspect restricted raw response")
        boards = response["data"]["boards"]
        if len(boards) != 1 or boards[0]["id"] != board:
            raise ProbeError("Board unavailable or mismatched")
        logs = boards[0]["activity_logs"]
        if not isinstance(logs, list):
            raise ProbeError("Activity logs missing or invalid")
        drift = {"missing_field_rows": 0, "extra_field_rows": 0, "invalid_type_rows": 0}
        for row in logs:
            if not isinstance(row, dict):
                raise ProbeError("Invalid activity row")
            drift["missing_field_rows"] += bool(FIELDS - row.keys())
            drift["extra_field_rows"] += bool(row.keys() - FIELDS)
            drift["invalid_type_rows"] += any(not isinstance(row.get(key), str) for key in FIELDS)
        return logs, drift
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProbeError("Response schema invalid; inspect restricted raw response") from None


def probe(token: str, board: str, start: str, end: str, directory: Path,
          version: str, max_pages: int = 100, transport=None) -> dict:
    if not token or not re.fullmatch(r"[0-9]+", board) or not re.fullmatch(r"20\d{2}-(01|04|07|10)", version):
        raise ProbeError("Token, canonical numeric board ID and explicit dated API version required")
    try:
        dates = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (start, end)]
        if any(d.tzinfo is None for d in dates) or dates[0] >= dates[1]:
            raise ValueError
    except ValueError:
        raise ProbeError("Explicit ordered timezone-aware time window required") from None
    if max_pages < 1:
        raise ProbeError("Positive page bound required")
    # Validate storage before sending a request.
    if any((p / ".git").exists() for p in (directory.resolve(), *directory.resolve().parents)):
        raise ProbeError("Raw storage must be outside git")
    send = transport or build_opener(NoRedirect()).open
    manifest: dict = {"board_id": board, "api_version": version, "from": start, "to": end,
                "complete": False, "pages": [], "normalization": "not_attempted"}
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        variables = {"boards": [board], "from": start, "to": end, "page": page, "limit": 100}
        request = Request("https://api.monday.com/v2", data=json.dumps({"query": QUERY, "variables": variables}).encode(),
                          headers={"Authorization": token, "API-Version": version, "Content-Type": "application/json"}, method="POST")
        try:
            with send(request, timeout=30) as response:
                raw = response.read()
        except (OSError, RuntimeError, ProbeError):
            raise ProbeError("Monday transport failed; credentials and remote errors suppressed") from None
        artifact = retain(raw, directory)
        logs, drift = inspect_response(raw, board)
        artifact.update({"page": page, "row_count": len(logs), "drift": drift})
        manifest["pages"].append(artifact)
        if any(drift.values()):
            raise ProbeError("Activity schema drift; raw response retained")
        ids = [row["id"] for row in logs]
        if len(set(ids)) != len(ids) or seen.intersection(ids):
            raise ProbeError("Duplicate events across pagination; completeness unverified")
        seen.update(ids)
        if not logs:
            manifest["complete"] = True
            return manifest
    raise ProbeError("Page bound reached; completeness unverified; raw pages retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("board", "start", "end", "api-version", "raw-dir"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()
    try:
        result = probe(os.environ.get("MONDAY_API_TOKEN", ""), args.board, args.start, args.end,
                       Path(args.raw_dir), args.api_version, args.max_pages)
    except ProbeError as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
