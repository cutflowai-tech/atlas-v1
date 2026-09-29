# Atlas operational alert state

`atlas_sync.alerts.update_alert_state()` is the Task 8 integration boundary. It accepts the
authoritative Task 7 runtime `StatusSnapshot`, persisted scheduled-cycle records, the configured
the validated operational state root (`ATLAS_LOCK_DIR`, normally `ATLAS_DATA_DIR/locks`), and an
observation timestamp. It performs no Monday request and sends no alert.

State and lifecycle events are one consistent document at
`ATLAS_LOCK_DIR/alerts/state.json`. The file is written to a same-directory temporary file, flushed,
atomically replaced, and the directory is synced. A corrupt or unsupported existing document fails
closed and is not overwritten. Each replacement uses a collision-resistant temporary filename, so
a stale temp file left by a killed process cannot block a later container/process restart. Callers
must serialize updates.

## Exact rules

- `data_stale`: critical exactly when Task 7 says `freshness_state == "stale"`. Task 7 owns the
  exact freshness boundary (`age >= stale_after_seconds`); this layer does not calculate it again.
- `consecutive_scheduled_failures`: trailing completed failed scheduler cycles are counted from the
  persisted cycle records. Running, locked, skipped, and malformed cycles are ignored. The newest
  completed success resets the count. Below `failure_threshold`, the count is exposed in
  `last_observation` and no incident exists. At the exact threshold and above the incident is critical.
- `publication_integrity`: critical when Task 7 says the live dashboard is unusable and a
  publication/build/raw/provenance health check is `failed`. A generic `system_state == failed` is
  never reinterpreted as publication failure.
- `publication_metadata_inconsistent`: warning when Task 7 emits its metadata warning or either
  `current_metadata` / `publication_history` is not passed.

One active incident exists per kind. Every repeated observation updates its occurrence count,
severity, evidence, and `last_observed_at`. When the condition disappears the incident is resolved;
`last_observed_at` remains the last time the condition was present and `resolved_at` records closure.
A later return creates a new incident with `previous_incident_id` and a `reactivated` event. Stored
evidence is allow-listed codes, IDs, counts, and thresholds only; raw exceptions and secrets are not
accepted.
