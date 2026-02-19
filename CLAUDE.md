# CLAUDE.md — Chorus AI / Dossier V1

> This is the authoritative project context file. Read this before touching any code.
> All implementation decisions must trace back to the design contracts in this file.

---

## What This Project Is

**Chorus AI** is a closed-loop, multi-model document intelligence system.
**Dossier** is the first application built on it.

Dossier takes a PDF, runs it through a strict multi-stage pipeline, and produces a structured analytical report — think *New Yorker book review meets CIA intelligence dossier*: grounded, traceable, and deeply contextualized.

This is **not** a chatbot, agent, or general-purpose LLM wrapper.
It is a deterministic pipeline with strict contracts between stages.

---

## Core Design Rules (Non-Negotiable)

These govern every implementation decision. Do not deviate from them:

1. **Determinism** — Same input + same config = same output. No randomness, no surprises.
2. **Grounding First** — No summary, analysis, or narrative exists without being grounded in extracted facts.
3. **Fail-Closed** — Any broken stage gate halts the entire run. No silent degradation.
4. **Traceability** — Every output traces back to source spans in the original document.
5. **Separation of Concerns** — Facts, summaries, external context, and opinion are never mixed or co-mingled.
6. **Auditability** — Every decision is inspectable after the fact.
7. **No Agent Autonomy in V1** — No background retries, no self-directing behavior, no tool-calling loops.

---

## The 7-Stage Pipeline (Locked)

Each stage consumes explicit input artifacts, produces explicit output artifacts, and either succeeds or fails — nothing in between.

```
INIT → INGESTED → EXTRACTED → SUMMARIZED → VERIFIED → CONTEXTUALIZED → COMPILED → FINALIZED
```

State regression is not allowed. If a run fails, start a new run.

---

### Stage 1: Ingestion
**Input:** PDF file  
**Output:** `IngestionRecord` (normalized text + metadata)  
**Responsibilities:**
- Extract raw text from PDF (must have machine-readable text layer — image-only PDFs are rejected)
- Normalize formatting
- Segment into pages, sections, paragraphs
- Index page/paragraph positions
- Hash source file for immutability

**Hard Rule:** If the PDF fails text density validation → classify as INELIGIBLE, return diagnostics, halt. No partial processing.

---

### Stage 2: Extraction (Fact Finder)
**Input:** `IngestionRecord`  
**Output:** `FactList` (JSON array of atomic facts)  
**Model Role:** Model 4 — cheap, extractive-only model  
**Responsibilities:**
- Extract atomic, document-grounded facts only
- No paraphrasing beyond minimal normalization
- No interpretation or synthesis
- Every fact must reference a source location

**Fact Schema (immutable for V1):**
```json
{
  "fact_id": "F001",
  "claim": "Author argues that X",
  "type": "author_position | empirical_claim | definition | citation | conclusion",
  "source_location": { "page": 4, "paragraph": 2 },
  "confidence": 0.0
}
```

**Hard Rule:** The FactList is locked after this stage. Downstream stages cannot modify it.

---

### Stage 3: Summarization
**Input:** `IngestionRecord` (the document text)  
**Output:** `Summary_A`, `Summary_B`, `Summary_C` (three independent structured summaries)  
**Model Roles:** Models 1, 2, 3 — cheap, fast, from different vendors/architectures  
**Responsibilities:**
- Each model independently summarizes the document
- Focus on: core arguments, author claims, supporting evidence
- No external knowledge, no interpretation beyond the document, no speculative language

**Constraints:**
- Summaries are strictly document-grounded
- Models do NOT see each other's outputs at this stage

---

### Stage 4: Verification (Closed-Loop Core)
**Input:** `FactList` + `[Summary_A, Summary_B, Summary_C]`  
**Output:** `VerificationReport` with pass/fail per summary + `FactCoverageScore`  
**Model Role:** Model 5 — higher-quality model (compiler/verifier)  

**Scoring Logic:**
- Each summary scored against FactList for: coverage, absence of unsupported claims, alignment
- Score threshold for pass: `>= 0.75` (configurable in `config.yaml`)

**Pass/Retry Logic:**
- **PASS:** At least 2 summaries score >= threshold → proceed to Stage 5
- **RETRY:** Fewer than 2 pass → regenerate only the failed summaries, rerun verification
- **FAIL:** Max retries reached without 2 passing → emit diagnostic, halt run

**Hard Rule:** The FactList never changes during retry loops. Only summaries regenerate.

---

### Stage 5: Contextual Analysis
**Input:** Verified summaries (passing ones only)  
**Output:** `ContextualAnalysis_A`, `ContextualAnalysis_B`  
**Model Roles:** Models 6, 7 — contextualizer models  

**Allowed Context Lenses (whitelist):**
- Historical context
- Disciplinary / academic context
- Methodological context
- Comparative discourse (how this fits in broader debates)
- Critical perspectives

**Hard Rules:**
- External context appears ONLY in the dedicated "Contextual Analysis (External Sources)" section
- External context is FORBIDDEN in: fact extraction, summaries, key claims, verification inputs
- All external claims must be explicitly cited (academic textbooks, peer-reviewed journals, high-repute publications only)
- No speculation, prediction, extrapolation, or inference of intent
- Failure to produce contextual analysis is non-fatal — note the gap and continue

---

### Stage 6: Compilation
**Input:** Verified summaries + contextual analysis artifacts  
**Output:** `CompiledSummary` + section-level lineage mapping  
**Model Role:** Model 5 (reused) or a dedicated compilation model  

**Responsibilities:**
- Emphasize overlapping claims across summaries
- Discard unsupported or niche assertions
- Maintain strict alignment with FactList
- Record which source summaries contributed to each section

---

### Stage 7: Finalization (The Dossier)
**Input:** `CompiledSummary` + all upstream artifacts  
**Output:** `FinalDossier` (structured JSON + human-readable formats)  

**Required Dossier Sections:**
1. Executive Overview
2. Key Claims (fact-grounded, citing Fact IDs)
3. Compiled Summary
4. Contextual Analysis (clearly labeled as external)
5. Risks, Limitations, and Warnings
6. Audit Trail (fact references, summary lineage, model participation, confidence scores)

**Hard Rule:** All omissions, failures, or degraded sections must be explicitly labeled in the output.

---

## Artifact Contracts

Every stage passes typed JSON artifacts. No free-form text between stages.

| Artifact | Produced By | Consumed By |
|---|---|---|
| `IngestionRecord` | Stage 1 | Stages 2, 3 |
| `FactList` | Stage 2 | Stages 4, 6, 7 |
| `Summary_[A/B/C]` | Stage 3 | Stage 4 |
| `VerificationReport` | Stage 4 | Stages 5, 6 |
| `ContextualAnalysis_[A/B]` | Stage 5 | Stage 6 |
| `CompiledSummary` | Stage 6 | Stage 7 |
| `FinalDossier` | Stage 7 | Export |
| `AuditTrail` | All stages | Stage 7 + export |

All artifacts are:
- JSON-serializable
- Written to disk immediately upon creation
- Append-only (never mutated after creation)

---

## Run Folder Structure

Every run is isolated. No stage writes outside its folder.

```
runs/
 └── dossier_run_YYYYMMDD_HHMMSS_<hash>/
     ├── 00_input/           ← original PDF, unchanged
     ├── 01_ingestion/       ← IngestionRecord.json
     ├── 02_extraction/      ← FactList.json
     ├── 03_summarization/   ← Summary_A.json, Summary_B.json, Summary_C.json
     ├── 04_verification/    ← VerificationReport.json
     ├── 05_contextual/      ← ContextualAnalysis_A.json, ContextualAnalysis_B.json
     ├── 06_compilation/     ← CompiledSummary.json
     ├── 07_final/           ← FinalDossier.json, FinalDossier.pdf
     └── audit/              ← AuditTrail.json, run_manifest.json
```

---

## Tech Stack

- **Language:** Python 3.x
- **PDF parsing:** `pdfplumber` or `PyMuPDF (fitz)` — machine-readable PDFs only
- **LLM calls:** Anthropic API (primary), with support for other providers
- **Data format:** JSON for all artifacts
- **Config:** `config.yaml` for model assignments, thresholds, retry limits
- **Run tracking:** timestamp + source file hash as run ID

---

## Model Assignment Map (V1 Defaults)

| Role | Model Slot | Suggested Default | Purpose |
|---|---|---|---|
| Summarizer A | Model 1 | `claude-haiku-4-5` | Fast, cheap summarization |
| Summarizer B | Model 2 | `gemini-flash` or `qwen` | Different vendor/architecture |
| Summarizer C | Model 3 | `llama` or `mistral` | Third independent summary |
| Fact Finder | Model 4 | `claude-haiku-4-5` | Extractive only, no synthesis |
| Compiler/Verifier | Model 5 | `claude-sonnet-4-6` | Higher quality, verification |
| Contextualizer A | Model 6 | `claude-sonnet-4-6` | External context, cited |
| Contextualizer B | Model 7 | `gemini-pro` or second frontier | Second context perspective |

Model assignments are config-driven — swap models in `config.yaml` without touching pipeline code.

---

## Configuration (`config.yaml`)

```yaml
verification:
  pass_threshold: 0.75
  max_retries: 2

models:
  summarizer_a: "claude-haiku-4-5-20251001"
  summarizer_b: "gemini-1.5-flash"
  summarizer_c: "llama-3-8b"
  fact_finder: "claude-haiku-4-5-20251001"
  compiler: "claude-sonnet-4-6"
  contextualizer_a: "claude-sonnet-4-6"
  contextualizer_b: "gemini-1.5-pro"

output:
  formats: ["json", "pdf"]
  include_audit_trail: true
```

---

## Failure Behavior Reference

| Stage | Failure Type | Behavior |
|---|---|---|
| Ingestion | Image-only PDF | HALT — return diagnostics, no processing |
| Ingestion | Malformed PDF | HALT — return diagnostics |
| Verification | < 2 summaries pass | RETRY failed summaries (max `config.max_retries`) |
| Verification | Retries exhausted | HALT — return partial diagnostics only |
| Contextual Analysis | Models fail | NON-FATAL — note gap, continue to compilation |
| Any stage | Unexpected exception | HALT — write failure artifact, preserve all upstream outputs |

---

## What V1 Explicitly Does NOT Do

- No autonomous agents or self-directing behavior
- No parallel stage execution (sequential only)
- No online retrieval or web search during runs
- No human-in-the-loop editing (deferred to V2)
- No fine-tuning or memory layers
- No sentence-level traceability (section-level only in V1)
- No image-only or scanned PDF support

---

## How to Run (Commands)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full pipeline on a PDF
python run_dossier.py --input path/to/document.pdf

# Run a specific stage only (for debugging)
python run_dossier.py --input path/to/document.pdf --stage ingestion

# Resume a run from a specific stage (uses existing artifacts)
python run_dossier.py --resume runs/dossier_run_20250219_143022_abc123 --from-stage verification

# List all runs
python run_dossier.py --list-runs
```

---

## Project File Structure

```
chorus-ai/
├── CLAUDE.md                  ← you are here
├── config.yaml                ← model assignments, thresholds
├── requirements.txt
├── run_dossier.py             ← main entry point / orchestrator
├── pipeline/
│   ├── __init__.py
│   ├── orchestrator.py        ← state machine, stage routing
│   ├── stage_01_ingestion.py
│   ├── stage_02_extraction.py
│   ├── stage_03_summarization.py
│   ├── stage_04_verification.py
│   ├── stage_05_contextual.py
│   ├── stage_06_compilation.py
│   └── stage_07_finalization.py
├── models/
│   ├── __init__.py
│   └── model_client.py        ← unified LLM API wrapper
├── artifacts/
│   ├── __init__.py
│   └── schemas.py             ← Pydantic schemas for all artifact types
├── utils/
│   ├── run_manager.py         ← run folder creation, manifest writing
│   └── audit.py              ← audit trail management
└── runs/                      ← auto-created, gitignored
```

---

## Coding Standards

- Use **Pydantic** for all artifact schemas — never pass raw dicts between stages
- Every stage function signature: `def run_stage(inputs: StageInputArtifact, config: Config, run_dir: Path) -> StageOutputArtifact`
- Stages raise `StageFailure` exceptions — the orchestrator catches and handles
- Write artifacts to disk immediately after creation, before moving to the next stage
- Never mutate an artifact after it's written
- All LLM prompts live in separate `.txt` or `.md` files in `pipeline/prompts/` — not hardcoded in Python

---

## What's Already Built (Update This As Work Progresses)

- [ ] Stage 1: Ingestion
- [ ] Stage 2: Fact Extraction
- [ ] Stage 3: Summarization
- [ ] Stage 4: Verification + retry loop
- [ ] Stage 5: Contextual Analysis
- [ ] Stage 6: Compilation
- [ ] Stage 7: Finalization + PDF export
- [ ] Orchestrator / state machine
- [ ] Run folder manager
- [ ] Audit trail
- [ ] Config system
- [ ] CLI entry point

---

## V1 Success Criteria

Dossier V1 is complete when it:
1. Produces summaries measurably more accurate than a single frontier LLM
2. Reduces hallucinations through internal verification
3. Produces legible, grounded, and defensible analytical reports
4. Fails safely and visibly when confidence cannot be achieved
5. Every output traces to a source fact

---

*This document is the canonical project brain. If you're about to do something not covered here, stop and ask.*
