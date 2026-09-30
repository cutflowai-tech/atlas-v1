"""Atomic publication and rollback of completed staged builds (never rebuilds anything).

    PYTHONPATH=src python3 -m atlas_sync publish <attempt_id>
    PYTHONPATH=src python3 -m atlas_sync rollback [<attempt_id>]

The live site is the symlink ``<ATLAS_PUBLISH_DIR>/current``, pointing at exactly one completed build's
``<ATLAS_BUILD_DIR>/<attempt_id>/site``. The link text is relative (e.g. ``../builds/<attempt_id>/site``), so the
layout survives mounting the data root elsewhere; it must resolve to exactly that site, or the publish is
refused. Nothing is copied and no build file is modified.

Both commands hold the production lock (:mod:`atlas_sync.lock`) from before reading ``current`` until the
metadata is written. If another production operation holds it, nothing is validated, switched or recorded.

Publishing a build:

1. validate it again from scratch (:func:`validate_build`), including the production verification of its
   source raw run; any failure stops here and ``current`` is untouched;
2. create a temporary symlink ``<publish>/.current.<publication_id>.tmp`` to the build's ``site``;
3. ``os.replace`` it onto ``current``. Both names are in the same directory, so this is a single atomic
   rename on one filesystem; only the symlink moves, never a build;
4. verify that ``current`` now resolves to that exact ``site``;
5. append ``<publish>/history/<sequence>-<publication_id>.json`` (immutable) and then replace
   ``<publish>/CURRENT.json`` atomically.

Metadata is written only after the switch is verified, so it never claims a build is live before it is.
If it cannot be written after a successful switch, the result is ``published_metadata_inconsistent``: the
new build is live and the metadata is behind; running ``publish <attempt_id>`` again re-validates and
rewrites it. No automatic reversal is attempted.

Rollback picks a build that was published before (from the history), re-validates it the same way and
switches ``current`` with the same steps. Results and records hold no token and no exception text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander import site_layout
from atlas_commander.contracts import validate
from atlas_commander.ingest import MANIFEST_NAME, RUN_ID_PATTERN, Clock, new_run_id, utc_now
from atlas_commander.ingest_verify import verify
from atlas_commander.investigation.site import site_problems as intelligence_problems
from atlas_commander.profile import evidence_consistency_errors
from atlas_monday_probe.client import InvalidMondaySetting, validate_api_version
from atlas_monday_probe.raw_store import write_immutable_atomic

from .config import PRODUCTION_CONTRACT_VERSIONS, ConfigError, SyncConfig, load_sync_config
from .lock import EXIT_LOCKED, LockError, OperationLocked, production_lock
from .run import BUILD_METADATA_NAME, BUILD_METADATA_VERSION, COMPLETE_NAME, FAILED_NAME, PROFILE_SCHEMAS, SITE_DIR, build_state

POINTER_NAME = "current"
CURRENT_METADATA_NAME = "CURRENT.json"
HISTORY_DIR = "history"
PUBLICATION_VERSION = "atlas-publication-v1"
HISTORY_PATTERN = re.compile(r"^(\d{6})-(\d{8}T\d{6}Z-[0-9a-f]{12})\.json$")
MAX_PROBLEMS = 20

# Result statuses. Only "published" is full success; "published_metadata_inconsistent" means the switch happened.
PUBLISHED, REJECTED, SWITCH_FAILED, INCONSISTENT = "published", "rejected", "switch_failed", "published_metadata_inconsistent"
LOCKED = "locked"   # another production operation held the lock; nothing was done


class PublishRejected(Exception):
    """The build or target cannot be published. Raised before ``current`` is touched."""

    def __init__(self, category: str, problems: list[str]) -> None:
        super().__init__(category)
        self.category, self.problems = category, problems


@dataclass
class ValidatedBuild:
    attempt_id: str
    site: Path
    source_run_id: str
    build_metadata_sha256: str
    contract_version: str
    board_id: str
    dashboard_sha256: str


@dataclass
class PublishResult:
    """Safe, JSON-ready outcome of one publish or rollback (no token, no exception text)."""

    publication_id: str
    action: str
    status: str = "running"
    attempt_id: str | None = None
    previous_attempt_id: str | None = None
    source_run_id: str | None = None
    published_at: str | None = None
    current_target: str | None = None
    current_link: str | None = None
    build_metadata_sha256: str | None = None
    contract_version: str | None = None
    board_id: str | None = None
    switched: bool = False
    failure_stage: str | None = None
    failure_category: str | None = None
    problems: list[str] = field(default_factory=list)
    history_record: str | None = None
    current_metadata: str | None = None
    lock: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path, what: str, category: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise PublishRejected(category, [f"{what} is missing or is not valid JSON"]) from None
    if not isinstance(document, dict):
        raise PublishRejected(category, [f"{what} is not a JSON object"])
    return document


def _roots(config: SyncConfig) -> tuple[Path, Path, Path]:
    return config.build_dir.expanduser().resolve(), config.publish_dir.expanduser().resolve(), config.raw_dir.expanduser().resolve()


def build_site_path(config: SyncConfig, attempt_id: str) -> Path:
    """``<build root>/<attempt_id>/site``; the attempt ID must be a run-style ID, so it cannot traverse paths."""
    if not isinstance(attempt_id, str) or not RUN_ID_PATTERN.match(attempt_id):
        raise PublishRejected("invalid_attempt_id", ["attempt ID must look like YYYYMMDDTHHMMSSZ-<12 hex>"])
    build_root, _, _ = _roots(config)
    return build_root / attempt_id / SITE_DIR


def _site_files(site: Path, problems: list[str]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(site.rglob("*")):
        name = path.relative_to(site).as_posix()
        if path.is_symlink():
            problems.append(f"site contains a symlink: {name}")   # could point anywhere; a generated site has none
        elif path.is_file():
            files[name] = path
    return files


def validate_build(config: SyncConfig, attempt_id: str) -> ValidatedBuild:
    """Every check a build must pass, now, before ``current`` may point at it. Raises :class:`PublishRejected`."""
    site = build_site_path(config, attempt_id)
    build = site.parent
    build_root, _, raw_root = _roots(config)
    if not build.is_dir() or build.is_symlink():
        raise PublishRejected("unknown_attempt", [f"no staged build for attempt {attempt_id}"])
    if build.resolve() != build_root / attempt_id or not site.is_dir() or site.is_symlink() or site.resolve() != build_root / attempt_id / SITE_DIR:
        raise PublishRejected("unsafe_path", ["the build or its site is not a real directory under the build root"])

    state = build_state(build)
    if state != "complete" or not (build / COMPLETE_NAME).is_file() or (build / FAILED_NAME).exists():
        raise PublishRejected("build_not_complete", [f"build state is {state}; only a complete build can be published"])
    metadata_bytes = (build / BUILD_METADATA_NAME).read_bytes() if (build / BUILD_METADATA_NAME).is_file() else b""
    metadata = _load_json(build / BUILD_METADATA_NAME, BUILD_METADATA_NAME, "build_metadata_invalid")
    marker = _load_json(build / COMPLETE_NAME, COMPLETE_NAME, "build_metadata_invalid")
    metadata_sha = _sha256(metadata_bytes)

    problems: list[str] = []
    if marker.get("status") != "complete" or marker.get("attempt_id") != attempt_id or marker.get("build_metadata_sha256") != metadata_sha:
        problems.append("build.json or COMPLETE.json was changed after the build completed")
    if metadata.get("build_metadata_version") != BUILD_METADATA_VERSION or (metadata.get("attempt") or {}).get("attempt_id") != attempt_id:
        problems.append("build.json does not describe this attempt")
    if metadata.get("published") is not False:
        problems.append("build.json does not have the staged state (published: false) written by run-once")
    if problems:
        raise PublishRejected("build_tampered", problems)

    contract_version = metadata.get("contract_version")
    if contract_version != config.contract_version or contract_version not in PRODUCTION_CONTRACT_VERSIONS:
        raise PublishRejected("wrong_contract", [f"build uses contract {contract_version!r}; production uses {config.contract_version}"])
    monday = metadata.get("monday") or {}
    if monday.get("board_id") != config.board_id:
        raise PublishRejected("wrong_board", [f"build is for board {monday.get('board_id')!r}; production is {config.board_id}"])
    try:
        validate_api_version(str(monday.get("api_version")))
    except InvalidMondaySetting:
        raise PublishRejected("wrong_api_version", ["build has no valid Monday API version"]) from None
    if monday.get("api_version") != config.monday_api_version:
        raise PublishRejected("wrong_api_version", [f"build used API {monday.get('api_version')}; configuration is {config.monday_api_version}"])

    source = metadata.get("source") or {}
    run_id = source.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.match(run_id) or source.get("raw_run_dir") != str(raw_root / run_id):
        raise PublishRejected("wrong_source_run", ["build.json does not name a source run under the configured raw root"])
    raw_run = raw_root / run_id
    if not raw_run.is_dir():
        raise PublishRejected("missing_raw_evidence", [f"source raw run {run_id} is missing"])
    report = verify(raw_run, require_production=True)
    if not report["passed"] or report.get("run_id") != run_id:
        raise PublishRejected("raw_evidence_invalid", [f"source raw run {run_id} fails production verification", *report["failures"]][:MAX_PROBLEMS])
    manifest_bytes = (raw_run / MANIFEST_NAME).read_bytes()
    manifest = json.loads(manifest_bytes)
    if (source.get("manifest_sha256") != _sha256(manifest_bytes) or source.get("extract_sha256") != manifest["extract"]["sha256"]
            or source.get("coverage") != manifest.get("coverage") or source.get("retrieved_at") != manifest.get("retrieved_at")
            or manifest.get("contract_version") != contract_version or (manifest.get("monday") or {}).get("board_id") != config.board_id
            or (manifest.get("monday") or {}).get("api_version") != monday.get("api_version")):
        raise PublishRejected("wrong_source_run", [f"build metadata does not match source raw run {run_id}"])

    problems = []
    listed = (metadata.get("artifacts") or {}).get("files")
    if not isinstance(listed, dict) or (metadata.get("artifacts") or {}).get("root") != SITE_DIR:
        raise PublishRejected("build_tampered", ["build.json has no artifact list"])
    files = _site_files(site, problems)
    problems += [f"listed artifact missing: {name}" for name in listed if name not in files]
    problems += [f"unlisted file in site: {name}" for name in files if name not in listed]
    for name, path in files.items():
        record = listed.get(name) or {}
        data = path.read_bytes()
        if name in listed and (record.get("sha256") != _sha256(data) or record.get("size_bytes") != len(data)):
            problems.append(f"artifact changed since the build: {name}")
    editors = [editor.get("editor_id") for editor in metadata.get("editors") or []]
    required = site_layout.required_files(editors, contract_version)   # English and Arabic are published together or not at all
    problems += [f"required artifact missing or empty: {name}" for name in required if name not in files or files[name].stat().st_size == 0]
    if metadata.get("editor_count") != len(editors):
        problems.append("editor count does not match the Editor list")
    if config.monday_token is not None and config.monday_token.reveal():
        token = config.monday_token.reveal().encode()
        problems += [f"artifact contains the Monday token: {name}" for name, path in files.items() if token in path.read_bytes()]
        if token in metadata_bytes:
            problems.append("build.json contains the Monday token")
    problems += site_layout.publication_problems(files, editors, contract_version, manifest.get("retrieved_at"))
    problems += [problem for name in site_layout.optional_files(contract_version) if name in files
                 for problem in intelligence_problems(files[name], contract_version, manifest.get("retrieved_at"))]
    if problems:
        raise PublishRejected("build_tampered", problems[:MAX_PROBLEMS])

    for editor in editors:
        profile = json.loads(files[f"profiles/{editor}.json"].read_bytes())
        schema = PROFILE_SCHEMAS.get(profile.get("contract_version"))
        profile_source = profile.get("source") or {}
        if schema is None or validate(profile, schema) or evidence_consistency_errors(profile):
            problems.append(f"profiles/{editor}.json does not satisfy the Editor Profile schema")
        if (profile.get("editor") or {}).get("editor_id") != editor or profile.get("executable_contract_version") != contract_version \
                or profile_source.get("retrieved_at") != manifest.get("retrieved_at") \
                or (profile_source.get("history_coverage") or {}).get("activity_log_window") != manifest.get("window"):
            problems.append(f"profiles/{editor}.json does not come from this build's source run and contract")
    for name, locale in site_layout.html_files(editors).items():
        if not files[name].read_text(encoding="utf-8").startswith(site_layout.document_opening(locale)):
            problems.append(f"{name} does not declare lang={locale} and its direction")
    dashboard = json.loads(files[site_layout.DASHBOARD_JSON].read_bytes())
    if sorted(s.get("editor_id") for s in dashboard.get("editors") or []) != sorted(editors) \
            or (dashboard.get("source") or {}).get("retrieved_at") != manifest.get("retrieved_at"):
        problems.append("dashboard.json does not match this build's Editors and source run")
    if problems:
        raise PublishRejected("build_invalid", problems[:MAX_PROBLEMS])
    return ValidatedBuild(attempt_id, site, run_id, metadata_sha, contract_version, config.board_id, listed[site_layout.PUBLISHED_CHECK]["sha256"])


def _pointer(config: SyncConfig) -> Path:
    _, publish_root, _ = _roots(config)
    return publish_root / POINTER_NAME


def live_attempt(config: SyncConfig) -> str | None:
    """The attempt ``current`` actually points at, or None when there is no ``current`` yet.

    Raises :class:`PublishRejected` when ``current`` exists but is not a symlink to a build site under the build root."""
    pointer = _pointer(config)
    if not pointer.is_symlink():
        if pointer.exists():
            raise PublishRejected("unsafe_current", [f"{POINTER_NAME} exists and is not a symlink; it is never overwritten"])
        return None
    build_root, publish_root, _ = _roots(config)
    target = Path(os.readlink(pointer))
    if not target.is_absolute():   # relative links resolve from the publish directory; earlier absolute links are still read
        target = Path(os.path.normpath(publish_root / target))
    if target.parent.parent != build_root or target.name != SITE_DIR or not RUN_ID_PATTERN.match(target.parent.name):
        raise PublishRejected("unsafe_current", [f"{POINTER_NAME} points outside the Atlas build root"])
    return target.parent.name


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def link_text(config: SyncConfig, site: Path) -> str:
    """The relative symlink text from the publish directory to ``site``; refused unless it resolves to exactly ``site``."""
    _, publish_root, _ = _roots(config)
    try:
        text = os.path.relpath(site, publish_root)
    except ValueError:   # e.g. different drives: no relative path exists
        raise PublishRejected("unsafe_path", ["no relative link can be formed from the publish directory to the build site"]) from None
    if os.path.isabs(text) or Path(os.path.normpath(publish_root / text)) != site or (publish_root / text).resolve() != site:
        raise PublishRejected("unsafe_path", ["a relative link from the publish directory would not resolve to the build site"])
    return text


def _create_temporary_pointer(text: str, temporary: Path) -> None:
    os.symlink(text, temporary)   # exclusive: fails if the name exists


def _replace_pointer(temporary: Path, pointer: Path) -> None:
    if temporary.parent != pointer.parent:   # invariant: one directory, so one filesystem and one atomic rename
        raise PublishRejected("unsafe_path", ["temporary pointer and current are not in the same directory"])
    os.replace(temporary, pointer)


def _verify_pointer(pointer: Path, build: ValidatedBuild, text: str) -> bool:
    try:
        return (pointer.is_symlink() and os.readlink(pointer) == text and pointer.resolve() == build.site
                and _sha256((pointer / site_layout.PUBLISHED_CHECK).read_bytes()) == build.dashboard_sha256)
    except OSError:
        return False


def _history(config: SyncConfig) -> list[dict[str, Any]]:
    """Readable history records, oldest first."""
    _, publish_root, _ = _roots(config)
    directory = publish_root / HISTORY_DIR
    records = []
    for path in sorted(directory.iterdir()) if directory.is_dir() else []:
        match = HISTORY_PATTERN.match(path.name)
        if not match:
            continue
        try:
            record = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            records.append({**record, "_sequence": int(match.group(1))})
    return sorted(records, key=lambda record: record["_sequence"])


def _write_history(config: SyncConfig, result: PublishResult) -> Path:
    _, publish_root, _ = _roots(config)
    sequence = max((record["_sequence"] for record in _history(config)), default=0) + 1
    record = {"publication_version": PUBLICATION_VERSION, "sequence": sequence, **result.as_dict()}
    record.pop("history_record")
    record.pop("current_metadata")
    data = json.dumps(record, indent=1, sort_keys=True).encode() + b"\n"
    return write_immutable_atomic(publish_root / HISTORY_DIR, f"{sequence:06d}-{result.publication_id}.json", data).path


def _write_current_metadata(config: SyncConfig, result: PublishResult) -> Path:
    """Replace CURRENT.json atomically (temporary file, fsync, rename in the same directory)."""
    _, publish_root, _ = _roots(config)
    document = {"publication_version": PUBLICATION_VERSION, "pointer": POINTER_NAME,
                **{key: getattr(result, key) for key in ("publication_id", "action", "attempt_id", "previous_attempt_id", "source_run_id",
                                                         "published_at", "current_target", "current_link", "build_metadata_sha256", "contract_version",
                                                         "board_id", "history_record")},
                "status": PUBLISHED}
    data = json.dumps(document, indent=1, sort_keys=True).encode() + b"\n"
    path = publish_root / CURRENT_METADATA_NAME
    temporary = publish_root / f".{CURRENT_METADATA_NAME}.{result.publication_id}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    _fsync_dir(publish_root)
    return path


def current_consistency(config: SyncConfig) -> dict[str, Any]:
    """Compare CURRENT.json with the symlink, which is what is actually served."""
    _, publish_root, _ = _roots(config)
    try:
        live = live_attempt(config)
    except PublishRejected:
        live = "unsafe"
    path = publish_root / CURRENT_METADATA_NAME
    try:
        recorded = json.loads(path.read_bytes()).get("attempt_id") if path.exists() else None
    except (OSError, ValueError):
        recorded = "unreadable"
    return {"live_attempt_id": live, "recorded_attempt_id": recorded, "consistent": live == recorded}


def _switch(config: SyncConfig, build: ValidatedBuild, result: PublishResult, clock: Clock) -> None:
    """Steps 2-5: temporary symlink, atomic replace, verification, then metadata. Updates ``result`` in place."""
    _, publish_root, _ = _roots(config)
    publish_root.mkdir(parents=True, exist_ok=True)
    pointer = publish_root / POINTER_NAME
    temporary = publish_root / f".{POINTER_NAME}.{result.publication_id}.tmp"
    text = link_text(config, build.site)   # raises PublishRejected before anything is created
    result.failure_stage = "switch"
    problems: list[str] = []
    try:
        _create_temporary_pointer(text, temporary)
        if os.readlink(temporary) != text:
            raise PublishRejected("switch_failed", ["temporary pointer does not point at the build site"])
        _replace_pointer(temporary, pointer)
    except Exception as error:  # noqa: BLE001 - _replace_pointer either renames atomically or raises before it has done so
        if temporary.is_symlink():
            temporary.unlink()
        result.status, result.failure_category = SWITCH_FAILED, error.category if isinstance(error, PublishRejected) else "switch_failed"
        result.problems = [f"switch failed ({type(error).__name__}); {POINTER_NAME} was not changed"]
        return
    result.switched = True
    result.published_at = _iso(clock())
    result.current_target = str(build.site)
    result.current_link = text
    try:
        _fsync_dir(pointer.parent)
    except Exception as error:  # noqa: BLE001 - rename happened; report uncertainty and never pretend old is live
        result.failure_stage, result.failure_category = "post_switch_durability", "post_switch_durability_failed"
        problems.append(f"{POINTER_NAME} was replaced but its directory could not be synced ({type(error).__name__})")
    if not _verify_pointer(pointer, build, text):
        result.failure_stage, result.failure_category = "post_switch_verification", "post_switch_verification_failed"
        problems.append(f"{POINTER_NAME} was replaced but does not resolve to the expected build site")
    result.status = PUBLISHED if not problems else INCONSISTENT
    try:
        result.history_record = str(_write_history(config, result))
    except Exception as error:  # noqa: BLE001 - reported as an inconsistency, never hidden
        problems.append(f"history record could not be written ({type(error).__name__})")
        result.failure_stage, result.failure_category = "history", result.failure_category or "history_write_failed"
    if result.status == PUBLISHED:
        try:
            result.current_metadata = str(_write_current_metadata(config, result))
        except Exception as error:  # noqa: BLE001 - reported as an inconsistency, never hidden
            problems.append(f"{CURRENT_METADATA_NAME} could not be written ({type(error).__name__})")
            result.failure_stage, result.failure_category = "current_metadata", result.failure_category or "current_metadata_write_failed"
    if problems:
        result.status = INCONSISTENT
        recovery = (f"{POINTER_NAME} now points at {build.attempt_id}; run 'publish {build.attempt_id}' to re-validate "
                    "and rewrite the metadata, or 'rollback' to switch back")
        result.problems = [*problems, recovery]
    else:
        result.failure_stage = None


def _promote(config: SyncConfig, attempt_id: str, result: PublishResult, clock: Clock) -> PublishResult:
    result.attempt_id = attempt_id if RUN_ID_PATTERN.match(attempt_id or "") else None
    result.failure_stage = "validation"
    build = validate_build(config, attempt_id)
    result.source_run_id, result.build_metadata_sha256 = build.source_run_id, build.build_metadata_sha256
    result.contract_version, result.board_id = build.contract_version, build.board_id
    _switch(config, build, result, clock)
    return result


def _reject(config: SyncConfig | None, result: PublishResult, error: PublishRejected) -> PublishResult:
    result.status, result.failure_category, result.problems = REJECTED, error.category, error.problems[:MAX_PROBLEMS]
    if config is not None:
        try:   # a rejected request is history too; current was not touched
            result.history_record = str(_write_history(config, result))
        except Exception:  # noqa: BLE001, S110 - best effort; the rejection itself is the outcome
            pass
    return result


def _run(action: str, requested: str | None, environ: Mapping[str, str] | None, config: SyncConfig | None, clock: Clock,
         publication_id_factory: Callable[[datetime], str]) -> PublishResult:
    result = PublishResult(publication_id=publication_id_factory(clock()), action=action)
    try:
        cfg = config or load_sync_config(environ, now=clock())
    except ConfigError as error:
        result.status, result.failure_stage, result.failure_category = REJECTED, "configuration", "configuration"
        result.problems = error.problems[:MAX_PROBLEMS]
        return result
    try:
        # The ownership layer for publish and rollback: one lock for the whole operation, before `current` is read.
        with production_lock(cfg, "publish" if action == "publish" else "rollback", target=requested, clock=clock):
            return _run_locked(action, requested, cfg, result, clock)
    except OperationLocked as locked:   # nothing validated, switched or recorded
        result.status, result.failure_stage, result.failure_category, result.lock = LOCKED, "lock", locked.failure_category, locked.as_dict()
        return result
    except LockError as error:          # unsafe or missing lock location: fail closed, nothing recorded
        result.status, result.failure_stage, result.failure_category, result.problems = REJECTED, "lock", error.failure_category, [error.message]
        return result


def _run_locked(action: str, requested: str | None, cfg: SyncConfig, result: PublishResult, clock: Clock) -> PublishResult:
    """Publish or roll back; the caller holds the production lock (never call this without it)."""
    try:
        result.failure_stage = "current"
        result.previous_attempt_id = live_attempt(cfg)
        if action == "rollback":
            target = _rollback_target(cfg, requested, result.previous_attempt_id)
        else:
            assert requested is not None
            target = requested
        return _promote(cfg, target, result, clock)
    except PublishRejected as error:
        return _reject(cfg, result, error)


def _rollback_target(config: SyncConfig, requested: str | None, live: str | None) -> str:
    if live is None:
        raise PublishRejected("nothing_published", [f"there is no {POINTER_NAME} to roll back from"])
    published = [record for record in reversed(_history(config)) if record.get("switched") is True and record.get("attempt_id")]
    if requested is None:
        for record in published:
            if record["attempt_id"] != live:
                return str(record["attempt_id"])
        raise PublishRejected("no_previous_publication", ["no earlier successfully published build to roll back to"])
    build_site_path(config, requested)   # rejects malformed IDs and traversal
    if requested == live:
        raise PublishRejected("already_current", [f"{requested} is already live"])
    if not any(record["attempt_id"] == requested for record in published):
        raise PublishRejected("not_previously_published", [f"{requested} was never successfully published; use publish for a new build"])
    return requested


def publish(attempt_id: str, environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None, clock: Clock = utc_now,
            publication_id_factory: Callable[[datetime], str] = new_run_id) -> PublishResult:
    """Validate the completed staged build ``attempt_id`` and make it the live site. Never raises for a rejected build."""
    return _run("publish", attempt_id, environ, config, clock, publication_id_factory)


def _publish_locked(attempt_id: str, *, config: SyncConfig, clock: Clock = utc_now,
                    publication_id_factory: Callable[[datetime], str] = new_run_id) -> PublishResult:
    """Publish exactly ``attempt_id`` while the caller holds the production lock; never scans for a fallback."""
    result = PublishResult(publication_id=publication_id_factory(clock()), action="publish")
    return _run_locked("publish", attempt_id, config, result, clock)


def rollback(attempt_id: str | None = None, environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None,
             clock: Clock = utc_now, publication_id_factory: Callable[[datetime], str] = new_run_id) -> PublishResult:
    """Switch back to the most recent earlier published build other than the live one (or to ``attempt_id``, which must
    have been published before). The target is re-validated exactly like a publish; nothing is rebuilt."""
    return _run("rollback", attempt_id, environ, config, clock, publication_id_factory)


EXIT_PUBLISHED, EXIT_CONFIG, EXIT_REJECTED, EXIT_SWITCH_FAILED, EXIT_INCONSISTENT = 0, 2, 3, 4, 5


def exit_code(result: PublishResult) -> int:
    if result.status == PUBLISHED:
        return EXIT_PUBLISHED
    if result.status == LOCKED:
        return EXIT_LOCKED
    if result.status == INCONSISTENT:
        return EXIT_INCONSISTENT
    if result.status == SWITCH_FAILED:
        return EXIT_SWITCH_FAILED
    return EXIT_CONFIG if result.failure_category in {"configuration", "lock_configuration"} else EXIT_REJECTED


def summary(result: PublishResult) -> str:
    verb = "ROLLBACK" if result.action == "rollback" else "PUBLISH"
    headline = {PUBLISHED: "SUCCEEDED", REJECTED: "REJECTED (live site unchanged)", SWITCH_FAILED: "FAILED (live site unchanged)",
                INCONSISTENT: "SWITCHED, METADATA INCONSISTENT (new build is live; see below)",
                LOCKED: "NOT STARTED (LOCKED): another Atlas production operation is running; live site unchanged"}.get(result.status, result.status.upper())
    lines = [f"{verb} {headline}: publication {result.publication_id}",
             f"  build:          {result.attempt_id or 'none'}",
             f"  previous live:  {result.previous_attempt_id or 'none'}",
             f"  source raw run: {result.source_run_id or 'none'}"]
    if result.switched:
        lines.append(f"  live target:    {result.current_target} (since {result.published_at})")
    if result.lock and result.lock.get("holder"):
        holder = result.lock["holder"]
        lines.append(f"  lock holder (diagnostic): {holder.get('operation', 'unknown')} pid {holder.get('pid', '?')} since {holder.get('acquired_at', '?')}")
    if result.failure_category:
        lines.append(f"  failure:        {result.failure_stage} [{result.failure_category}]")
    lines += [f"  - {problem}" for problem in result.problems]
    return "\n".join(lines)
