"""Atlas web presentation for contracts with the Editor interpretation layer (1.5.0+): the Editors app and the Editor report.

Contracts up to 1.4.0 keep their original pages byte for byte (``dashboard_html``, ``profile_html``; ``fixtures/golden``), so a
rollback to 1.4.0 also rolls back the presentation. Which renderer a build uses is decided by the contract's capabilities.
"""

from atlas_commander.web.app import render_app
from atlas_commander.web.report import render_report

__all__ = ["render_app", "render_report"]
