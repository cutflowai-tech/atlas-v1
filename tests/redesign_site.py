"""One showcase site build shared by the redesign tests (built once per test process, removed at exit)."""

from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from atlas_commander import profile_cli, site_layout
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.runtime import load_contract_version

CONTRACT = load_contract_version("1.5.0")


@lru_cache(maxsize=1)
def site() -> Path:
    out = Path(tempfile.mkdtemp(prefix="atlas-redesign-site-"))
    atexit.register(shutil.rmtree, out, True)
    result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT)
    profile_cli.build_all(result, CONTRACT, out, GENERATED_AT)
    return out


def page(locale: str) -> str:
    return (site() / site_layout.dashboard_html(locale)).read_text(encoding="utf-8")


def document(name: str) -> Any:
    return json.loads((site() / name).read_text())
