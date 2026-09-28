# DATA-001 schema drift report

Observed source: Customer Projects board 5091110326, snapshot dated 2026-07-25.
The source is Markdown, not an original GraphQL response. Its heading reports
959 returned items. It has board metadata, columns, groups and items sections;
no `activity_logs` key is present. The manifest records the exact source hash.
Source timestamp lexeme counts are occurrences, not unique events or work cycles.

| Contract requirement | Evidence and disposition |
| --- | --- |
| event_id and occurred_at | No activity event envelope available. Item created_at/updated_at cannot replace status-change time. |
| monday_board_id | 5091110326 is supplied and matches the export filename. |
| monday_item_id and status_column_id | Export has source identifiers; no event-to-item/column linkage has been verified. |
| from_status and to_status | No transition pair or approved versioned status mapping established. |
| actor_resolution and canonical actor mapping | No verified canonical Editor selected. Actor identity is not Editor assignment. No mapping guessed. |
| contract_version | No normalized records emitted. Frozen schema remains 1.0.0. |

This is an input capability gap, not a demonstrated breaking change to Monday's
live schema. Live API drift is unmeasured because access is unavailable. The
adapter reports missing/extra field row counts and invalid scalar types without
exposing values. It preserves raw response bytes before rejecting schema drift,
GraphQL errors, mismatched boards, or duplicates. Activity `data` stays an opaque
source string; payload-specific transition mapping remains future work.

The adapter uses documented board activity fields and explicit dated API versions:
https://developer.monday.com/api-reference/reference/activity-logs
It retains the documented 17-digit created_at string without rounding or converting
it into the contract's date-time. API pagination completion does not establish
historical completeness beyond the account's retention window or under concurrent
source changes. No metric output is supported by this sample.
