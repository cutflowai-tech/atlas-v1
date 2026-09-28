"""Preserve source bytes and report shape gaps without normalizing source facts."""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

BOARD = "5091110326"
QUERY = """query AtlasActivity($board: [ID!]!, $items: [ID!], $from: ISO8601DateTime!,
$to: ISO8601DateTime!, $page: Int!, $limit: Int!) {
  boards(ids: $board) { id activity_logs(item_ids: $items, from: $from, to: $to,
    page: $page, limit: $limit) { id event data entity user_id created_at account_id } }
}"""


class ProbeError(Exception):
    """Safe, value-free operational failure."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("HTTP redirect refused")


def store_raw(root: Path, payload: bytes) -> dict:
    """Content addressed, exclusive creation, read-only bytes outside any git tree."""
    root = root.resolve()
    if any((p / ".git").exists() for p in (root, *root.parents)):
        raise ProbeError("Raw storage must be outside git")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(payload).hexdigest()
    target = root / (digest + ".raw")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != payload:
            raise ProbeError("Raw storage integrity failure") from None
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o400)
    return {"sha256": digest, "bytes": len(payload), "raw_file": target.name}


def snapshot_report(payload: bytes) -> dict:
    text = payload.decode("utf-8")
    if not re.search(r"^board_id: '5091110326'$", text, re.MULTILINE):
        raise ProbeError("Unexpected snapshot board")
    try:
        section = text.split("## Columns\n", 1)[1].split("## Groups", 1)[0]
        columns = []
        statuses = []
        for line in section.splitlines():
            if not line.startswith("| `"):
                continue
            cells = [c.strip().strip("`") for c in line.strip("|").split(" | ")]
            columns.append({"id": cells[0], "type": cells[2]})
            if cells[0] == "project_status":
                statuses = sorted(json.loads(cells[4])["labels"].values())
    except (IndexError, ValueError, KeyError, TypeError):
        raise ProbeError("Snapshot column format drift") from None
    canonical = {"Backlog", "In Progress", "Ready For Approval", "Revision", "Approved", "Delivered"}
    return {
        "board_id": BOARD, "source_format": "exported_markdown_not_api_response",
        "observed_items": len(re.findall(r"^- \*\*item_id:\*\*", text, re.MULTILINE)),
        "columns": columns,
        "status_labels_outside_contract": sorted(set(statuses) - canonical),
        "contract_statuses_not_observed": sorted(canonical - set(statuses)),
        "activity_history": "not_exported_per_source_manifest",
        "normalization": "blocked_missing_history_and_approved_versioned_mappings",
        "editor_identity": "dropdown_label_is_not_canonical_monday_user_id",
        "quality_mapping": "not_approved_or_inferred",
        "metric_outputs": [],
    }


def fetch(token: str, version: str, variables: dict) -> bytes:
    request = Request("https://api.monday.com/v2", method="POST",
                      data=json.dumps({"query": QUERY, "variables": variables}).encode(),
                      headers={"Authorization": token, "API-Version": version, "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            return response.read()
    except (OSError, ValueError, ProbeError):
        # Do not echo remote error bodies, headers, or credentials.
        raise ProbeError("Monday transport failed; no source mutation attempted") from None


def activity_probe(root: Path, token: str, version: str, item_ids: list[str], start: str, end: str,
                   transport=fetch, max_pages: int = 100) -> dict:
    """Caller supplies evidenced item membership; actor filters would omit shared-account events."""
    if not token:
        raise ProbeError("Missing MONDAY_API_TOKEN with read access to board 5091110326 activity logs")
    if not re.fullmatch(r"\d{4}-(01|04|07|10)", version):
        raise ProbeError("Explicit dated API version required")
    if not item_ids or any(not re.fullmatch(r"[0-9]+", x) for x in item_ids):
        raise ProbeError("Canonical item IDs from evidenced Editor membership required")
    try:
        a, b = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
        valid = a.tzinfo is not None and b.tzinfo is not None and a < b
    except ValueError:
        valid = False
    if not valid or max_pages < 1:
        raise ProbeError("Bounded timezone-aware time window and positive page cap required")
    pages = []
    seen = set()
    for page in range(1, max_pages + 1):
        raw = transport(token, version, {"board": [BOARD], "items": sorted(set(item_ids)),
                                       "from": start, "to": end, "page": page, "limit": 100})
        evidence = store_raw(root, raw)
        pages.append(evidence)
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise TypeError()
            if result.get("errors"):
                raise ProbeError("GraphQL errors; raw response retained; probe incomplete")
            boards = result["data"]["boards"]
            if len(boards) != 1 or boards[0]["id"] != BOARD:
                raise ProbeError("Board missing or mismatched; probe incomplete")
            events = boards[0]["activity_logs"]
            if not isinstance(events, list):
                raise TypeError()
            for event in events:
                for key in ("id", "event", "data", "entity", "user_id", "created_at", "account_id"):
                    if not isinstance(event[key], str):
                        raise TypeError()
                if event["id"] in seen:
                    raise ProbeError("Duplicate event across pages; completeness unproven")
                seen.add(event["id"])
        except (ValueError, KeyError, TypeError):
            raise ProbeError("Activity response shape drift; raw response retained") from None
        if not events:
            return {"board_id": BOARD, "api_version": version, "from": start, "to": end,
                    "pages": pages, "event_count": len(seen), "pagination": "empty_page_reached",
                    "historical_completeness": "unproven_api_retention_and_pagination_limits",
                    "normalization": "not_attempted", "metric_outputs": []}
    raise ProbeError("Page cap reached; raw responses retained; probe incomplete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    sub = parser.add_subparsers(dest="mode", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("path", type=Path)
    live = sub.add_parser("activity")
    live.add_argument("--api-version", required=True)
    live.add_argument("--item-id", action="append", required=True)
    live.add_argument("--from", dest="start", required=True)
    live.add_argument("--to", dest="end", required=True)
    args = parser.parse_args()
    try:
        if args.mode == "snapshot":
            raw = args.path.read_bytes()
            result = {"sample": store_raw(args.raw_dir, raw), "drift": snapshot_report(raw)}
        else:
            result = activity_probe(args.raw_dir, os.environ.get("MONDAY_API_TOKEN", ""), args.api_version,
                                    args.item_id, args.start, args.end)
        print(json.dumps(result, sort_keys=True, indent=2))
    except (ProbeError, OSError) as error:
        parser.exit(2, (str(error) if isinstance(error, ProbeError) else "Local file access failed") + "\n")


if __name__ == "__main__":
    main()
