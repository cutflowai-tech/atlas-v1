"""Production WSGI entry point of the Reasoning V3 web application (REV/20, ``REASONING-V3-PRODUCTION-ROLLOUT.md`` §2.3).

``gunicorn atlas_reasoning.wsgi:application`` serves exactly ``web_app.create_app()``: the same validated rollout, the same proxy-supplied
actor, allow-list, CSRF, Origin and security headers as every other path. It adds no route and relaxes nothing. Like ``create_app`` it
refuses to start with ``ATLAS_REASONING_V3`` off or an invalid rollout, and it opens no database connection until a request needs one.
"""

from __future__ import annotations

from atlas_reasoning.web_app import create_app

application = create_app()
