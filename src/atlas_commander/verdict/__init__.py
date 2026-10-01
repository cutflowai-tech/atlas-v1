"""The redesign's judgment layer (D54): verdicts, tiers, ranks, confidence, reasons and decisions, computed at build time.

It reads the published documents of one snapshot (``dashboard.json`` and, when present, ``intelligence-v2.json``) and writes
``verdicts.json``; the page renders it and computes nothing. Every sentence is a message key (``Msg``) so English and Arabic render
the same judgment. See ``docs/redesign/`` and ``contracts/verdict-v1.schema.json``.
"""
