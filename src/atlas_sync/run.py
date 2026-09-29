"""One production sync attempt: Monday -> immutable raw run -> production verification -> staged build.

    PYTHONPATH=src python3 -m atlas_sync run-once [--json]

The attempt only coordinates existing components; it adds no business rule:

 1. load and validate the deployment configuration (:func:`atlas_sync.config.load_sync_config`);
 2. create the read-only Monday client (with this attempt's time budget);
 3. the attempt has a unique ID (``YYYYMMDDTHHMMSSZ-<12 hex>``) and start time;
 4. ingest full history into a new immutable raw run (:func:`atlas_commander.ingest.ingest_run`);
 5. capture that run's ``run_id``; the build input is that run and no other;
 6. verify that exact run with ``ingest_verify --production``; on failure the attempt stops;
 8. create a new staging build directory ``<ATLAS_BUILD_DIR>/<attempt_id>/``;
 9. reconstruct cycles from the verified extract (its SHA-256 must still equal the manifest's);
10. build every Editor Profile; 11. build the CEO Dashboard (the existing profile CLI functions);
12. validate the generated artifacts; 13. write ``build.json`` (operational metadata);
14. write ``COMPLETE.json``, the completion marker, last; 15. return success.

The staged build is never published: this module only writes under the raw evidence root (through the
ingestion) and the build root. Publishing is a separate, later step.

Each attempt also writes a safe result record to ``<ATLAS_BUILD_DIR>/attempts/<attempt_id>.json`` once the
configuration is known. No record or artifact holds the Monday token, request headers or exception text.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander import site_layout
from atlas_commander.contracts import validate
from atlas_commander.cycles import COMPLETED
from atlas_commander.i18n import LOCALES
from atlas_commander.ingest import EXTRACT_NAME, MANIFEST_NAME, Clock, failure_category, ingest_run, new_run_id, tracked_columns, utc_now
from atlas_commander.ingest_verify import verify
from atlas_commander.pipeline import CycleReconstruction
from atlas_commander.profile import PROFILE_CONTRACTS, evidence_consistency_errors, profiled_editors
from atlas_commander.profile_cli import attribution_coverage, build_dashboard_files, build_profiles, reconstruct_extract
from atlas_monday_probe.client import DEFAULT_API_VERSION, ReadOnlyMondayClient, assert_read_only
from atlas_monday_probe.raw_store import inside_git_worktree, write_immutable_atomic

from .config import ConfigError, SyncConfig, load_sync_config
from .lock import EXIT_LOCKED, OperationLocked, production_lock
from .status import build_time_snapshot

Transport = Callable[[str, dict[str, Any]], bytes]

BUILD_METADATA_VERSION = "atlas-build-v1"
SITE_DIR = "site"                       # the generated profiles and dashboard: what a later publish step would serve
BUILD_METADATA_NAME = "build.json"      # operational metadata, outside the site
COMPLETE_NAME = "COMPLETE.json"         # completion marker, written last and only after every check passed
FAILED_NAME = "FAILED.json"             # present only in a build directory whose attempt failed
ATTEMPTS_DIR = "attempts"               # <build root>/attempts/<attempt_id>.json: one safe result per attempt
STAGES = ("configuration", "lock", "monday_client", "ingestion", "verification", "build_directory", "reconstruction", "profiles", "dashboard",
          "validation", "metadata", "completion")
PROFILE_SCHEMAS = dict(PROFILE_CONTRACTS)
STAGED_NOTE = "Staged build only: it has not been published, and the published dashboard was not modified."


class SyncTimeout(RuntimeError):
    """The attempt's time budget is spent; nothing further is started."""

    failure_category = "timeout"

    def __init__(self, next_step: str, elapsed: float, limit: float) -> None:
        super().__init__(f"sync time budget of {limit:g}s exhausted after {elapsed:.1f}s; not starting {next_step}")
        self.next_step = next_step


class VerificationFailed(RuntimeError):
    failure_category = "verification_failed"


class BuildDirectoryError(RuntimeError):
    failure_category = "build_directory"


class BuildValidationError(RuntimeError):
    failure_category = "build_validation"

    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"{len(problems)} build validation problem(s)")
        self.problems = problems


class Budget:
    """Elapsed-time budget on a monotonic clock. Checked before every stage, every Monday request and every retry wait.

    It never interrupts work already running (no thread killing): an operation in progress finishes or fails on its own."""

    def __init__(self, limit_seconds: float, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 started: float | None = None) -> None:
        self.limit = float(limit_seconds)
        self._monotonic, self._sleep = monotonic, sleep
        self.started = monotonic() if started is None else started

    def elapsed(self) -> float:
        return self._monotonic() - self.started

    def remaining(self) -> float:
        return self.limit - self.elapsed()

    def check(self, next_step: str) -> None:
        if self.remaining() <= 0:
            raise SyncTimeout(next_step, self.elapsed(), self.limit)

    def sleep(self, seconds: float) -> None:
        """A retry wait that would end after the budget is refused before it starts."""
        if seconds >= self.remaining():
            raise SyncTimeout("a Monday retry wait", self.elapsed(), self.limit)
        self._sleep(seconds)


class BudgetedMondayClient(ReadOnlyMondayClient):
    """The read-only client, refusing to start a request or a retry wait once the attempt's budget is spent."""

    def __init__(self, transport: Transport, api_version: str = DEFAULT_API_VERSION, *, budget: Budget, **options: Any) -> None:
        super().__init__(transport, api_version, sleep=budget.sleep, **options)
        self.budget = budget

    def query(self, query: str, variables: dict[str, Any]) -> bytes:
        assert_read_only(query)   # the read-only guard stays first
        self.budget.check("a Monday request")
        return super().query(query, variables)


@dataclass
class SyncResult:
    """Safe, JSON-ready outcome of one attempt (no token, headers or exception text)."""

    attempt_id: str
    status: str = "running"
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    failing_stage: str | None = None
    error_category: str | None = None
    error_type: str | None = None
    source_run_id: str | None = None
    raw_run_dir: str | None = None
    staged_build_dir: str | None = None
    editor_count: int | None = None
    verification: dict[str, Any] | None = None
    attempt_record: str | None = None
    published: bool = False
    lock: dict[str, Any] | None = None   # set only when the production lock was held by another operation

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# A failure with no more specific category, in a stage after ingestion, is named after that stage.
STAGE_CATEGORIES = {"reconstruction": "reconstruction", "profiles": "profile_generation", "dashboard": "dashboard_generation",
                    "validation": "build_validation", "metadata": "build_metadata", "completion": "build_metadata"}


def _category(error: BaseException, stage: str) -> str:
    if isinstance(error, ConfigError):
        return "configuration"
    category = failure_category(error)   # declared (timeout, verification, build), Monday, raw store, interrupted, ...
    if stage in STAGE_CATEGORIES and category in {"unexpected_response", "internal"}:
        return STAGE_CATEGORIES[stage]
    return category


def _client(config: SyncConfig, budget: Budget, transport: Transport | None) -> ReadOnlyMondayClient:
    token = config.require_monday_token()   # fail closed without a token, whatever the transport
    if transport is not None:
        return BudgetedMondayClient(transport, config.monday_api_version, budget=budget)
    return BudgetedMondayClient.from_token(token.reveal(), config.monday_api_version, budget=budget)


def _create_build_dir(build_root: Path, attempt_id: str) -> Path:
    """``<build root>/<attempt_id>``, created exclusively: an attempt never writes into another attempt's build."""
    root = build_root.expanduser().resolve()
    if inside_git_worktree(root):
        raise BuildDirectoryError(f"builds hold real Monday data and must be outside git: {root}")
    root.mkdir(parents=True, exist_ok=True)
    path = root / attempt_id
    try:
        path.mkdir()
    except FileExistsError:
        raise BuildDirectoryError(f"build directory already exists: {path}") from None
    (path / SITE_DIR).mkdir()
    return path


def _files(root: Path) -> dict[str, Path]:
    return {path.relative_to(root).as_posix(): path for path in sorted(root.rglob("*")) if path.is_file()}


def _token_bytes(config: SyncConfig) -> bytes | None:
    return config.monday_token.reveal().encode() if config.monday_token is not None and config.monday_token.reveal() else None


def validate_site(site: Path, result: CycleReconstruction, contract: Mapping[str, Any], extract: Mapping[str, Any],
                  manifest: Mapping[str, Any], token: bytes | None) -> dict[str, dict[str, Any]]:
    """Check the generated site against the reconstruction and the source run; return the artifact hashes.

    Uses the existing schema validation for profiles. It checks presence, integrity and provenance only: no
    performance rule is evaluated here."""
    problems: list[str] = []
    editors = [editor["editor_id"] for editor in profiled_editors(result)]
    required = site_layout.required_files(editors, contract["contract_version"])   # both languages: a build missing either one is incomplete
    files = _files(site)
    problems += [f"missing required artifact {name}" for name in required if name not in files]
    problems += [f"unexpected artifact {name}" for name in files if name not in required]
    problems += [f"empty artifact {name}" for name, path in files.items() if path.stat().st_size == 0]
    if token:
        problems += [f"artifact {name} contains the Monday token" for name, path in files.items() if token in path.read_bytes()]

    problems += site_layout.publication_problems(files, editors, contract["contract_version"], extract.get("retrieved_at"))

    for name, locale in site_layout.html_files(editors).items():
        path = files.get(name)
        if path is not None and not path.read_text(encoding="utf-8").startswith(site_layout.document_opening(locale)):
            problems.append(f"{name} does not declare lang={locale} and its direction")

    retrieved_at = extract.get("retrieved_at")
    window = manifest["window"]
    for editor in editors:
        path = files.get(f"profiles/{editor}.json")
        if path is None or path.stat().st_size == 0:
            continue
        try:
            profile = json.loads(path.read_text())
        except ValueError:
            problems.append(f"profiles/{editor}.json is not valid JSON")
            continue
        schema = PROFILE_SCHEMAS.get(profile.get("contract_version"))
        if schema is None:
            problems.append(f"profiles/{editor}.json has unknown profile contract {profile.get('contract_version')!r}")
        elif errors := validate(profile, schema) + evidence_consistency_errors(profile):
            problems.append(f"profiles/{editor}.json violates {schema}: {errors}")
        if (profile.get("editor") or {}).get("editor_id") != editor:
            problems.append(f"profiles/{editor}.json is for another Editor")
        source = profile.get("source") or {}
        if source.get("retrieved_at") != retrieved_at or (source.get("history_coverage") or {}).get("activity_log_window") != window:
            problems.append(f"profiles/{editor}.json does not come from source run {manifest['run']['run_id']}")
        if profile.get("executable_contract_version") != contract["contract_version"]:
            problems.append(f"profiles/{editor}.json was built with another contract")

    path = files.get(site_layout.DASHBOARD_JSON)
    if path is not None and path.stat().st_size:
        try:
            dashboard = json.loads(path.read_text())
        except ValueError:
            problems.append("dashboard.json is not valid JSON")
        else:
            source = dashboard.get("source") or {}
            if source.get("retrieved_at") != retrieved_at or source.get("executable_contract_version") != (contract["contract_version"] if editors else None):
                problems.append("dashboard.json does not come from the source run and contract")
            summaries = dashboard.get("editors")
            if not isinstance(summaries, list) or sorted(s.get("editor_id") for s in summaries) != sorted(editors):
                problems.append("dashboard.json does not list exactly the built Editors")
    if problems:
        raise BuildValidationError(problems)
    return {name: {"sha256": _sha256(path.read_bytes()), "size_bytes": path.stat().st_size} for name, path in files.items()}


def _counts(result: CycleReconstruction, manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Counts the existing pipeline already exposes; nothing is re-derived or re-classified here."""
    completed = [cycle for cycle in result.cycles if cycle.state == COMPLETED]
    coverage = attribution_coverage(result)
    counts = {
        "items": manifest["counts"]["items"],
        "column_logs": manifest["counts"]["column_logs"],
        "create_pulse": manifest["counts"]["create_pulse"],
        "items_with_complete_history": manifest["counts"]["items_with_complete_history"],
        "status_events": len(result.status_events),
        "projects": len({cycle.monday_item_id for cycle in result.cycles}),
        "cycles": len(result.cycles),
        "completed_cycles": len(completed),
        "completed_cycles_attributed": coverage["attributed"],
    }
    exclusions = {
        "quarantined_status_logs": len(result.quarantined_status_logs),
        "rejected_logs": len(result.rejected_logs),
        "completed_not_attributed_by_reason": coverage["not_attributed_by_reason"],
        "cycle_exclusions_by_reason": dict(sorted(Counter(reason for cycle in result.cycles for reason in cycle.exclusions).items())),
    }
    return counts, exclusions


def _check_metadata(build: Path, metadata_bytes: bytes, config: SyncConfig, manifest: Mapping[str, Any], raw_run: Path, token: bytes | None) -> None:
    """``build.json`` as written agrees with the source run's manifest and with the files it hashes."""
    problems: list[str] = []
    metadata = json.loads(metadata_bytes)
    source = metadata["source"]
    if not (source["run_id"] == manifest["run"]["run_id"] == raw_run.name) or source["raw_run_dir"] != str(raw_run):
        problems.append("source run_id does not identify the verified raw run")
    if source["coverage"] != manifest["coverage"]:
        problems.append("coverage differs from the source run")
    if metadata["monday"] != {"board_id": manifest["monday"]["board_id"], "api_version": manifest["monday"]["api_version"]} \
            or metadata["monday"]["board_id"] != config.board_id:
        problems.append("Monday board or API version differs from the source run")
    if metadata["contract_version"] != manifest["contract_version"] or metadata["contract_version"] != config.contract_version:
        problems.append("contract version differs from the source run")
    if source["extract_sha256"] != manifest["extract"]["sha256"]:
        problems.append("extract hash differs from the verified manifest")
    site = build / SITE_DIR
    on_disk = {name: _sha256(path.read_bytes()) for name, path in _files(site).items()}
    if {name: record["sha256"] for name, record in metadata["artifacts"]["files"].items()} != on_disk:
        problems.append("artifact hashes do not match the generated files")
    if metadata["editor_count"] != len(metadata["editors"]) or metadata["editor_count"] != sum(1 for n in on_disk if n.startswith("profiles/") and n.endswith(".json")):
        problems.append("editor count does not match the generated profiles")
    if token and token in metadata_bytes:
        problems.append("build metadata contains the Monday token")
    if problems:
        raise BuildValidationError(problems)


def _write_json(root: Path, name: str, document: Mapping[str, Any]) -> tuple[Path, bytes]:
    data = json.dumps(document, indent=1, sort_keys=True).encode() + b"\n"
    return write_immutable_atomic(root, name, data).path, data


def run_once(environ: Mapping[str, str] | None = None, *, config: SyncConfig | None = None, transport: Transport | None = None,
             clock: Clock = utc_now, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
             attempt_id_factory: Callable[[datetime], str] = new_run_id, max_duration_seconds: float | None = None,
             monday_item_url: str | None = None) -> SyncResult:
    """Run one sync attempt and return its :class:`SyncResult`. Never publishes; never raises for a failed stage.

    Holds the production lock (:mod:`atlas_sync.lock`) from before the Monday client is created until the attempt
    record is written. If another production operation holds it, nothing is read, written or built: the result has
    status ``locked``. This is the ownership layer for run-once; callers (including the CLI) must not take the lock.

    ``transport`` replaces the HTTPS transport (tests); ``clock``/``monotonic``/``sleep`` make timing deterministic."""
    t0 = monotonic()
    started = clock()
    result = SyncResult(attempt_id=attempt_id_factory(started), started_at=_iso(started))
    lock = ExitStack()
    try:
        return _attempt(result, lock, environ, config, transport, clock, monotonic, sleep, max_duration_seconds,
                        monday_item_url, t0, started, acquire_lock=True)
    finally:
        lock.close()   # releases the production lock, whatever happened


def _attempt(result: SyncResult, lock: ExitStack, environ: Mapping[str, str] | None, cfg: SyncConfig | None, transport: Transport | None,
             clock: Clock, monotonic: Callable[[], float], sleep: Callable[[float], None], max_duration_seconds: float | None,
             monday_item_url: str | None, t0: float, started: datetime, *, acquire_lock: bool) -> SyncResult:
    stage = STAGES[0]
    build: Path | None = None
    run_ids: list[str] = []
    held = False

    def remember(moment: datetime) -> str:
        run_ids.append(new_run_id(moment))
        return run_ids[-1]

    try:
        if cfg is None:
            cfg = load_sync_config(environ, require_token=True, now=started)
        contract = cfg.contract()

        stage = "lock"   # before any Monday request, raw run or build; held for the rest of the attempt
        if acquire_lock:
            lock.enter_context(production_lock(cfg, "run-once", target=result.attempt_id, clock=clock))
        held = True
        budget = Budget(max_duration_seconds if max_duration_seconds is not None else cfg.max_sync_duration_seconds, monotonic, sleep, started=t0)

        stage = "monday_client"
        budget.check(stage)
        client = _client(cfg, budget, transport)

        stage = "ingestion"
        budget.check(stage)
        manifest = ingest_run(client, cfg.board_id, tracked_columns(contract["source_board"]), cfg.history_start, cfg.raw_dir,
                              clock=clock, contract_version=cfg.contract_version, run_id_factory=remember)
        run_id = manifest["run"]["run_id"]
        raw_run = (cfg.raw_dir / run_id).expanduser().resolve()

        stage = "verification"
        budget.check(stage)
        report = verify(raw_run, require_production=True)
        result.verification = {"passed": report["passed"], "status": report.get("status"), "require_production": True,
                               "raw_files_checked": report.get("raw_files_checked"), "failures": report["failures"][:20]}
        if not report["passed"] or report.get("run_id") != run_id:
            raise VerificationFailed(f"raw run {run_id} failed production verification")

        stage = "build_directory"
        budget.check(stage)
        build = _create_build_dir(cfg.build_dir, result.attempt_id)
        result.staged_build_dir = str(build)
        site = build / SITE_DIR
        build_started_at = _iso(clock())

        stage = "reconstruction"
        budget.check(stage)
        extract_bytes = (raw_run / EXTRACT_NAME).read_bytes()
        if _sha256(extract_bytes) != manifest["extract"]["sha256"]:
            raise VerificationFailed("extract changed after verification")
        extract = json.loads(extract_bytes)
        reconstruction = reconstruct_extract(extract, contract)

        stage = "profiles"
        budget.check(stage)
        generated_at = _iso(clock())
        profiles, pages = build_profiles(reconstruction, contract, site, generated_at, monday_item_url)

        stage = "dashboard"
        budget.check(stage)
        status_snapshot = build_time_snapshot(
            config=cfg, generated_at=generated_at, attempt_id=result.attempt_id,
            source_run_id=run_id, retrieved_at=manifest["retrieved_at"],
            coverage=manifest["coverage"], verified=bool(result.verification["passed"]),
            started_at=result.started_at,
        )
        build_dashboard_files(reconstruction, contract, site, generated_at, profiles, pages, monday_item_url,
                              status_snapshot=status_snapshot.as_dict())

        stage = "validation"
        budget.check(stage)
        token = _token_bytes(cfg)
        artifacts = validate_site(site, reconstruction, contract, extract, manifest, token)
        editors = profiled_editors(reconstruction)
        result.editor_count = len(editors)

        stage = "metadata"
        budget.check(stage)
        counts, exclusions = _counts(reconstruction, manifest)
        metadata = {
            "build_metadata_version": BUILD_METADATA_VERSION,
            "attempt": {"attempt_id": result.attempt_id, "sync_started_at": result.started_at, "build_started_at": build_started_at,
                        "profiles_generated_at": generated_at, "build_completed_at": _iso(clock())},
            "source": {"run_id": run_id, "raw_run_dir": str(raw_run), "retrieved_at": manifest["retrieved_at"], "coverage": manifest["coverage"],
                       "manifest_sha256": _sha256((raw_run / MANIFEST_NAME).read_bytes()), "extract_sha256": manifest["extract"]["sha256"]},
            "monday": {"board_id": manifest["monday"]["board_id"], "api_version": manifest["monday"]["api_version"]},
            "contract_version": manifest["contract_version"],
            "verification": {key: result.verification[key] for key in ("passed", "status", "require_production", "raw_files_checked")},
            "editor_count": len(editors),
            "editors": editors,
            "counts": counts,
            "exclusions": exclusions,
            "artifacts": {"root": SITE_DIR, "entry": site_layout.ROOT_ENTRY, "locales": list(LOCALES), "files": artifacts},
            "published": False,
            "note": STAGED_NOTE,
        }
        _, metadata_bytes = _write_json(build, BUILD_METADATA_NAME, metadata)
        _check_metadata(build, metadata_bytes, cfg, manifest, raw_run, token)

        stage = "completion"
        budget.check(stage)
        _write_json(build, COMPLETE_NAME, {"status": "complete", "attempt_id": result.attempt_id, "source_run_id": run_id,
                                           "build_metadata_sha256": _sha256(metadata_bytes), "completed_at": _iso(clock()),
                                           "published": False, "note": STAGED_NOTE})
        result.status = "success"
    except OperationLocked as locked:   # another operation is running: nothing was started, nothing is written
        _fail(result, stage, locked)
        result.status, result.lock = "locked", locked.as_dict()
    except Exception as error:   # noqa: BLE001 - every failure ends the attempt; it is recorded, never hidden as success
        _fail(result, stage, error)
    except BaseException as error:   # interrupted: record it, then let the interruption propagate (the lock is released after)
        _fail(result, stage, error)
        _finish(result, cfg if held else None, build, run_ids, clock, monotonic, t0)
        raise
    _finish(result, cfg if held else None, build, run_ids, clock, monotonic, t0)   # records are written only under the lock
    return result


def _run_once_locked(*, config: SyncConfig, transport: Transport | None = None, clock: Clock = utc_now,
                     monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                     attempt_id_factory: Callable[[datetime], str] = new_run_id,
                     max_duration_seconds: float | None = None, monday_item_url: str | None = None) -> SyncResult:
    """Run one exact attempt while the caller holds the shared production lock.

    Private by design: public :func:`run_once` remains the ownership boundary for direct callers. The scheduled
    cycle owns the same lock across this helper and the exact-attempt publish helper, avoiding re-entry.
    """
    t0, started = monotonic(), clock()
    result = SyncResult(attempt_id=attempt_id_factory(started), started_at=_iso(started))
    lock = ExitStack()
    try:
        return _attempt(result, lock, None, config, transport, clock, monotonic, sleep, max_duration_seconds,
                        monday_item_url, t0, started, acquire_lock=False)
    finally:
        lock.close()


def _fail(result: SyncResult, stage: str, error: BaseException) -> None:
    result.status = "failed"
    result.failing_stage = stage
    result.error_category = _category(error, stage)
    result.error_type = type(error).__name__
    result.editor_count = None


def _finish(result: SyncResult, cfg: SyncConfig | None, build: Path | None, run_ids: list[str], clock: Clock,
            monotonic: Callable[[], float], t0: float) -> None:
    if run_ids and cfg is not None:
        result.source_run_id = run_ids[-1]
        result.raw_run_dir = str((cfg.raw_dir / run_ids[-1]).expanduser().resolve())
    result.finished_at = _iso(clock())
    result.duration_seconds = round(monotonic() - t0, 3)
    record = result.as_dict()
    if build is not None and result.status != "success":
        try:   # the build directory's own failure marker; its partial files stay for diagnosis
            _write_json(build, FAILED_NAME, {**record, "note": "Failed attempt: this build is incomplete and must never be published."})
        except Exception:  # noqa: BLE001, S110 - never mask the original failure; the missing COMPLETE.json still marks it unusable
            pass
    if cfg is not None:
        try:
            path, _ = _write_json(cfg.build_dir.expanduser().resolve() / ATTEMPTS_DIR, f"{result.attempt_id}.json", record)
            result.attempt_record = str(path)
        except Exception:  # noqa: BLE001 - the attempt's outcome is decided; a missing record is reported as attempt_record None
            result.attempt_record = None


def build_state(build: Path) -> str:
    """``complete`` (marker present, no failure record), ``failed`` or ``incomplete``."""
    if (build / FAILED_NAME).exists():
        return "failed"
    return "complete" if (build / COMPLETE_NAME).is_file() else "incomplete"


EXIT_OK, EXIT_ACCESS, EXIT_MONDAY, EXIT_VERIFICATION, EXIT_BUILD, EXIT_TIMEOUT = 0, 2, 3, 4, 5, 6
ACCESS_CATEGORIES = {"configuration", "lock_configuration", "invalid_configuration", "missing_access", "authentication", "permission"}


def exit_code(result: SyncResult) -> int:
    if result.status == "success":
        return EXIT_OK
    if result.status == "locked":
        return EXIT_LOCKED
    if result.error_category == "timeout":
        return EXIT_TIMEOUT
    if result.error_category in ACCESS_CATEGORIES:
        return EXIT_ACCESS
    if result.failing_stage in {"monday_client", "ingestion"}:
        return EXIT_MONDAY
    if result.failing_stage == "verification":
        return EXIT_VERIFICATION
    return EXIT_BUILD


def summary(result: SyncResult) -> str:
    if result.status == "locked":
        holder = (result.lock or {}).get("holder") or {}
        return "\n".join([f"SYNC NOT STARTED (LOCKED): another Atlas production operation is running; attempt {result.attempt_id} did nothing",
                          f"  lock holder (diagnostic): {holder.get('operation', 'unknown')} pid {holder.get('pid', '?')} since {holder.get('acquired_at', '?')}",
                          "  NOT PUBLISHED: nothing was read from Monday, built or published."])
    lines = [f"SYNC {'SUCCEEDED' if result.status == 'success' else 'FAILED'}: attempt {result.attempt_id}"]
    if result.status != "success":
        lines.append(f"  failed at stage: {result.failing_stage} [{result.error_category}]")
    lines += [f"  source raw run: {result.source_run_id or 'none'}" + (f" ({result.raw_run_dir})" if result.raw_run_dir else ""),
              f"  staged build:   {result.staged_build_dir or 'none'}"]
    if result.editor_count is not None:
        lines.append(f"  Editors built:  {result.editor_count}")
    lines += [f"  duration:       {result.duration_seconds or 0:.1f}s",
              f"  attempt record: {result.attempt_record or 'not written'}",
              "  NOT PUBLISHED: this command only stages a build; the published dashboard was not modified."]
    return "\n".join(lines)
