# Atlas Reasoning V3 — Phase 07: Implement the LLM Analyst Reasoning Engine

## Document purpose
This file is an implementation specification for the code builder. Treat every MUST/MUST NOT statement as binding. Do not infer additional product behavior that is not written here.

## Global architectural rules
- The existing deterministic Atlas pipeline remains the source of truth.
- Monday data, cycle reconstruction, metrics, Interpretation 1.5, Intelligence V2, confidence, and evidence remain upstream and must not be weakened.
- LLM output MUST NOT become the source of truth for metrics, source events, actor attribution, sample sizes, deadlines, or evidence identity.
- PostgreSQL is the canonical store for Reasoning V3 application state.
- Honcho is contextual memory, not the canonical database.
- The UI may display LLM reasoning summaries, but MUST NOT expose raw hidden chain-of-thought.
- All new outputs MUST remain traceable to upstream deterministic evidence.
- Existing behavior MUST remain unchanged when Reasoning V3 is disabled.

## Objective
Convert one bounded new ReasoningCase into one structured ReasoningResult using GPT-5.6 Sol.

## Scope
New-case reasoning only. No update patching yet.

## Required implementation
1. Create a versioned analyst prompt.
2. Provide only bounded case evidence, supporting findings, contradicting findings, current context, and provenance.
3. Instruct the model not to invent numbers, people, projects, events, or metrics.
4. Require separation between observation, interpretation, alternative explanation, limitation, and hypothesis.
5. Require explicit counter-evidence handling.
6. Allow the model to produce management questions when business context is missing.
7. Prohibit HR, personality, psychological, salary, termination, and unsupported blame judgments.
8. Require strict ReasoningResult structured output.
9. Serialize equivalent inputs in a deterministic order.
10. Store prompt version and model metadata.
11. The UI/store MUST use the explicit reasoning summary, not hidden chain-of-thought.

## Required deliverables
Analyst prompt v1, analyst orchestrator, structured parser, prompt fixtures, and behavior documentation.

## Required tests
Valid mocked output, evidence-reference preservation, immutable case ID, missing-field failure, deterministic prompt structure, and prohibited-field checks.

## Acceptance criteria
Atlas can create one valid, evidence-linked new reasoning result from one bounded case.

## Explicit non-goals
No update patches. No Honcho. No executive synthesis. No raw chain-of-thought.

## Stop condition
Stop after the new-case path works end-to-end with mocked and controlled provider responses.
