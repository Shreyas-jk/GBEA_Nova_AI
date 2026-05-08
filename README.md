# BenefitsNavigator

**Live demo:** https://gbea-nova-ai.onrender.com

An agentic AI system that helps US citizens and residents discover government benefits they may be eligible for. Built on **AWS Bedrock** using **two Amazon Nova models** and the **Strands Agents SDK**:

- **Amazon Nova 2 Lite** — reasoning, conversation, tool use, and multimodal document analysis
- **Amazon Nova Multimodal Embedding** — semantic search over the benefits knowledge base (RAG)

## The Problem

Millions of Americans are eligible for government benefits but don't know it, or find the application process too confusing. BenefitsNavigator bridges that gap by conducting a friendly interview, matching users against 15+ benefit programs using a deterministic rules engine, and generating a personalized action plan.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Browser (Web UI)                               │
│  ┌──────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │      Chat Pane (WebSocket)   │  │      Benefits Panel (live)      │  │
│  │  - Message bubbles           │  │  - Eligible program cards       │  │
│  │  - Document upload           │  │  - Color-coded categories       │  │
│  │  - Typing indicator          │  │  - Confidence badges            │  │
│  │  - Drag & drop files         │  │  - Generate Action Plan button  │  │
│  └──────────────────────────────┘  └─────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │ WebSocket + REST
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Server (web/server.py)                       │
│         GET /  |  POST /upload  |  WebSocket /ws/chat                   │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                 Orchestrator Agent (Nova 2 Lite)                        │
│              Routes conversations to sub-agent tools                    │
│                                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │   Intake     │ │  Eligibility │ │  Action Plan │ │  Document    │    │
│  │   Interview  │ │  Checker     │ │  w/ Cross-   │ │  Analyzer    │    │
│  │ (sub-agent)  │ │(rules engine)│ │  Program Opt │ │ (multimodal) │    │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
│  ┌──────────────┐ ┌──────────────┐                                      │
│  │  Benefits KB │ │  Proactive   │                                      │
│  │  (semantic)  │ │  Follow-Up   │                                      │
│  └──────┬───────┘ └──────────────┘                                      │
└─────────┼───────────────────────────────────────────────────────────────┘
          │                       │
          ▼                       ▼
┌─────────────────────┐ ┌────────────────────────────────────────────────┐
│  Nova Embed (RAG)   │ │           Nova 2 Lite (Reasoning)              │
│  Semantic search    │ │  Conversation, tool use, document analysis     │
│  amazon.nova-embed  │ │  global.amazon.nova-2-lite-v1:0                │
│  -multimodal-v1:0   │ │                                                │
└─────────────────────┘ └────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Amazon Bedrock                                  │
│  Nova 2 Lite: reasoning, conversation, tool use, document analysis      │
│  Nova Multimodal Embedding: semantic search over benefits KB (RAG)      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Multi-Agent Pattern (Strands "agents-as-tools")

1. **Orchestrator Agent** — Main conversational agent. Routes user messages to the appropriate sub-agent tool based on the conversation state.
2. **Intake Agent** (tool) — Conducts a conversational interview to build a structured citizen profile (household size, income, state, children, etc.).
3. **Eligibility Agent** (tool) — Takes the citizen profile and runs it through a **deterministic Python rules engine** against 15+ federal and state benefit programs. No LLM calls for the actual eligibility math.
4. **Action Plan Agent** (tool) — Generates a personalized, prioritized step-by-step plan with application links, required documents, and deadlines.
5. **Document Analyzer** (tool) — Extracts eligibility-relevant information from uploaded documents (pay stubs, tax returns, lease agreements, utility bills) using PDF text extraction and Nova 2 Lite multimodal image analysis.
6. **Benefits KB Search** (tool) — Keyword search over the local program knowledge base for general questions about benefit programs.

## Web UI

The web interface features a split-pane layout:

- **Left pane (Chat)** — Conversational interface with the BenefitsNavigator agent. Supports markdown rendering, file upload via button/paste/drag-and-drop, and a typing indicator.
- **Right pane (Benefits Panel)** — Live-updating cards for each evaluated program, color-coded by category with confidence badges (Likely eligible / May qualify / Not eligible). Includes a "Generate Action Plan" button.

The UI supports dark mode (via `prefers-color-scheme`) and is responsive on mobile, where the benefits panel becomes a slide-out drawer.

### Document Upload

Upload pay stubs, tax returns, lease agreements, or utility bills (PDF, PNG, JPG) and the agent will automatically extract relevant information to update your profile. Supported methods:

- Click the paperclip button
- Drag and drop files onto the chat area
- Paste from clipboard

## Project Structure

```
benefits-agent/
├── main.py                    # Terminal mode: orchestrator agent + Rich chat loop
├── config.py                  # AWS config, model settings, FPL tables, system prompts
├── requirements.txt           # Core dependencies
├── run.sh                     # One-command launcher for the web UI
├── tools/
│   ├── __init__.py            # Export all tools
│   ├── intake.py              # @tool: intake_interview — gathers citizen profile
│   ├── eligibility.py         # @tool: check_eligibility — matches profile to programs
│   ├── action_plan.py         # @tool: create_action_plan — generates step-by-step plan
│   ├── benefits_kb.py         # @tool: search_benefits_kb — searches program knowledge base
│   ├── document_reader.py     # @tool: analyze_document — extracts info from uploaded docs
│   └── rules_engine.py        # Pure Python: deterministic eligibility rules
├── data/
│   ├── federal_programs.json  # 12 federal programs with eligibility rules
│   └── state_programs.json    # State-specific programs (California)
├── web/
│   ├── server.py              # FastAPI server with WebSocket chat endpoint
│   ├── requirements.txt       # Web-specific dependencies
│   └── static/
│       ├── index.html         # Split-pane web UI
│       ├── styles.css         # Styling with dark mode support
│       └── app.js             # Frontend state management and WebSocket client
├── tests/
│   ├── test_eligibility.py    # Pytest tests for the rules engine (28 tests)
│   └── test_eval_harness.py   # Pytest tests for the eval harness itself (70 tests)
├── evals/                     # Eval harness — see evals/README.md
│   ├── golden/                # 30 conversation cases + 30 retrieval queries
│   ├── judges/                # LLM-as-judge (Claude Sonnet, cross-family)
│   ├── metrics/               # P@k / MRR / safety regex checks
│   ├── runners/               # CLI: run_conversation_evals / run_retrieval_evals / run_all
│   ├── reports/               # latest.md (overwritten) + history.jsonl (append-only)
│   └── findings.md            # Bugs surfaced by the harness, manual triage log
├── .github/workflows/
│   └── evals.yml              # PR smoke run + nightly full run + regression issue
└── README.md
```

## Supported Programs

### Federal Programs (12)

| Program            | Category   | Income Limit |
| ------------------ | ---------- | ------------ |
| SNAP (Food Stamps) | Food       | 130% FPL     |
| Medicaid           | Healthcare | 138% FPL     |
| CHIP               | Healthcare | 200% FPL     |
| WIC                | Food       | 185% FPL     |
| LIHEAP             | Utilities  | 150% FPL     |
| Section 8          | Housing    | 50% AMI      |
| EITC               | Tax Credit | Varies       |
| Child Tax Credit   | Tax Credit | $200k/$400k  |
| Pell Grant         | Education  | ~$60k        |
| TANF               | Cash       | 100% FPL     |
| SSI                | Cash       | ~$11,316     |
| Lifeline           | Utilities  | 135% FPL     |

### California State Programs (5)

| Program  | Category   | Notes                                          |
| -------- | ---------- | ---------------------------------------------- |
| CalFresh | Food       | 200% FPL (broad-based)                         |
| Medi-Cal | Healthcare | All income-eligible, regardless of immigration |
| CalWORKs | Cash       | State TANF variant                             |
| CARE     | Utilities  | 30-35% energy bill discount                    |
| CAPI     | Cash       | For non-citizens ineligible for SSI            |

## Configuration

| Environment Variable | Default                          | Description                                   |
| -------------------- | -------------------------------- | --------------------------------------------- |
| `AWS_REGION`         | `us-east-1`                      | AWS region for Bedrock                        |
| `MODEL_ID`           | `global.amazon.nova-2-lite-v1:0` | Bedrock model ID                              |
| `THINKING_EFFORT`    | `medium`                         | Nova 2 Lite thinking effort (low/medium/high) |

## Running Tests

```bash
cd benefits-agent
pytest tests/ -v
```

## Evaluation

The deterministic rules engine is covered by `tests/test_eligibility.py`
(28 cases). Beyond that, an **LLM eval harness** in `evals/` grades the
agent's actual conversational behavior, retrieval quality, and safety
guardrails — the things unit tests can't see.

Three layers:

1. **Deterministic checks** — regex over agent responses for forbidden
   requests (SSN/bank/password), hedged language ("you may qualify" vs
   "you qualify"), crisis-resource presence (988, 211, DV hotline),
   eligible-program set membership.
2. **LLM-as-judge** — **Claude Sonnet on Bedrock** scores each response
   on five dimensions (accuracy / safety / helpfulness / tone / grounding,
   1–5 each). Cross-family judging is deliberate: a same-family judge
   shares training-data blind spots with the agent and silently weakens
   the eval signal. See `evals/README.md#methodology` for the full
   rationale.
3. **Retrieval evals** — P@1 / P@3 / P@5 / R@5 / MRR over 30 hand-labeled
   queries with stable semantic chunk IDs against the 51-chunk KB.

Run it:

```bash
python -m evals.runners.run_all                  # full suite + report
python -m evals.runners.run_all --subset smoke   # ~6 cases, ~30s — what CI uses
python -m evals.runners.run_all --cost-cap 0     # deterministic-only, no Bedrock judge
```

Output lands in `evals/reports/latest.md` (overwritten per run) and
`evals/reports/history.jsonl` (append-only trend log). The
`.github/workflows/evals.yml` GitHub Actions workflow runs the smoke
subset on every PR and the full suite nightly, opening a regression
issue if pass rate drops ≥10pp from the previous run.

The harness's first baseline run surfaced three real product bugs in
`evals/findings.md` — including an invalid embedding model ID that was
silently degrading semantic search to zero hits in production. That's
the harness doing its job.

## Extending

### Adding a new federal program

1. Add the program definition to `data/federal_programs.json`
2. Optionally add a custom checker in `tools/rules_engine.py` (register it in `_PROGRAM_CHECKERS`)
3. The generic checker handles most FPL-based programs automatically

### Adding a new state

1. Add state programs to `data/state_programs.json` under the 2-letter state code
2. Add custom checkers in `tools/rules_engine.py` if needed
3. State programs are automatically loaded when the user's profile includes that state

## Safety & Ethics

These behaviors are continuously verified by the eval harness's
deterministic safety checks (`evals/metrics/safety.py`) and the
safety dimension of the LLM judge (`evals/judges/rubric.py`). Six
safety-critical conversation cases in `evals/golden/conversations.json`
exercise the high-risk paths.

- Never asks for SSN, bank accounts, or passwords
- Always says "you may qualify", never "you qualify"
- Prioritizes crisis resources (988, 211, DV hotline 1-800-799-7233) for suicidal ideation, domestic violence, homelessness
- Refuses prompt injections and redirects minors to a trusted adult
- Includes disclaimers that assessments are informational only
- Uses warm, non-judgmental language throughout

## Tech Stack

- **Reasoning Model**: Amazon Nova 2 Lite via AWS Bedrock — conversation, tool use, document analysis
- **Embedding Model**: Amazon Nova Multimodal Embedding via AWS Bedrock — semantic search (RAG)
- **Agent Framework**: Strands Agents SDK
- **Language**: Python 3.10+
- **Web**: FastAPI + WebSocket + vanilla HTML/CSS/JS
- **Document Processing**: pdfplumber (PDF), Nova 2 Lite multimodal (images)
- **Vector Store**: In-memory (plain Python, no external DB)
- **Terminal UI**: Rich library
- **Testing**: pytest (rules engine + harness self-tests)
- **Eval Harness**: deterministic safety regex + Claude Sonnet judge (cross-family) + retrieval P@k/MRR — runs in GitHub Actions on every PR and nightly
