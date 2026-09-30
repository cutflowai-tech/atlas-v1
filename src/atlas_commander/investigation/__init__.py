"""Atlas Intelligence V2: a deterministic, auditable investigation layer over the contract 1.5 engine.

The layer reads what the existing engine already produced (the cycle reconstruction, deadline results, Quality label
occurrences and the finished Editor Profiles) and turns it into structured *findings*: evidence -> pattern ->
interpretation -> management significance -> suggested investigation. It is never an input to a metric, a component state,
Overall Status or Trend, and it writes nothing back into the documents it reads.

Modules, in data-flow order:

- ``policy``: parameters with their approval state (D25) and the two run modes (``approved_only`` / ``review``);
- ``models``: the Finding, Statement and evidence structures and their invariants;
- ``facts``: one fact row per completed project, item stage timelines and current open work;
- ``stats`` and ``baselines``: robust descriptive statistics, team / Video Type / Editor / time baselines;
- ``confidence``: explainable evidence strength, kept separate from importance;
- detector families: ``concentration``, ``bottlenecks``, ``changes``, ``workload``, ``patterns``, ``person_system``,
  ``contradictions``, ``risks``, ``editor``, ``data_quality``;
- ``prioritization``, ``graph``, ``narrative``, ``ai_guard``: ranking, de-duplication, the finding relationship graph,
  deterministic wording and the guard for an optional AI rewrite;
- ``engine``: builds the ``intelligence-v2`` document; ``html``: a minimal review page; ``__main__``: the CLI.
"""

INTELLIGENCE_V2_VERSION = "intelligence-v2.0.0"
