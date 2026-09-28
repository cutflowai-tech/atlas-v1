from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "risk-policy.json"
DAG_PATH = ROOT / "tasks" / "dag.json"

CRITICAL_FLAGS = {"business_rules", "schema", "security", "money", "destructive_migration"}
REQUIRED_TASK_FIELDS = {
    "id", "title", "risk", "status", "depends_on", "acceptance_tests",
    "evidence_requirements", "affected_contracts", "contract_owner_gate",
}

ROUTES = {
    "simple": [
        {"slot": "builder-1", "runtime": "Atlas Codex W", "family": "codex"},
        {"slot": "reviewer-1", "runtime": "Atlas Codex A", "family": "codex"},
        {"slot": "integrator", "runtime": "Atlas Arbiter Integrator", "family": "codex"},
    ],
    "normal": [
        {"slot": "builder-1", "runtime": "Atlas Builder Codex M", "family": "codex"},
        {"slot": "builder-2", "runtime": "Atlas Builder Claude A", "family": "claude"},
        {"slot": "reviewer-1", "runtime": "Atlas Validator Codex", "family": "codex"},
        {"slot": "arbiter", "runtime": "Atlas Arbiter Integrator", "family": "codex"},
        {"slot": "integrator", "runtime": "Atlas Arbiter Integrator", "family": "codex"},
    ],
    "critical": [
        {"slot": "builder-1", "runtime": "Atlas Builder Codex M", "family": "codex"},
        {"slot": "builder-2", "runtime": "Atlas Builder Codex W", "family": "codex"},
        {"slot": "builder-3", "runtime": "Atlas Builder Claude A", "family": "claude"},
        {"slot": "validator-1", "runtime": "Atlas Validator Codex", "family": "codex"},
        {"slot": "validator-2", "runtime": "Atlas Validator Claude", "family": "claude"},
        {"slot": "arbiter", "runtime": "Atlas Arbiter Integrator", "family": "codex"},
        {"slot": "integrator", "runtime": "Atlas Arbiter Integrator", "family": "codex"},
    ],
}


def classify(flags: set[str]) -> str:
    if flags & CRITICAL_FLAGS:
        return "critical"
    if "multi_component" in flags or "external_integration" in flags:
        return "normal"
    return "simple"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text())


def slots_for(risk: str) -> list[str]:
    return [assignment["slot"] for assignment in ROUTES[risk]]


def assignments_for(risk: str) -> list[dict]:
    assignments = ROUTES[risk]
    policy = load_policy()[risk]
    builder_families = {item["family"] for item in assignments if item["slot"].startswith("builder-")}
    if policy["requires_cross_family"] and len(builder_families) < 2:
        raise ValueError(f"{risk} routing requires builders from at least two model families")
    return assignments


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def fanout(task_id: str, risk: str, base: str) -> dict:
    safe_id = task_id.lower().replace("_", "-")
    run_dir = ROOT / ".atlas" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    assignments = []
    for routing in assignments_for(risk):
        slot = routing["slot"]
        if slot in {"arbiter", "integrator"}:
            continue
        branch = f"task/{safe_id}/{slot}"
        path = ROOT / ".worktrees" / safe_id / slot
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assignments.append({**routing, "branch": branch, "worktree": str(path), "existing": True})
            continue
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        if branch_exists:
            git("worktree", "add", str(path), branch)
        else:
            git("worktree", "add", "-b", branch, str(path), base)
        assignments.append({**routing, "branch": branch, "worktree": str(path), "existing": False})
    manifest = {"task_id": task_id, "risk": risk, "base": base, "assignments": assignments}
    (run_dir / "fanout.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def ready_tasks() -> list[dict]:
    tasks = json.loads(DAG_PATH.read_text())["tasks"]
    for task in tasks:
        missing = REQUIRED_TASK_FIELDS - set(task)
        if missing:
            raise ValueError(f"task {task.get('id', '<unknown>')} missing fields: {sorted(missing)}")
    by_id = {task["id"]: task for task in tasks}
    ready = []
    for task in tasks:
        deps_done = all(by_id.get(dep, {}).get("status") == "done" for dep in task.get("depends_on", []))
        gate_ok = task.get("contract_owner_gate", "not_required") in {"approved", "not_required"}
        if task.get("status") in {"todo", "ready"} and deps_done and gate_ok:
            ready.append(task)
    return ready


def doctor() -> int:
    commands = ["git", "gh", "docker", "jq", "mise", "multica", "codex-a", "codex-m", "codex-w", "claude-a", "claude-m", "hermes"]
    missing = [command for command in commands if shutil.which(command) is None]
    branch = git("branch", "--show-current")
    report = {"missing_commands": missing, "branch": branch, "policy": str(POLICY_PATH), "dag": str(DAG_PATH)}
    print(json.dumps(report, indent=2))
    return 1 if missing else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="Atlas V1 swarm commander")
    sub = parser.add_subparsers(dest="command", required=True)
    classify_parser = sub.add_parser("classify")
    classify_parser.add_argument("--title", required=True)
    for flag in sorted(CRITICAL_FLAGS | {"multi_component", "external_integration"}):
        classify_parser.add_argument(f"--{flag.replace('_', '-')}", action="store_true")
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--risk", choices=["simple", "normal", "critical"], required=True)
    fanout_parser = sub.add_parser("fanout")
    fanout_parser.add_argument("task_id")
    fanout_parser.add_argument("--risk", choices=["simple", "normal", "critical"], required=True)
    fanout_parser.add_argument("--base", default="integration")
    sub.add_parser("ready")
    sub.add_parser("doctor")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "classify":
        active = {name for name in CRITICAL_FLAGS | {"multi_component", "external_integration"} if getattr(args, name)}
        risk = classify(active)
        print(json.dumps({"title": args.title, "risk": risk, "policy": load_policy()[risk]}, indent=2))
        return 0
    if args.command == "plan":
        print(json.dumps({"risk": args.risk, "assignments": assignments_for(args.risk)}, indent=2))
        return 0
    if args.command == "fanout":
        print(json.dumps(fanout(args.task_id, args.risk, args.base), indent=2))
        return 0
    if args.command == "ready":
        print(json.dumps(ready_tasks(), indent=2))
        return 0
    return doctor()


if __name__ == "__main__":
    sys.exit(main())
