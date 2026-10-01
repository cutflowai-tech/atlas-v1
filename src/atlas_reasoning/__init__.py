"""Atlas Reasoning V3: management reasoning downstream of the deterministic Atlas pipeline (``REV/``, ``docs/REASONING-V3.md``).

Reasoning V3 sits after Intelligence V2 and never feeds back into it:

    Monday -> deterministic Atlas -> metrics -> Interpretation 1.5 -> Intelligence V2 -> reasoning_input_boundary -> Reasoning V3

- ``reasoning_input_boundary`` is the only module of this package that reads upstream Atlas output, and it reads only the
  published, language-neutral documents (``intelligence-v2.json``, ``publication.json``, ``profiles/*.json``) into a typed,
  immutable payload. No module of ``atlas_commander`` or ``atlas_sync`` imports this package (``tests/test_reasoning_boundary.py``).
- Reasoning V3 is disabled by default (``settings.ATLAS_REASONING_V3``). Disabled, Atlas behaves exactly as before.
- PostgreSQL holds the canonical Reasoning V3 state (``store``). LLM output is never the source of truth for any fact.
"""

REASONING_PACKAGE_VERSION = "reasoning-v3-foundation-1"
