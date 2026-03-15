"""
Chorus AI — Dossier Generator (Streamlit UI)
Run with: streamlit run app.py
"""

import json
import threading
import time
from pathlib import Path

import streamlit as st

# ── Constants ─────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent
CONFIG_PATH = REPO_ROOT / "configs" / "v1.json"
RUNS_DIR = REPO_ROOT / "runs"
UPLOADS_DIR = REPO_ROOT / ".streamlit_uploads"

STATE_ORDER = [
    "INIT",
    "INGESTED",
    "EXTRACTED",
    "SUMMARIZED",
    "VERIFIED",
    "CONTEXTUALIZED",
    "COMPILED",
    "FINALIZED",
]
STATE_INDEX = {s: i for i, s in enumerate(STATE_ORDER)}

STAGE_LABELS = {
    "INIT":           ("1/7", "Initializing"),
    "INGESTED":       ("1/7", "Ingesting PDF"),
    "EXTRACTED":      ("2/7", "Extracting Facts"),
    "SUMMARIZED":     ("3/7", "Generating Summaries"),
    "VERIFIED":       ("4/7", "Verifying Summaries"),
    "CONTEXTUALIZED": ("5/7", "Contextual Analysis"),
    "COMPILED":       ("6/7", "Compiling Report"),
    "FINALIZED":      ("7/7", "Done"),
}

# ── Pipeline thread ───────────────────────────────────────────────────────────

def _run_pipeline(pdf_path: Path, state: dict) -> None:
    """
    Runs the full 7-stage pipeline in a background thread.
    Writes progress into `state` (a shared dict from st.session_state).
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")

        from chorus_ai.core.config import load_and_canonicalize_config
        from chorus_ai.core.errors import ChorusFatalError
        from chorus_ai.core.hashing import sha256_file
        from chorus_ai.runs.layout import compute_run_id, create_run_folders
        from chorus_ai.stages.ingest import run_ingest
        from chorus_ai.stages.extract import run_extract
        from chorus_ai.stages.summarize import run_summarize
        from chorus_ai.stages.verify import run_verify
        from chorus_ai.stages.contextualize import run_contextualize
        from chorus_ai.stages.compile import run_compile
        from chorus_ai.stages.export import run_export

        config = load_and_canonicalize_config(CONFIG_PATH)
        run_id = compute_run_id(pdf_path, config)
        run_root = RUNS_DIR / f"dossier_{run_id}"

        state["run_id"] = run_id
        state["run_root"] = str(run_root)

        if not run_root.exists():
            run_root = create_run_folders(RUNS_DIR, run_id, config, pdf_path)

        source_sha = sha256_file(pdf_path)

        # Stage 1 — Ingestion
        state["current_stage"] = "INGESTED"
        run_ingest(run_root, source_sha)
        state["state"] = "INGESTED"

        # Stage 2 — Extraction
        state["current_stage"] = "EXTRACTED"
        run_extract(run_root)
        state["state"] = "EXTRACTED"

        # Stage 3 — Summarization
        state["current_stage"] = "SUMMARIZED"
        run_summarize(str(run_root))
        state["state"] = "SUMMARIZED"

        # Stage 4 — Verification
        state["current_stage"] = "VERIFIED"
        verify_result = run_verify(str(run_root))
        if not verify_result.get("ok"):
            raise ChorusFatalError("VERIFY_FAILED", "Verification failed", verify_result)
        state["state"] = "VERIFIED"

        # Stage 5 — Contextual Analysis (non-fatal)
        state["current_stage"] = "CONTEXTUALIZED"
        run_contextualize(run_root)
        state["state"] = "CONTEXTUALIZED"

        # Stage 6 — Compilation
        state["current_stage"] = "COMPILED"
        compile_result = run_compile(str(run_root))
        if not compile_result.get("ok"):
            raise ChorusFatalError("COMPILE_FAILED", "Compile failed", compile_result)
        state["state"] = "COMPILED"

        # Stage 7 — Export
        state["current_stage"] = "FINALIZED"
        export_result = run_export(str(run_root))
        if not export_result.get("ok"):
            raise ChorusFatalError("EXPORT_FAILED", "Export failed", export_result)
        state["state"] = "FINALIZED"
        state["done"] = True

    except Exception as exc:
        state["error"] = str(exc)
        state["done"] = True


# ── UI helpers ────────────────────────────────────────────────────────────────

def _render_progress(ps: dict) -> None:
    current = ps.get("current_stage", "INIT")
    idx = STATE_INDEX.get(current, 0)
    total = len(STATE_ORDER) - 1  # INIT is not a pipeline stage

    step_label, stage_label = STAGE_LABELS.get(current, ("", current))

    st.progress(idx / total)
    st.caption(f"Stage {step_label} — {stage_label}")

    # Checklist
    completed = STATE_INDEX.get(ps.get("state", "INIT"), 0)
    rows = []
    for s in STATE_ORDER[1:]:
        si = STATE_INDEX[s]
        _, label = STAGE_LABELS[s]
        if si < completed:
            rows.append(f"- [x] {label}")
        elif si == STATE_INDEX.get(current, 0):
            rows.append(f"- [ ] **{label}** _(running...)_")
        else:
            rows.append(f"- [ ] {label}")
    st.markdown("\n".join(rows))


def _render_dossier(run_root: Path) -> None:
    dossier_path = run_root / "70_export" / "final_dossier.json"
    pdf_path = run_root / "70_export" / "final_dossier.pdf"

    if not dossier_path.exists():
        st.error("Dossier output not found.")
        return

    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    sections = dossier.get("sections", {})
    warnings = dossier.get("warnings", [])

    # Download
    col_dl, col_id = st.columns([2, 5])
    if pdf_path.exists():
        with col_dl:
            st.download_button(
                "Download PDF Dossier",
                data=pdf_path.read_bytes(),
                file_name="dossier.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
    with col_id:
        st.caption(f"Run ID: `{dossier.get('dossier_id', '—')}`")

    if warnings:
        st.warning("Pipeline warnings: " + " | ".join(warnings))

    st.divider()

    # 1 — Executive Overview
    st.subheader("Executive Overview")
    st.write(sections.get("executive_overview", "—"))

    # 2 — Key Claims
    st.subheader("Key Claims")
    key_claims = sections.get("key_claims", [])
    if isinstance(key_claims, list):
        for claim in key_claims:
            if isinstance(claim, dict):
                facts = ", ".join(claim.get("supporting_facts", []))
                suffix = f"  *({facts})*" if facts else ""
                st.markdown(f"- {claim.get('claim', '')}{suffix}")
            else:
                st.markdown(f"- {claim}")
    elif key_claims:
        st.write(key_claims)

    # 3 — Compiled Summary
    st.subheader("Compiled Summary")
    st.write(sections.get("compiled_summary", "—"))

    # 4 — Contextual Analysis
    with st.expander("Contextual Analysis (External Sources)"):
        ctx = sections.get("contextual_analysis", "—")
        if isinstance(ctx, list):
            for section in ctx:
                if isinstance(section, dict):
                    st.markdown(f"**{section.get('lens', '').replace('_', ' ').title()}**")
                    st.write(section.get("content", ""))
                    srcs = section.get("sources", [])
                    if srcs:
                        st.caption("Sources: " + " · ".join(srcs))
                else:
                    st.write(section)
        elif isinstance(ctx, dict):
            for lens, content in ctx.items():
                st.markdown(f"**{lens.replace('_', ' ').title()}**")
                st.write(content)
        else:
            st.write(ctx)

    # 5 — Risks & Limitations
    with st.expander("Risks, Limitations & Warnings"):
        st.write(sections.get("risks_and_limitations", "—"))

    # 6 — Audit Trail
    with st.expander("Audit Trail"):
        audit = sections.get("audit_trail", {})
        if isinstance(audit, dict):
            vcol, fcol = st.columns(2)
            with vcol:
                verif = audit.get("verification", {})
                st.metric("Verification Status", verif.get("status", "—").upper())
                st.metric("Retries Used", verif.get("retries_used", 0))
            with fcol:
                st.metric("Facts Extracted", audit.get("fact_count", "—"))
                scores = verif.get("summary_scores", [])
                if scores:
                    avg = sum(s.get("contradiction_score", 0) for s in scores) / len(scores)
                    st.metric("Avg Contradiction Score", f"{avg:.3f}")
            st.json(audit)
        else:
            st.json(audit)

    # Model roster
    roster = dossier.get("model_roster", [])
    if roster:
        with st.expander("Model Roster"):
            for m in roster:
                st.markdown(
                    f"**{m.get('role', m.get('slot', '?'))}** — "
                    f"`{m.get('model_id', '?')}` ({m.get('model_short', '')})"
                )


def _render_sidebar() -> None:
    with st.sidebar:
        st.header("Configuration")
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            models = cfg.get("models", {})
            st.markdown("**Models**")
            for slot, model in models.items():
                label = slot.replace("_", " ").title()
                short = model.split("/")[-1] if "/" in model else model
                st.caption(f"{label}: `{short}`")

            st.divider()
            verif = cfg.get("verification", {})
            st.markdown("**Verification**")
            st.caption(f"Max contradiction: `{verif.get('max_contradiction_score', '?')}`")
            st.caption(f"Max retries: `{verif.get('max_retries', '?')}`")
        except Exception:
            st.caption("Could not load config.")

        # Show existing runs
        existing = sorted(RUNS_DIR.glob("dossier_*"), reverse=True) if RUNS_DIR.exists() else []
        if existing:
            st.divider()
            st.markdown("**Recent Runs**")
            for r in existing[:5]:
                status_f = r / "00_meta" / "status.json"
                state = "?"
                if status_f.exists():
                    try:
                        state = json.loads(status_f.read_text()).get("state", "?")
                    except Exception:
                        pass
                icon = "✓" if state == "FINALIZED" else "…"
                st.caption(f"{icon} `{r.name[-20:]}`")


# ── App ───────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Chorus AI — Dossier",
    page_icon="📄",
    layout="wide",
)

_render_sidebar()

st.title("Chorus AI — Dossier Generator")
st.caption("Upload a PDF to produce a multi-model, fact-verified analytical report.")

# Session state defaults
if "ps" not in st.session_state:
    st.session_state.ps = {}      # pipeline state dict shared with thread
if "thread" not in st.session_state:
    st.session_state.thread = None

ps: dict = st.session_state.ps
thread: threading.Thread | None = st.session_state.thread

running = thread is not None and thread.is_alive()
done = ps.get("done", False)
error = ps.get("error")

# ── Upload / start ──
if not running and not done:
    uploaded = st.file_uploader("Upload PDF", type=["pdf"])

    if uploaded:
        UPLOADS_DIR.mkdir(exist_ok=True)
        pdf_path = UPLOADS_DIR / uploaded.name
        pdf_path.write_bytes(uploaded.getvalue())

        st.success(f"{uploaded.name} — {uploaded.size:,} bytes")

        if st.button("Generate Dossier", type="primary"):
            st.session_state.ps = {}
            new_thread = threading.Thread(
                target=_run_pipeline,
                args=(pdf_path, st.session_state.ps),
                daemon=True,
            )
            st.session_state.thread = new_thread
            new_thread.start()
            st.rerun()

# ── Running: live progress ──
elif running:
    st.info("Pipeline running — this takes a few minutes.")
    _render_progress(ps)
    time.sleep(2)
    st.rerun()

# ── Error ──
elif done and error:
    st.error(f"Pipeline failed: {error}")
    run_root_str = ps.get("run_root")
    if run_root_str:
        failure_f = Path(run_root_str) / "00_meta" / "failure.json"
        if failure_f.exists():
            with st.expander("Failure details"):
                st.json(json.loads(failure_f.read_text(encoding="utf-8")))
    if st.button("Start Over"):
        st.session_state.ps = {}
        st.session_state.thread = None
        st.rerun()

# ── Done ──
elif done and not error:
    run_root = Path(ps.get("run_root", ""))
    _render_dossier(run_root)
    st.divider()
    if st.button("Process Another PDF"):
        st.session_state.ps = {}
        st.session_state.thread = None
        st.rerun()
