# Editor identity attestation request (D44, D48, D49)

**Why:** round-4 thresholds cannot be calibrated while most completed work belongs to unattested Editor Name labels. Management must confirm each identity **and** that the person was working as an Editor over the observed range. Presence in the Editor Name column, another column (e.g. Reviewer), a name, or project volume is not enough.

**Evidence:** production ingest run `20260929T130736Z-e6d03314e704` (board 5091110326, Editor Name column `dropdown_mm1emgt8`), Editor Name changes from 2026-03-14 to 2026-09-29. Monday logs the label name as it was at each change; the key is `(label ID, logged name)`.

## A. Unattested Editor Name labels

| # | Identity `(label, logged name)` | Observed range | Projects | Question | Answer |
|---|---|---|---:|---|---|
| A1 | (4, "Mario") | 2026-03-14 → 2026-09-28 | 186 | Mario was an Editor for this whole range? | yes / no / from … |
| A2 | (5, "Anas") | 2026-05-18 → 2026-09-28 | 73 | Anas was an Editor from 2026-05-18 onward? | yes / no / from … |
| A3 | (7, "Martin") | 2026-05-12 → 2026-09-28 | 62 | Martin was an Editor from 2026-05-12 onward? | yes / no / from … |
| A4 | (8, "Samra") | 2026-03-14 → 2026-08-11 | 95 | Samra was an Editor for this whole range? | yes / no / from … |
| A5 | (9, "Ibrahim") | 2026-05-03 → 2026-09-29 | 132 | Ibrahim was an Editor from 2026-05-03 onward? | yes / no / from … |
| A6 | (10, "Amir") | 2026-04-22 → 2026-09-28 | 76 | Amir (also a Reviewer option) was working **as an Editor** on the projects carrying this label? | yes / no / from … |
| A7 | (11, "Refaat") | 2026-06-29 → 2026-09-28 | 53 | Refaat was an Editor from 2026-06-29 onward? | yes / no / from … |

## B. Early names that now also exist as separate mapped labels

Each needs **both** answers to merge the history under one Editor; otherwise the early identity stays separate and unmapped.

| # | Early identity | Observed range | Projects | Same person as | Was an Editor then? | Answer |
|---|---|---|---:|---|---|---|
| B1 | (5, "Ahmed") | 2026-03-14 → 2026-05-04 | 46 | Ahmed, label 12? | yes / no | |
| B2 | (7, "Mans") | 2026-03-14 → 2026-05-06 | 35 | Mansour, label 14? | yes / no | |
| B3 | (9, "Michael") | 2026-03-14 → 2026-05-02 | 26 | Michael, label 13? | yes / no | |

## C. Already decided (D50) — no answer needed

`(11, "New")` and `(2, "Done")` are invalid identity values; `(1, "El Baz")` stays an unresolved historical identity.

## Record

Attested by: ______________________  Role: ______________________  Date: ____________
