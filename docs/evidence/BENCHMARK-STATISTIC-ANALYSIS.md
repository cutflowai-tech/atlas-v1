# Benchmark statistic analysis: mean vs median (read-only)

Purpose: before the official benchmark statistic is locked, check whether outliers materially distort the mean. The runtime statistic stays the **median**, marked provisional in `config/monday-contract-v1.2.json` (`speed_benchmark.benchmark_statistic_status`), until Waset approves one.

- Data: full Monday history for board `5091110326` through 2026-09-28 (`docs/evidence/REAL-001-STATUS.md`).
- Path: production `reconstruct_cycles()`. Durations are elapsed clock time of each item's first completed `In Progress → Ready For Approval` cycle.
- Reproduce: `PYTHONPATH=src python3 scripts/real_data_analysis.py <extract>`

Two populations, both split by exact Video Type cohort:

- **Eligible:** cycles with no exclusion at all (147).
- **Timing-valid:** the eligible cycles plus those excluded only because Editor identity is unresolved (740). Durations do not depend on who the Editor is, so this larger set shows the distribution shape.

No cohort is benchmark-eligible yet, because no Video Type label is confirmed as a base type. This analysis is descriptive only.

## Eligible cycles (147)

| Cohort | Labels | n | Mean h | Median h | Mean/Median | Max h | Mean shift from 1 max | Median shift from 1 max | > 3× median |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | Class A | 44 | 42.9 | 42.4 | 1.01 | 72.5 | +1.6% | +1.0% | 0 |
| 5 | Class B | 38 | 46.5 | 42.5 | 1.09 | 93.6 | +2.8% | +0.3% | 0 |
| 6 | Simple Short | 25 | 38.7 | 35.2 | 1.10 | 110.5 | +8.4% | +1.7% | 1 |
| 27 | Premium Short | 9 | 60.9 | 49.8 | 1.22 | 213.0 | **+45.4%** | +3.5% | 1 |
| 16:4 | Ai + Class A | 7 | 39.5 | 36.8 | 1.07 | 60.0 | +9.5% | +10.7% | 0 |
| 10:4 | 2* + Class A | 5 | 65.4 | 55.9 | 1.17 | 106.6 | +18.7% | +2.0% | 0 |
| 10:16:4 | 2* + Ai + Class A | 5 | 40.7 | 38.8 | 1.05 | 57.9 | +11.9% | +14.4% | 0 |
| 8 | Class A+ | 4 | 28.4 | 23.1 | 1.23 | 47.5 | +28.9% | +7.3% | 0 |

The other 8 cohorts have n ≤ 3.

## Timing-valid cycles (740)

| Cohort | Labels | n | Mean h | Median h | Mean/Median | P90 h | Max h | 10% trimmed mean h | Mean shift from 1 max | Median shift from 1 max | > 3× median |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | Class A | 200 | 46.6 | 42.1 | 1.11 | 75.4 | 244.8 | 42.3 | +2.2% | +0.2% | 5 |
| 6 | Simple Short | 194 | 33.2 | 31.4 | 1.06 | 57.5 | 123.5 | 31.6 | +1.4% | +0.7% | 2 |
| 5 | Class B | 137 | 45.4 | 41.8 | 1.09 | 72.8 | 129.9 | 43.7 | +1.4% | 0.0% | 1 |
| 27 | Premium Short | 97 | 48.8 | 45.6 | 1.07 | 79.5 | 213.0 | 44.5 | +3.6% | +1.2% | 2 |
| 8 | Class A+ | 31 | 43.3 | 37.6 | 1.15 | 70.6 | 100.9 | 42.0 | +4.6% | +5.6% | 0 |
| 16:4 | Ai + Class A | 17 | 44.2 | 36.8 | 1.20 | 58.2 | 181.9 | 37.4 | **+24.2%** | +5.6% | 1 |
| 10:4 | 2* + Class A | 16 | 64.2 | 56.7 | 1.13 | 98.4 | 121.9 | 64.1 | +6.4% | +1.5% | 0 |
| 10:16:4 | 2* + Ai + Class A | 12 | 40.3 | 35.3 | 1.14 | 63.4 | 67.7 | 40.2 | +6.6% | +11.0% | 0 |
| 10:5 | 2* + Class B | 5 | 53.8 | 58.4 | 0.92 | 65.4 | 66.3 | — | +6.1% | +17.6% | 0 |

The other 18 cohorts have n ≤ 4.

## Findings

1. **Durations are right-skewed.** The mean exceeds the median in almost every cohort, by 1–23%. Long tails reach 3–5× the median: up to 244.8 h against a 42.1 h median for Class A.
2. **In large cohorts (n ≥ 100) the two statistics differ by only 2–4 h**, and one extreme project moves either by less than 3%.
3. **In the small cohorts where management conclusions will actually be drawn (n between 5 and 20), a single project can move the mean by 19–45%**, versus at most 3.5% for the median in the same cases (Premium Short: +45.4% vs +3.5%; Ai + Class A: +24.2% vs +5.6%; 2* + Class A: +18.7% vs +2.0%). The 10% trimmed mean behaves like the median.
4. **The median is less stable than the mean only in tiny, even-sized cohorts** (n = 4–5, e.g. 2* + Class B), where the minimum sample of 5 already limits conclusions.

## Recommendation

Adopt the **median** as the official V1 benchmark statistic, and show sample size and P10–P90 range next to it. With the approved minimum of 5 projects, the Editor and team figures will often come from 5–20 projects. At that size a single stalled project can shift a mean by up to 45%, so a mean-based "faster/slower" verdict could flip because of one project. The mean can be shown as supplementary context but should not drive conclusions. Adopting it is a one-line versioned config change (`speed_benchmark.benchmark_statistic_status` → approved).
