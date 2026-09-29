# Editor identity attestation record (D44, D48, D49)

**Why:** round-4 thresholds cannot be calibrated while most completed work belongs to unattested Editor Name labels. Management must confirm each identity **and** that the person was working as an Editor over the observed range. Presence in the Editor Name column, another column (e.g. Reviewer), a name, or project volume is not enough.

**Evidence:** production ingest run `20260929T130736Z-e6d03314e704` (board 5091110326, Editor Name column `dropdown_mm1emgt8`), Editor Name changes from 2026-03-14 to 2026-09-29. Monday logs the label name as it was at each change; the key is `(label ID, logged name)`.

The tables below retain the management-facing date summaries. Contract 1.5 uses these exact UTC occurrence bounds extracted from the
same verified run:

| Identity | First observed | Last observed |
|---|---|---|
| `(4, "Mario")` | `2026-03-14T00:44:34.286658Z` | `2026-09-28T23:40:30.586199Z` |
| `(5, "Anas")` | `2026-05-18T21:18:49.066589Z` | `2026-09-28T23:53:06.778508Z` |
| `(7, "Martin")` | `2026-05-12T16:18:07.005690Z` | `2026-09-28T23:46:48.811226Z` |
| `(8, "Samra")` | `2026-03-14T06:03:43.139996Z` | `2026-08-11T21:21:19.738906Z` |
| `(9, "Ibrahim")` | `2026-05-03T14:10:25.391996Z` | `2026-09-29T11:28:22.791445Z` |
| `(10, "Amir")` | `2026-04-22T16:43:52.478289Z` | `2026-09-28T23:50:05.196143Z` |
| `(11, "Refaat")` | `2026-06-29T01:31:10.174360Z` | `2026-09-28T23:51:39.316328Z` |
| `(5, "Ahmed")` | `2026-03-14T05:58:12.013277Z` | `2026-05-04T10:50:59.999145Z` |
| `(7, "Mans")` | `2026-03-14T06:03:36.639229Z` | `2026-05-06T08:13:45.547424Z` |
| `(9, "Michael")` | `2026-03-14T06:03:49.632351Z` | `2026-05-02T20:03:48.180209Z` |

## A. Confirmed Editor Name labels

| # | Identity `(label, logged name)` | Observed range | Projects | Question | Answer |
|---|---|---|---:|---|---|
| A1 | (4, "Mario") | 2026-03-14 → 2026-09-28 | 186 | Mario was an Editor for this whole range? | **Yes — Editor for the documented range.** |
| A2 | (5, "Anas") | 2026-05-18 → 2026-09-28 | 73 | Anas was an Editor from 2026-05-18 onward? | **Yes — Editor for the documented range.** |
| A3 | (7, "Martin") | 2026-05-12 → 2026-09-28 | 62 | Martin was an Editor from 2026-05-12 onward? | **Yes — Editor for the documented range.** |
| A4 | (8, "Samra") | 2026-03-14 → 2026-08-11 | 95 | Samra was an Editor for this whole range? | **Yes — Editor for the documented range.** |
| A5 | (9, "Ibrahim") | 2026-05-03 → 2026-09-29 | 132 | Ibrahim was an Editor from 2026-05-03 onward? | **Yes — Editor for the documented range.** |
| A6 | (10, "Amir") | 2026-04-22 → 2026-09-28 | 76 | Amir (also a Reviewer option) was working **as an Editor** on the projects carrying this label? | **Yes — Editor for the documented range.** |
| A7 | (11, "Refaat") | 2026-06-29 → 2026-09-28 | 53 | Refaat was an Editor from 2026-06-29 onward? | **Yes — Editor for the documented range.** |

## B. Early names that now also exist as separate mapped labels

Management confirmed both identity sameness and Editor role for each historical range, allowing the history to merge under the
canonical Editor.

| # | Early identity | Observed range | Projects | Same person as | Was an Editor then? | Answer |
|---|---|---|---:|---|---|---|
| B1 | (5, "Ahmed") | 2026-03-14 → 2026-05-04 | 46 | Ahmed, label 12? | yes | **Yes — same canonical Editor; Editor for the documented range.** |
| B2 | (7, "Mans") | 2026-03-14 → 2026-05-06 | 35 | Mansour, label 14? | yes | **Yes — same canonical Editor; Editor for the documented range.** |
| B3 | (9, "Michael") | 2026-03-14 → 2026-05-02 | 26 | Michael, label 13? | yes | **Yes — same canonical Editor; Editor for the documented range.** |

## C. Already decided (D50) — no answer needed

`(11, "New")` and `(2, "Done")` are invalid identity values; `(1, "El Baz")` stays an unresolved historical identity.

## Record

Attested by: **Waset management**  Role: **Management authority for Atlas identity decisions**  Date: **2026-09-29**

Scope: the attestations apply only to the observed ranges above. They do not create an ID-only mapping and do not alter the D50
quarantines.
