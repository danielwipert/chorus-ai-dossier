"""
Chorus AI — Dossier Web UI
Run with: streamlit run app.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

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

CONFIG_PATH = Path(__file__).parent / "configs" / "v1.json"
RUNS_DIR = Path(__file__).parent / "runs"

st.set_page_config(page_title="Chorus AI — Dossier", layout="centered")
st.title("Chorus AI — Dossier")
st.caption(
    "Upload a PDF and generate a structured analytical report — "
    "fact-checked, multi-model, grounded."
)

uploaded = st.file_uploader("Upload a PDF", type=["pdf"], label_visibility="collapsed")

if not uploaded:
    st.info("Upload a PDF above to get started.")
    st.stop()

st.divider()

if st.button("Generate Dossier", type="primary", use_container_width=True):
    # Write the uploaded file to a temp location so the pipeline can hash + read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded.read())
        tmp_pdf = Path(tmp.name)

    try:
        config = load_and_canonicalize_config(CONFIG_PATH)
    except Exception as exc:
        st.error(f"Could not load config: {exc}")
        st.stop()

    run_id = compute_run_id(tmp_pdf, config)
    run_root = RUNS_DIR / f"dossier_{run_id}"

    if not run_root.exists():
        run_root = create_run_folders(RUNS_DIR, run_id, config, tmp_pdf)

    source_sha = sha256_file(tmp_pdf)

    STAGES = [
        ("Ingestion",           "Extracting and validating text from PDF"),
        ("Extraction",          "Finding and cataloguing all factual claims"),
        ("Summarization",       "Generating 3 independent model summaries"),
        ("Verification",        "Checking summaries against the fact list"),
        ("Contextual Analysis", "Adding external scholarly context"),
        ("Compilation",         "Synthesising the final compiled report"),
        ("Export",              "Rendering PDF dossier"),
    ]

    progress = st.progress(0, text="Starting pipeline…")
    stage_slots = [st.empty() for _ in STAGES]
    error_box = st.empty()

    def mark(i: int, label: str, done: bool = False, err: bool = False) -> None:
        icon = "✅" if done else ("❌" if err else "⏳")
        stage_slots[i].markdown(f"{icon} **{STAGES[i][0]}** — {label}")

    failed = False
    result: dict = {}

    try:
        # Stage 1
        mark(0, STAGES[0][1])
        run_ingest(run_root, source_sha)
        mark(0, "done", done=True)
        progress.progress(1 / 7, text="Ingestion complete")

        # Stage 2
        mark(1, STAGES[1][1])
        run_extract(run_root)
        mark(1, "done", done=True)
        progress.progress(2 / 7, text="Extraction complete")

        # Stage 3
        mark(2, STAGES[2][1])
        run_summarize(str(run_root))
        mark(2, "done", done=True)
        progress.progress(3 / 7, text="Summarization complete")

        # Stage 4
        mark(3, STAGES[3][1])
        verify_result = run_verify(str(run_root))
        if not verify_result.get("ok"):
            raise ChorusFatalError("VERIFY_FAILED", "Verification failed", verify_result)
        mark(3, "done", done=True)
        progress.progress(4 / 7, text="Verification complete")

        # Stage 5 (non-fatal)
        mark(4, STAGES[4][1])
        run_contextualize(run_root)
        mark(4, "done", done=True)
        progress.progress(5 / 7, text="Contextual analysis complete")

        # Stage 6
        mark(5, STAGES[5][1])
        compile_result = run_compile(str(run_root))
        if not compile_result.get("ok"):
            raise ChorusFatalError("COMPILE_FAILED", "Compilation failed", compile_result)
        mark(5, "done", done=True)
        progress.progress(6 / 7, text="Compilation complete")

        # Stage 7
        mark(6, STAGES[6][1])
        result = run_export(str(run_root))
        if not result.get("ok"):
            raise ChorusFatalError("EXPORT_FAILED", "Export failed", result)
        mark(6, "done", done=True)
        progress.progress(1.0, text="Done")

    except ChorusFatalError as exc:
        error_box.error(f"Pipeline failed: **{exc.code}** — {exc}")
        failed = True

    except Exception as exc:
        error_box.error(f"Unexpected error: {exc}")
        failed = True

    finally:
        tmp_pdf.unlink(missing_ok=True)

    if not failed and result.get("ok"):
        st.divider()
        st.success("Dossier generated successfully.")

        # Show executive overview
        json_path = result.get("artifact")
        if json_path and Path(json_path).exists():
            dossier = json.loads(Path(json_path).read_text(encoding="utf-8"))
            overview = dossier.get("executive_overview", "")
            if overview:
                st.subheader("Executive Overview")
                st.write(overview)

            key_claims = dossier.get("key_claims", [])
            if key_claims:
                st.subheader("Key Claims")
                for claim in key_claims[:5]:
                    fact_ids = ", ".join(claim.get("fact_ids", []))
                    st.markdown(
                        f"- {claim.get('claim', '')} "
                        f"{'`' + fact_ids + '`' if fact_ids else ''}"
                    )

        # Download button for PDF
        pdf_path = result.get("pdf")
        if pdf_path and Path(pdf_path).exists():
            pdf_bytes = Path(pdf_path).read_bytes()
            st.download_button(
                label="Download Dossier PDF",
                data=pdf_bytes,
                file_name=f"dossier_{uploaded.name}",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        else:
            st.warning("PDF rendering failed — download the JSON dossier instead.")
            if json_path and Path(json_path).exists():
                st.download_button(
                    label="Download Dossier JSON",
                    data=Path(json_path).read_bytes(),
                    file_name=f"dossier_{uploaded.name.replace('.pdf', '.json')}",
                    mime="application/json",
                    use_container_width=True,
                )
