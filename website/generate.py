"""
Build script: renders Jinja2 templates → docs/index.html
Usage: python website/generate.py
"""

import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# ── Paths ─────────────────────────────────────────────────

ROOT      = Path(__file__).parent.parent
TMPL_DIR  = Path(__file__).parent / "templates"
STATIC_SRC = Path(__file__).parent / "static"
DOCS_DIR  = ROOT / "docs"
STATIC_DST = DOCS_DIR / "static"

# ── Site data ─────────────────────────────────────────────

DATA = {
    "page_title":       "Chorus AI — Dossier V1",
    "meta_description": "A closed-loop, multi-model document intelligence pipeline. "
                        "Extract facts, generate independent summaries, verify against "
                        "a locked fact list, and produce a grounded analytical dossier.",
    "github_url":       "https://github.com/danielwipert/chorusai",

    "nav_links": [
        {"label": "What it is",     "anchor": "what"},
        {"label": "Principles",     "anchor": "principles"},
        {"label": "Pipeline",       "anchor": "pipeline"},
        {"label": "Verification",   "anchor": "verification"},
        {"label": "Architecture",   "anchor": "architecture"},
        {"label": "Stack",          "anchor": "stack"},
    ],

    # ── Hero ────────────────────────────────────────────────
    "hero": {
        "tag":      "Open Source Project · Dossier V1",
        "title":    "Multi-model document<br><em>intelligence</em>, grounded in fact.",
        "subtitle": "Chorus AI is a closed-loop pipeline that extracts atomic facts from a "
                    "PDF, generates three independent summaries across different model "
                    "architectures, then verifies every summary against a locked fact list "
                    "before producing a traceable analytical dossier.",
    },

    "stats": [
        {"value": "7",       "label": "Pipeline stages"},
        {"value": "3×",      "label": "Independent summaries"},
        {"value": "0.0",     "label": "Default contradiction tolerance"},
        {"value": "100%",    "label": "Outputs trace to source facts"},
    ],

    # ── What It Is ──────────────────────────────────────────
    "what": {
        "title": "What is Chorus AI?",
        "intro": "Chorus AI is not a chatbot, agent, or general-purpose LLM wrapper. "
                 "It is a deterministic document intelligence pipeline with strict "
                 "contracts between stages — designed to produce analytical reports "
                 "that are grounded, verifiable, and auditable.",
        "cells": [
            {
                "label":   "The problem",
                "heading": "LLMs hallucinate. Single-model outputs are unverified.",
                "body":    "A single frontier model summarising a complex document will "
                           "confidently assert things not in the source. There is no "
                           "internal check, no cross-validation, no audit trail.",
            },
            {
                "label":   "The solution",
                "heading": "Three summaries, one fact list, a closed verification loop.",
                "body":    "Chorus extracts atomic facts first, then generates summaries "
                           "independently across multiple model families. Each summary is "
                           "verified against the locked fact list — any contradiction fails "
                           "the summary and triggers a regeneration.",
            },
            {
                "label":   "The output",
                "heading": "A structured dossier with a full audit trail.",
                "body":    "The final dossier contains an executive overview, key claims "
                           "with fact IDs, compiled synthesis, external context, risks, "
                           "and a complete audit trail — every claim traces to a source span.",
            },
            {
                "label":   "Design philosophy",
                "heading": "Think CIA intelligence brief meets New Yorker book review.",
                "body":    "Grounded facts. Traceable claims. Explicitly labeled uncertainty. "
                           "No speculation passed off as analysis. If confidence cannot be "
                           "achieved, the pipeline halts visibly — not silently.",
            },
        ],
        "callout": "<strong>Hard guarantee:</strong> The FactList is locked after extraction. "
                   "No downstream stage can modify it. Summaries and analysis must conform to "
                   "the facts — not the other way around.",
    },

    # ── Design Principles ───────────────────────────────────
    "principles": {
        "title": "Seven non-negotiable design rules.",
        "intro":  "These govern every implementation decision. They are constraints, "
                  "not guidelines — a stage that violates them is wrong by definition.",
        "cards": [
            {
                "name": "Determinism",
                "desc": "Same input + same config = same output. Temperature is zero "
                        "across all models. No random seeds, no non-deterministic branches.",
            },
            {
                "name": "Grounding First",
                "desc": "No summary, analysis, or narrative exists without being grounded "
                        "in extracted facts. External context is allowed exactly one "
                        "designated section.",
            },
            {
                "name": "Fail-Closed",
                "desc": "Any broken stage gate halts the entire run. There is no silent "
                        "degradation. A partial dossier is not a dossier.",
            },
            {
                "name": "Traceability",
                "desc": "Every output traces back to source spans in the original document. "
                        "Every key claim references a Fact ID.",
            },
            {
                "name": "Separation of Concerns",
                "desc": "Facts, summaries, external context, and opinion are never mixed. "
                        "Each lives in an explicitly typed artifact that cannot be mutated "
                        "after creation.",
            },
            {
                "name": "Auditability",
                "desc": "Every decision is inspectable after the fact. The audit trail "
                        "records model participation, contradiction scores, coverage scores, "
                        "and which summaries contributed to each section.",
            },
            {
                "name": "No Agent Autonomy",
                "desc": "No background retries beyond configured limits, no self-directing "
                        "behavior, no tool-calling loops. V1 is a pipeline, not an agent.",
            },
        ],
    },

    # ── Pipeline ────────────────────────────────────────────
    "pipeline": {
        "title": "The seven-stage pipeline.",
        "intro":  "Each stage consumes explicit input artifacts, produces explicit output "
                  "artifacts, and either succeeds or fails — nothing in between. "
                  "State regression is not allowed.",
        "stages": [
            {
                "num":       1,
                "state":     "→ INGESTED",
                "name":      "Ingestion",
                "desc":      "Extracts raw text from the PDF, normalises formatting, "
                             "segments into pages and paragraphs, indexes positions, "
                             "and hashes the source file for immutability.",
                "input":     "PDF file",
                "output":    "IngestionRecord",
                "model":     None,
                "hard_rule": "Image-only PDFs are rejected immediately. No partial processing.",
            },
            {
                "num":       2,
                "state":     "→ EXTRACTED",
                "name":      "Extraction (Fact Finder)",
                "desc":      "Uses a cheap extractive model to pull atomic, document-grounded "
                             "facts. No paraphrasing, no interpretation, no synthesis. Every "
                             "fact references a source page and paragraph.",
                "input":     "IngestionRecord",
                "output":    "FactList",
                "model":     "Model 4 — cheap, extractive-only",
                "hard_rule": "FactList is locked after this stage. No downstream stage may modify it.",
            },
            {
                "num":       3,
                "state":     "→ SUMMARIZED",
                "name":      "Summarization",
                "desc":      "Three independent models from different vendors and architectures "
                             "each summarise the document. They do not see each other's outputs. "
                             "Diversity of architecture reduces correlated failure modes.",
                "input":     "IngestionRecord",
                "output":    "Summary_A, Summary_B, Summary_C",
                "model":     "Models 1, 2, 3 — different vendors / architectures",
                "hard_rule": None,
            },
            {
                "num":       4,
                "state":     "→ VERIFIED",
                "name":      "Verification",
                "desc":      "Each summary is scored against every fact in the FactList. "
                             "The primary metric is contradiction_score. Failed summaries "
                             "are regenerated; the FactList never changes.",
                "input":     "FactList + [Summary_A, Summary_B, Summary_C]",
                "output":    "VerificationReport",
                "model":     "Model 5 — higher-quality verifier",
                "hard_rule": "< 2 summaries passing after max retries → halt run.",
            },
            {
                "num":       5,
                "state":     "→ CONTEXTUALIZED",
                "name":      "Contextual Analysis",
                "desc":      "Two contextualizer models enrich the verified summaries with "
                             "historical, disciplinary, methodological, and comparative context. "
                             "All external claims must be explicitly cited.",
                "input":     "Verified summaries",
                "output":    "ContextualAnalysis_A, ContextualAnalysis_B",
                "model":     "Models 6, 7 — contextualizer models",
                "hard_rule": "Non-fatal: failure noted and run continues to compilation.",
            },
            {
                "num":       6,
                "state":     "→ COMPILED",
                "name":      "Compilation",
                "desc":      "Synthesises the verified summaries into a single compiled "
                             "summary. Overlapping claims are emphasised; unsupported or "
                             "niche assertions are discarded. Section lineage is recorded.",
                "input":     "Verified summaries + ContextualAnalysis artifacts",
                "output":    "CompiledSummary",
                "model":     "Model 5 (reused)",
                "hard_rule": None,
            },
            {
                "num":       7,
                "state":     "→ FINALIZED",
                "name":      "Finalization",
                "desc":      "Assembles the full dossier: executive overview, key claims "
                             "with fact IDs, compiled summary, contextual analysis, risks "
                             "and limitations, and a complete audit trail. Exported as "
                             "structured JSON and a typeset PDF.",
                "input":     "CompiledSummary + all upstream artifacts",
                "output":    "FinalDossier (JSON + PDF)",
                "model":     None,
                "hard_rule": "All omissions and degraded sections must be explicitly labeled in output.",
            },
        ],
    },

    # ── Verification ────────────────────────────────────────
    "verification": {
        "title":  "The closed-loop verification core.",
        "intro":   "Stage 4 is the hallucination gate. It is the reason three summaries "
                   "are generated rather than one. A summary that contradicts any extracted "
                   "fact fails — regardless of how plausible it sounds.",
        "flow_nodes": [
            {"label": "FactList",        "sub": "locked after Stage 2",  "highlight": False},
            {"label": "Summary A/B/C",   "sub": "3 independent models",  "highlight": False},
            {"label": "Verifier",        "sub": "Model 5",               "highlight": True},
            {"label": "Scores each fact","sub": "aligned / absent / contradicted", "highlight": False},
            {"label": "Pass / Retry",    "sub": "per summary",           "highlight": False},
        ],
        "rules": [
            {
                "status_class": "pass",
                "status_label": "PASS",
                "desc": "≥ 2 summaries have contradiction_score ≤ threshold "
                        "(default 0.0). Run proceeds to Stage 5.",
            },
            {
                "status_class": "retry",
                "status_label": "RETRY",
                "desc": "Fewer than 2 summaries pass. Failed summaries are regenerated "
                        "and re-verified. FactList is unchanged.",
            },
            {
                "status_class": "fail",
                "status_label": "HALT",
                "desc": "Max retries reached without 2 passing. Run halts. "
                        "Diagnostic artifact written. All upstream outputs preserved.",
            },
        ],
        "callout": "<strong>Primary metric:</strong> <code>contradiction_score = contradicted_facts / total_facts</code>. "
                   "Coverage (how many facts the summary mentions) is recorded as a secondary metric for the "
                   "audit trail — but a tight summary that skips facts without contradicting them is acceptable. "
                   "Only contradictions are disqualifying.",
    },

    # ── Architecture ────────────────────────────────────────
    "architecture": {
        "title": "Architecture and artifact contracts.",
        "intro":  "Every stage passes typed JSON artifacts. No free-form text between "
                  "stages. Artifacts are written to disk immediately upon creation and "
                  "are never mutated after that.",
        "model_table": {
            "columns": ["Role", "Slot", "Default model", "Purpose"],
            "rows": [
                {"role": "Summarizer A",     "slot": "Model 1", "model": "claude-haiku-4-5-20251001",              "purpose": "Fast, cheap summarization"},
                {"role": "Summarizer B",     "slot": "Model 2", "model": "Qwen/Qwen2.5-72B-Instruct",             "purpose": "Different vendor / architecture"},
                {"role": "Summarizer C",     "slot": "Model 3", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo","purpose": "Third independent summary"},
                {"role": "Fact Finder",      "slot": "Model 4", "model": "claude-haiku-4-5-20251001",              "purpose": "Extractive only, no synthesis"},
                {"role": "Compiler/Verifier","slot": "Model 5", "model": "deepseek-ai/DeepSeek-V3",               "purpose": "Higher quality, verification & compilation"},
                {"role": "Contextualizer A", "slot": "Model 6", "model": "Qwen/Qwen2.5-72B-Instruct",             "purpose": "External context, cited"},
            ],
        },
        "artifacts": [
            {"name": "IngestionRecord",        "producer": "Stage 1",   "consumer": "Stages 2, 3"},
            {"name": "FactList",               "producer": "Stage 2",   "consumer": "Stages 4, 6, 7"},
            {"name": "Summary_[A/B/C]",        "producer": "Stage 3",   "consumer": "Stage 4"},
            {"name": "VerificationReport",     "producer": "Stage 4",   "consumer": "Stages 5, 6"},
            {"name": "ContextualAnalysis_[A/B]","producer": "Stage 5",  "consumer": "Stage 6"},
            {"name": "CompiledSummary",        "producer": "Stage 6",   "consumer": "Stage 7"},
            {"name": "FinalDossier",           "producer": "Stage 7",   "consumer": "Export"},
            {"name": "AuditTrail",             "producer": "All stages","consumer": "Stage 7 + export"},
        ],
        "folder_entries": [
            {"path": "├── 00_input/",        "comment": "← original PDF, unchanged",          "highlight": False},
            {"path": "├── 01_ingestion/",    "comment": "← IngestionRecord.json",             "highlight": False},
            {"path": "├── 02_extraction/",   "comment": "← FactList.json",                   "highlight": True},
            {"path": "├── 03_summarization/","comment": "← Summary_A.json, _B.json, _C.json","highlight": False},
            {"path": "├── 04_verification/", "comment": "← VerificationReport.json",         "highlight": True},
            {"path": "├── 05_contextual/",   "comment": "← ContextualAnalysis_A.json, _B.json","highlight": False},
            {"path": "├── 06_compilation/",  "comment": "← CompiledSummary.json",             "highlight": False},
            {"path": "├── 07_final/",        "comment": "← FinalDossier.json + .pdf",         "highlight": True},
            {"path": "└── audit/",           "comment": "← AuditTrail.json, run_manifest.json","highlight": False},
        ],
    },

    # ── Tech Stack ──────────────────────────────────────────
    "stack": {
        "title": "Built with.",
        "intro":  "Practical choices made for correctness and clarity — not to chase "
                  "novelty. Every dependency earns its place.",
        "cards": [
            {"category": "Language",      "name": "Python 3.x",         "desc": "Clear, portable, strong ecosystem for document and ML work."},
            {"category": "PDF parsing",   "name": "pdfplumber",         "desc": "Machine-readable PDFs only. Image-only PDFs are explicitly rejected."},
            {"category": "Data layer",    "name": "Pydantic",           "desc": "All artifacts are typed Pydantic models. No raw dicts between stages."},
            {"category": "LLM — primary", "name": "Anthropic API",      "desc": "Claude Haiku for extraction and summarization. Claude Sonnet for verification."},
            {"category": "LLM — open",    "name": "Together AI",        "desc": "Llama, Qwen, DeepSeek — architecture diversity for multi-model verification."},
            {"category": "Config",        "name": "JSON config",        "desc": "All model assignments, thresholds, and retry limits in configs/v1.json."},
            {"category": "Output",        "name": "ReportLab PDF",      "desc": "Editorial monochrome dossier layout. Typeset, not templated."},
            {"category": "UI",            "name": "Streamlit",          "desc": "Lightweight web UI for local runs. Pipeline progress, artifact inspection."},
        ],
    },
}

# ── Build ──────────────────────────────────────────────────

def build():
    env = Environment(
        loader=FileSystemLoader(str(TMPL_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Allow |safe filter to pass HTML through
    template = env.get_template("index.html")
    html = template.render(**DATA)

    DOCS_DIR.mkdir(exist_ok=True)

    # Copy static assets
    if STATIC_DST.exists():
        shutil.rmtree(STATIC_DST)
    shutil.copytree(STATIC_SRC, STATIC_DST)

    out = DOCS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Built -> {out}")
    print(f"Static -> {STATIC_DST}")


if __name__ == "__main__":
    build()
