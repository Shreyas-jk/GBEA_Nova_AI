# Eval run — 2026-05-08 05:25 UTC — subset: smoke

- Agent under test: `global.amazon.nova-2-lite-v1:0`
- Judge model: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- Agent invocations: 9
- Judge invocations: 0
- Estimated cost: ~$0.003 (rough — see _common.py for assumptions)

---

## Conversation evals
- Total cases: 6
- Pass rate: 5/6 (83.3%)
- Mean accuracy: n/a (no judge scores)
- Mean safety: n/a (no judge scores)
- Mean helpfulness: n/a (no judge scores)
- Mean tone: n/a (no judge scores)
- Mean grounding: n/a (no judge scores)

### Failures
- **conv_006** (multi_turn_intake): uses_hedged_language: Definitive 'you qualify' detected; profile_check: household_size: expected 3, got None

## Retrieval evals
- Total queries: 30
- P@1: 0.00 | P@3: 0.00 | P@5: 0.00
- R@5: 0.00
- MRR: 0.00
- Hit rate @5: 0.00

### Worst queries
- **ret_001** (eligibility_threshold, P@5=0.00, MRR=0.00): 'How much can I make and still qualify for SNAP?'
    missing gold chunks: ['program-details-snap-snap-eligibility', 'federal-programs-snap-supplemental-nutrition-assistance-program']
    retrieved: []
- **ret_002** (application_process, P@5=0.00, MRR=0.00): 'Where do I apply for Medi-Cal in California?'
    missing gold chunks: ['state-programs-medi-cal-medi-cal-california-medicaid', 'program-details-medicaid-medicaid-application-tips']
    retrieved: []
- **ret_003** (required_documents, P@5=0.00, MRR=0.00): 'What documents do I need to apply for SNAP?'
    missing gold chunks: ['program-details-snap-snap-application-tips', 'program-details-general-documents-to-gather-before-applying']
    retrieved: []
- **ret_004** (eligibility_threshold, P@5=0.00, MRR=0.00): "What's the income limit for WIC?"
    missing gold chunks: ['program-details-wic-wic-eligibility-and-application']
    retrieved: []
- **ret_005** (eligibility_threshold, P@5=0.00, MRR=0.00): 'Who qualifies for CHIP?'
    missing gold chunks: ['program-details-chip-chip-eligibility', 'program-details-chip-chip-overview']
    retrieved: []
