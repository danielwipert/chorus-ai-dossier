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
**Output:** `VerificationReport` with pass/fail per summary + `contradiction_score` + `coverage_score`
**Model Role:** Model 5 — higher-quality model (compiler/verifier)

**Scoring Logic:**
- Each fact is classified as `aligned | absent | contradicted` against the summary
- **PRIMARY metric:** `contradiction_score = contradicted_facts / total_facts`
  - A summary **fails** if `contradiction_score > max_contradiction_score` (default `0.0` — zero tolerance)
  - This is the hallucination gate: a summary that contradicts any extracted fact fails
- **SECONDARY metric:** `coverage_score` recorded for audit trail only — does not gate pass/fail
  - A tight summary that skips facts but contradicts none is acceptable

**Pass/Retry Logic:**
- **PASS:** At least 2 summaries have `contradiction_score <= max_contradiction_score` → proceed to Stage 5
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

## Configuration (`configs/v1.json`)

```json
{
  "pipeline_version": "v1",
  "models": {
    "summarizer_a": "claude-haiku-4-5-20251001",
    "summarizer_b": "Qwen/Qwen2.5-72B-Instruct",
    "summarizer_c": "together:meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "fact_finder": "claude-haiku-4-5-20251001",
    "compiler": "together:deepseek-ai/DeepSeek-V3",
    "contextualizer_a": "Qwen/Qwen2.5-72B-Instruct"
  },
  "verification": {
    "pass_threshold": 0.5,
    "max_contradiction_score": 0.0,
    "max_retries": 2,
    "max_sample_facts": 40
  },
  "ingestion": {
    "min_chars_per_page": 50
  },
  "extraction": {
    "pages_per_chunk": 3
  },
  "output": {
    "include_audit_trail": true
  }
}
```

- `max_contradiction_score`: the primary verification gate. Default `0.0` = zero tolerance for contradictions. Can be relaxed slightly (e.g. `0.05`) if the verifier model is over-flagging borderline cases.
- `pass_threshold`: retained for backwards compatibility, not used in pass/fail logic.

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
# Install the package (editable mode)
pip install -e .

# Run the full pipeline on a PDF
chorus-ai path/to/document.pdf --config configs/v1.json

# Resume an existing run (replays only incomplete stages)
chorus-ai path/to/document.pdf --config configs/v1.json --resume

# Force re-run of already-completed stage outputs
chorus-ai path/to/document.pdf --config configs/v1.json --force
```

---

## Project File Structure

```
chorus-ai/
├── CLAUDE.md                        ← you are here
├── pyproject.toml                   ← package definition, entry point (chorus-ai CLI)
├── configs/
│   └── v1.json                      ← model assignments, thresholds, retry limits
└── src/chorus_ai/
    ├── cli.py                       ← main entry point (chorus-ai command)
    ├── core/
    │   ├── config.py                ← config loading
    │   ├── errors.py                ← StageFailure and other exceptions
    │   └── verification/
    │       └── verify_summary_v1.py ← contradiction scoring logic
    ├── llm/
    │   └── client.py                ← unified LLM API wrapper (Anthropic + Together)
    ├── runs/
    │   └── status.py                ← run state machine helpers
    ├── stages/
    │   ├── ingest.py                ← Stage 1
    │   ├── extract.py               ← Stage 2
    │   ├── summarize.py             ← Stage 3
    │   ├── verify.py                ← Stage 4
    │   ├── contextualize.py         ← Stage 5
    │   ├── compile.py               ← Stage 6
    │   ├── export.py                ← Stage 7
    │   ├── pdf_renderer.py          ← PDF rendering (ReportLab)
    │   └── prompts/                 ← one .txt per stage, not hardcoded in Python
    │       ├── extract_system.txt
    │       ├── summarize_system.txt
    │       ├── verify_system.txt
    │       ├── contextualize_system.txt
    │       └── compile_system.txt
    └── runs/                        ← auto-created, gitignored
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

- [x] Stage 1: Ingestion — pdfplumber extraction, text density validation, page/paragraph segmentation
- [x] Stage 2: Fact Extraction — LLM (haiku) with type classification, source locations, confidence scores
- [x] Stage 3: Summarization — three independent LLM summaries (A, B, C) with deterministic IDs
- [x] Stage 4: Verification + retry loop — structural check + LLM contradiction scoring (primary gate: `contradiction_score <= max_contradiction_score`, default 0.0), coverage recorded as secondary metric, regenerates failed summaries on retry
- [x] Stage 5: Contextual Analysis — two contextualizer models, non-fatal, notes gaps
- [x] Stage 6: Compilation — LLM synthesis with convergence scoring and section lineage
- [x] Stage 7: Finalization — all six required dossier sections + audit trail + PDF export (ReportLab, editorial monochrome design)
- [x] Orchestrator / state machine — CONTEXTUALIZED state added between VERIFIED and COMPILED
- [x] Run folder manager — 00_input/, 50_contextual/, 60_compilation/, 70_export/
- [x] Audit trail — embedded in final dossier (source hash, fact count, verification scores, model participation)
- [x] Config system — configs/v1.json with model assignments, thresholds, retry limits
- [x] CLI entry point — all 7 stages wired, resume semantics, non-fatal contextualize handling
- [x] LLM client — unified Anthropic wrapper, temperature=0, graceful non-Anthropic fallback
- [x] Prompt files — one .txt per stage in stages/prompts/, not hardcoded in Python

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
