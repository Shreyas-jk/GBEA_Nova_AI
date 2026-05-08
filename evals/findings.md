# Eval findings — bugs and regressions surfaced by the harness

This file is a manual log. The runners do **not** auto-write here — when an eval
exposes a real product bug, it is recorded here for the maintainer to triage
rather than silently patched. Per the harness's "Do not change agent behavior
to pass evals" hard constraint, fixing these is a separate explicit decision.

---

## Finding 001 — Vector store silently degrades to 0 embeddings (CRITICAL)

**Discovered:** 2026-05-07 by the first run of `evals/runners/run_retrieval_evals`.

**Symptom:** `python -m evals.runners.run_retrieval_evals` reports
`P@1 = P@3 = P@5 = R@5 = MRR = Hit@5 = 0.00` across all 30 queries. Inspecting
the per-query output shows `retrieved: []` for every query.

**Root cause:** `tools/embeddings.py:18` references
`amazon.nova-embed-multimodal-v1:0`, which is not a valid Bedrock model ID.
Every chunk-embedding call in `tools/vector_store.initialize()` raises
`ValidationException: The provided model identifier is invalid.` The function
catches per-chunk exceptions and continues, so the store ends up with 0
embeddings — initialized successfully but completely empty.

`bedrock.list_foundation_models()` for this account shows the actual Nova
multimodal embedding model ID is **`amazon.nova-2-multimodal-embeddings-v1:0`**
(note: `nova-2` prefix, plural `embeddings`).

**Production impact:** `tools/benefits_kb.search_benefits_kb` falls back to
keyword search whenever semantic retrieval returns no hits — see
`tools/benefits_kb.py:140-145`. The keyword fallback is reasonable but loses
the semantic-meaning advantage that motivated the Nova embedding integration
in the first place. Users who phrase queries in a way that doesn't share
keywords with program names ("help buying groceries" → SNAP, "I can't pay
my power bill" → LIHEAP) get worse hits, and the agent's ability to surface
relevant context is degraded.

**Why the harness caught it but production didn't:** The keyword fallback
masks the failure in the chat UX. There is no log alert when zero embeddings
are loaded, only a per-chunk `WARNING` that scrolls past on startup. The
retrieval evals make the failure quantitative and obvious.

**Recommended fix (one line):** in `tools/embeddings.py`,
`EMBED_MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"`. After fixing,
re-run `python -m evals.runners.run_retrieval_evals` and update the baseline
in `evals/README.md`.

**Recommended secondary hardening:** in `tools/vector_store.initialize()`,
raise instead of warning if zero chunks were embedded. Silently initializing
an empty vector store is the kind of failure mode that cost us a real signal
here.

**Status:** open. Not patched by the eval harness work.

---

## Finding 002 — `intake_interview` and `analyze_document` rebuild a sub-agent on every call

**Discovered:** during Step 1 codebase review.

**Symptom (suspected, not measured):** `tools/intake.py:_get_intake_model()`
and `tools/document_reader.py:_analyze_text_with_agent` instantiate a fresh
`BedrockModel` and `Agent` every invocation. Across a multi-turn conversation
this means each user turn that touches intake creates a new model client and
a new agent object. Probably small per-call overhead but adds up across the
eval suite (and across real chat sessions).

**Production impact:** unknown but probably observable as added latency on
multi-turn conversations.

**Recommended fix:** lazy-instantiate the sub-agent at module level (mirror
how the orchestrator is built once in `web/server.py`).

**Status:** open. Not blocking. Worth measuring with a real benchmark before
investing in the refactor.

---

## Finding 003 — Orchestrator does not call `check_eligibility` on canonical intake (HIGH)

**Discovered:** 2026-05-07, smoke conversation eval baseline (`conv_006`).

**Symptom:** In the canonical multi-turn case (single mom, 2 kids, $28k, CA),
the user explicitly says "Can you check what I might qualify for?" The agent
responds with a list that includes Medi-Cal, CalFresh, WIC, EITC, etc. — but
inspection of `agent.messages` shows it called `intake_interview` only.
`check_eligibility` was never invoked.

```
tools_called: ['intake_interview']
eligibility_check: {'passed': False, 'detail': 'Agent never produced an
eligibility result via check_eligibility'}
```

**Production impact:** The entire purpose of the deterministic rules engine
(`tools/rules_engine.py`, 28 covered cases) is to ground eligibility claims
in pure Python logic. When the agent skips that tool and synthesizes program
lists from training data + RAG context, every claim is ungrounded. The user
gets a plausible-looking list with no provable derivation from the rules engine,
and the rules engine itself becomes silently dead code.

**Recommended investigation:** Add stronger system-prompt nudges or an explicit
post-intake step that calls `check_eligibility` with the accumulated profile
before generating any eligibility text. Possibly wrap the orchestrator in a
schema-validator that rejects responses citing programs without a corresponding
`check_eligibility` toolUse in the same turn.

**Status:** open.

---

## Finding 004 — `intake_interview` drops fields the user clearly stated (HIGH)

**Discovered:** 2026-05-07, smoke conversation eval baseline (`conv_006`).

**Symptom:** The user said: "I live in California with my 2 kids, ages 3 and
7." The intake sub-agent should infer `household_size = 3` (1 adult + 2 kids)
and `children_ages = [3, 7]`. Instead the extracted profile contains:

```
profile_check: {'passed': False, 'detail': 'household_size: expected 3, got None'}
```

**Hypothesis (not verified):** The sub-agent may be invoked multiple times
across turns and the merge step may not be additive — only the latest tool
result is captured by the WebSocket extractor (`web/server.py:_extract_tool_results`
returns "the most recent" tool result). If the agent calls `intake_interview`
on the final turn with only the final user message and an outdated
`current_profile`, prior fields could get clobbered. Worth tracing.

**Production impact:** Without `household_size`, the rules engine cannot
compute FPL thresholds. Every income-based program would be evaluated as
"unknown" / low-confidence — wrong answers and lost eligibility surfacing.

**Recommended investigation:** Trace `agent.messages` across all turns of
`conv_006`. Check whether each `intake_interview` call passed the latest
accumulated profile in `current_profile`. If not, the orchestrator needs
to thread state through each call (or the extractor needs to merge instead
of replace).

**Status:** open.

---

## Finding 005 — Bedrock Anthropic use-case form not submitted (operator setup, not a bug)

**Discovered:** 2026-05-07, first smoke conversation run with the LLM judge.

**Symptom:** Judge calls to `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
fail with `ResourceNotFoundException: Model use case details have not been
submitted for this account. Fill out the Anthropic use case details form
before using the model.`

**Action required:** AWS Bedrock console → Model access → complete the
Anthropic use-case form for this account, wait for approval, retry.

**Why this is in findings:** The harness now correctly raises `JudgeAccessError`
for both `AccessDenied` and the use-case-form variant of
`ResourceNotFoundException`. Until the form is approved, the conversation
runner can be invoked with `--cost-cap 0` to baseline deterministic checks
only. **Do not** swap the judge to a Nova model to work around this — see
the cross-family-judging methodology section in `evals/README.md`.

**Status:** blocked on operator action.
