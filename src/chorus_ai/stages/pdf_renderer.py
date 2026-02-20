"""
PDF renderer for the Chorus AI Final Dossier.

Converts a FinalDossier dict (as produced by Stage 7) into a formatted PDF.
Design aesthetic: editorial monochrome — clean typography, red accent, cover page,
per-page header/footer.
"""
from __future__ import annotations

import xml.sax.saxutils as sax
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Palette — monochrome editorial with a single deep-red accent
# ---------------------------------------------------------------------------
_BLACK = HexColor("#0d0d0d")
_RED = HexColor("#8b0000")
_GRAY = HexColor("#666666")
_LIGHT_GRAY = HexColor("#dedede")
_RULE_COLOR = HexColor("#222222")

PAGE_W, PAGE_H = letter
MARGIN = 1.1 * inch
CONTENT_W = PAGE_W - 2 * MARGIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """Escape text for ReportLab's XML parser."""
    return sax.escape(str(text))


def _hrule(thick: float = 0.5, color: Any = _RULE_COLOR, after: float = 6.0) -> HRFlowable:
    return HRFlowable(width="100%", thickness=thick, color=color, spaceAfter=after)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> Dict[str, ParagraphStyle]:
    return {
        "cover_eyebrow": ParagraphStyle(
            "cover_eyebrow",
            fontName="Helvetica",
            fontSize=8,
            textColor=_GRAY,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName="Helvetica-Bold",
            fontSize=30,
            textColor=_BLACK,
            alignment=TA_CENTER,
            spaceAfter=8,
            leading=36,
        ),
        "cover_meta_key": ParagraphStyle(
            "cover_meta_key",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_GRAY,
            alignment=TA_RIGHT,
        ),
        "cover_meta_val": ParagraphStyle(
            "cover_meta_val",
            fontName="Helvetica",
            fontSize=8,
            textColor=_BLACK,
            alignment=TA_LEFT,
        ),
        "section_eyebrow": ParagraphStyle(
            "section_eyebrow",
            fontName="Helvetica",
            fontSize=7,
            textColor=_RED,
            spaceAfter=2,
            spaceBefore=20,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=_BLACK,
            spaceAfter=6,
            spaceBefore=0,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Times-Roman",
            fontSize=10,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            leading=15,
        ),
        "body_italic": ParagraphStyle(
            "body_italic",
            fontName="Times-Italic",
            fontSize=9,
            textColor=_GRAY,
            alignment=TA_JUSTIFY,
            spaceAfter=10,
            leading=14,
        ),
        "claim_num": ParagraphStyle(
            "claim_num",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_RED,
            spaceAfter=2,
            spaceBefore=12,
        ),
        "claim_text": ParagraphStyle(
            "claim_text",
            fontName="Times-Roman",
            fontSize=10,
            textColor=_BLACK,
            spaceAfter=3,
            leading=15,
            leftIndent=12,
        ),
        "claim_meta": ParagraphStyle(
            "claim_meta",
            fontName="Helvetica",
            fontSize=8,
            textColor=_GRAY,
            spaceAfter=6,
            leftIndent=12,
        ),
        "audit_key": ParagraphStyle(
            "audit_key",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_GRAY,
        ),
        "audit_val": ParagraphStyle(
            "audit_val",
            fontName="Helvetica",
            fontSize=8,
            textColor=_BLACK,
        ),
        "warning_text": ParagraphStyle(
            "warning_text",
            fontName="Helvetica",
            fontSize=9,
            textColor=_RED,
            spaceAfter=4,
            leading=13,
        ),
        # Contextual analysis structure
        "ctx_model_header": ParagraphStyle(
            "ctx_model_header",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_GRAY,
            spaceBefore=16,
            spaceAfter=2,
        ),
        "ctx_lens_header": ParagraphStyle(
            "ctx_lens_header",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=_BLACK,
            spaceBefore=10,
            spaceAfter=3,
        ),
        "ctx_sources_label": ParagraphStyle(
            "ctx_sources_label",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_GRAY,
            spaceBefore=6,
            spaceAfter=2,
        ),
        "ctx_citation": ParagraphStyle(
            "ctx_citation",
            fontName="Helvetica",
            fontSize=8,
            textColor=_GRAY,
            leftIndent=14,
            spaceAfter=3,
            leading=12,
        ),
        # Verification receipt
        "receipt_header": ParagraphStyle(
            "receipt_header",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_BLACK,
        ),
        "receipt_claim_num": ParagraphStyle(
            "receipt_claim_num",
            fontName="Courier-Bold",
            fontSize=8,
            textColor=_GRAY,
            spaceAfter=1,
        ),
        "receipt_status": ParagraphStyle(
            "receipt_status",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_RED,
            alignment=TA_RIGHT,
        ),
        "receipt_claim_text": ParagraphStyle(
            "receipt_claim_text",
            fontName="Times-Roman",
            fontSize=10,
            textColor=_BLACK,
            spaceAfter=3,
            leading=14,
        ),
        "receipt_meta": ParagraphStyle(
            "receipt_meta",
            fontName="Courier",
            fontSize=7,
            textColor=_GRAY,
            spaceAfter=0,
            leading=11,
        ),
        # Compiled summary — editorial typography
        # Lead: first paragraph, flush left (no indent), slightly larger, generous air
        "summary_lead": ParagraphStyle(
            "summary_lead",
            fontName="Times-Roman",
            fontSize=11,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            leading=18,
            spaceAfter=2,
        ),
        # Body: subsequent paragraphs, first-line indent does the visual separating work
        # (no spaceAfter — the indent reads as a new paragraph, like print editorial)
        "summary_body": ParagraphStyle(
            "summary_body",
            fontName="Times-Roman",
            fontSize=11,
            textColor=_BLACK,
            alignment=TA_JUSTIFY,
            leading=18,
            firstLineIndent=20,
            spaceAfter=0,
        ),
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_block(num: int, title: str, s: Dict[str, ParagraphStyle]) -> List:
    return [
        Paragraph(f"SECTION {num:02d}", s["section_eyebrow"]),
        Paragraph(_e(title), s["section_title"]),
        _hrule(),
    ]


def _cover_elements(dossier: Dict[str, Any], s: Dict[str, ParagraphStyle]) -> List:
    sha = dossier.get("source_doc_sha256", "")
    sha_display = (sha[:32] + "\u2026") if len(sha) > 32 else sha
    dossier_id = dossier.get("dossier_id", "UNKNOWN")
    created = dossier.get("created_at", "")[:19].replace("T", " ")
    run_status = dossier.get("run_status", "complete").upper()

    elements: List = [Spacer(1, 1.4 * inch)]

    elements.append(_hrule(thick=2.5, color=_RED, after=20))
    elements.append(Paragraph("CHORUS AI", s["cover_eyebrow"]))
    elements.append(Paragraph("INTELLIGENCE DOSSIER", s["cover_title"]))
    elements.append(_hrule(thick=2.5, color=_RED, after=28))
    elements.append(Spacer(1, 0.25 * inch))

    col_w = [2.0 * inch, CONTENT_W - 2.0 * inch]
    meta_rows = [
        [Paragraph("DOSSIER ID", s["cover_meta_key"]),
         Paragraph(_e(dossier_id), s["cover_meta_val"])],
        [Paragraph("SOURCE SHA-256", s["cover_meta_key"]),
         Paragraph(_e(sha_display), s["cover_meta_val"])],
        [Paragraph("GENERATED", s["cover_meta_key"]),
         Paragraph(_e(created + " UTC"), s["cover_meta_val"])],
        [Paragraph("PIPELINE", s["cover_meta_key"]),
         Paragraph("Chorus AI V1  \u00b7  7-Stage Verification Pipeline", s["cover_meta_val"])],
        [Paragraph("STATUS", s["cover_meta_key"]),
         Paragraph(_e(run_status), s["cover_meta_val"])],
    ]
    meta_ts = TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _LIGHT_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])
    t = Table(meta_rows, colWidths=col_w)
    t.setStyle(meta_ts)
    elements.append(t)

    warnings = dossier.get("warnings", [])
    if warnings:
        elements.append(Spacer(1, 0.35 * inch))
        elements.append(_hrule(thick=0.5, color=_RED, after=6))
        elements.append(Paragraph("PIPELINE WARNINGS", s["section_eyebrow"]))
        for w in warnings:
            elements.append(Paragraph(f"\u2022 {_e(w)}", s["warning_text"]))

    elements.append(PageBreak())
    return elements


def _verification_receipt_elements(claims: List[Dict[str, Any]], s: Dict[str, ParagraphStyle]) -> List:
    """
    Render key claims as a fact-check verification receipt.

    Styled like a POS printout — compact, monospaced metadata, dashed separators —
    to communicate that this is a traceability log, not a narrative section.
    """
    _BG = HexColor("#f7f7f7")

    if not claims:
        return [Paragraph("[No claims verified.]", s["body"])]

    total = len(claims)
    elements: List = []

    # Receipt header band
    header_row = [[Paragraph(
        f"FACT-CHECK RECEIPT  \u00b7  {total} claim{'s' if total != 1 else ''} verified against extracted facts",
        s["receipt_header"],
    )]]
    header_t = Table(header_row, colWidths=[CONTENT_W])
    header_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG),
        ("LINEABOVE",  (0, 0), (-1,  0), 1.0, _RULE_COLOR),
        ("LINEBELOW",  (0, -1), (-1, -1), 0.5, _LIGHT_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elements.append(header_t)
    elements.append(Spacer(1, 0.08 * inch))

    for i, claim in enumerate(claims):
        text = claim.get("claim", "")
        fact_ids = claim.get("fact_ids", [])
        convergence = (claim.get("convergence") or "").upper() or "\u2014"
        sources = claim.get("source_summaries", [])

        fact_ref = " \u00b7 ".join(fact_ids) if fact_ids else "\u2014"
        n_src = len(sources)

        # Two-column claim header: number left, VERIFIED right
        claim_hdr = Table(
            [[Paragraph(f"#{i + 1:03d}", s["receipt_claim_num"]),
              Paragraph("\u2713 VERIFIED", s["receipt_status"])]],
            colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5],
        )
        claim_hdr.setStyle(TableStyle([
            ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))

        meta = f"FACTS: {fact_ref}    CONVERGENCE: {convergence}    SOURCES: {n_src} of 3"

        block = [
            claim_hdr,
            Paragraph(_e(text), s["receipt_claim_text"]),
            Paragraph(_e(meta), s["receipt_meta"]),
        ]
        elements.append(KeepTogether(block))

        if i < total - 1:
            elements.append(HRFlowable(
                width="100%", thickness=0.5, color=_LIGHT_GRAY,
                dash=(2, 3), spaceAfter=6, spaceBefore=6,
            ))

    # Receipt footer band
    elements.append(Spacer(1, 0.08 * inch))
    footer_row = [[Paragraph(
        f"END OF RECEIPT  \u00b7  {total}/{total} claims traceable to source facts",
        s["receipt_header"],
    )]]
    footer_t = Table(footer_row, colWidths=[CONTENT_W])
    footer_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG),
        ("LINEABOVE",  (0, 0), (-1,  0), 0.5, _LIGHT_GRAY),
        ("LINEBELOW",  (0, -1), (-1, -1), 1.0, _RULE_COLOR),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elements.append(footer_t)

    return elements


def _audit_table_elements(audit: Dict[str, Any], s: Dict[str, ParagraphStyle]) -> List:
    def _row(key: str, val: Any) -> List:
        return [Paragraph(_e(key), s["audit_key"]), Paragraph(_e(str(val)), s["audit_val"])]

    verification = audit.get("verification", {})
    rows = [
        _row("Source SHA-256", audit.get("source_doc_sha256", "")),
        _row("Page Count", audit.get("page_count", "")),
        _row("Total Characters", f"{audit.get('total_chars', 0):,}"),
        _row("Facts Extracted", audit.get("fact_count", "")),
        _row("Fact Set ID", audit.get("fact_set_id", "")),
        _row("Verification Status", verification.get("status", "")),
        _row("Pass Threshold", verification.get("pass_threshold", "")),
        _row("Retries Used", verification.get("retries_used", 0)),
    ]
    for score in verification.get("summary_scores", []):
        slot = score.get("model_slot", "?")
        cov = score.get("coverage_score", "?")
        vstatus = score.get("status", "?")
        rows.append(_row(f"  {slot}", f"{cov}  [{vstatus}]"))

    ctx = audit.get("contextual_analyses", [])
    rows.append(_row("Contextual Analyses", ", ".join(ctx) if ctx else "none"))

    col_w = [2.2 * inch, CONTENT_W - 2.2 * inch]
    ts = TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _LIGHT_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])
    t = Table(rows, colWidths=col_w)
    t.setStyle(ts)
    return [t]


def _contextual_analysis_elements(ctx_text: str, s: Dict[str, ParagraphStyle]) -> List:
    """
    Parse and render the contextual analysis string produced by _build_contextual_analysis_section.

    The string embeds structure via conventions:
      === Contextual Analysis (contextualizer_x) ===  → model subheader + rule
      [Lens Name]                                      → lens subheading
      Sources:                                         → sources label
        - Citation text                                → indented citation
      Everything else                                  → body paragraph

    Splitting on \\n\\n first gives clean chunks regardless of how the LLM
    formatted internal whitespace.
    """
    if not ctx_text or ctx_text.startswith("[No contextual"):
        return [Paragraph(_e(ctx_text), s["body"])]

    elements: List = []
    chunks = [c.strip() for c in ctx_text.split("\n\n") if c.strip()]

    for chunk in chunks:
        # Collapse internal newlines so each chunk is a single line for matching
        line = " ".join(chunk.split())

        if line.startswith("===") and line.endswith("==="):
            # Model section header  e.g. "=== Contextual Analysis (contextualizer_a) ==="
            model_name = line.strip("=").strip()
            elements.append(Spacer(1, 0.08 * inch))
            elements.append(_hrule(thick=0.5, color=_LIGHT_GRAY, after=4))
            elements.append(Paragraph(_e(model_name), s["ctx_model_header"]))

        elif line.startswith("[") and line.endswith("]"):
            # Lens header  e.g. "[Historical Context]"
            lens = line[1:-1]
            elements.append(Paragraph(_e(lens), s["ctx_lens_header"]))

        elif line == "Sources:":
            elements.append(Paragraph("Sources:", s["ctx_sources_label"]))

        elif line.startswith("- "):
            # Citation entry
            elements.append(Paragraph(_e(line[2:]), s["ctx_citation"]))

        elif line.startswith("Limitations:"):
            elements.append(Paragraph(_e(line), s["body_italic"]))

        else:
            elements.append(Paragraph(_e(line), s["body"]))

    return elements


def _compiled_summary_elements(text: str, s: Dict[str, ParagraphStyle]) -> List:
    """
    Render compiled summary text with editorial typography:
    - First paragraph: flush left, 11pt, generous leading (no indent by convention)
    - Subsequent paragraphs: first-line indent, no extra space between — the indent
      does the visual separation, exactly as in print long-form editorial.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        return [Paragraph("[Compiled summary not available.]", s["body"])]

    elements: List = []
    for i, para in enumerate(paras):
        style = s["summary_lead"] if i == 0 else s["summary_body"]
        elements.append(Paragraph(_e(para.replace("\n", " ")), style))
    return elements


def _draw_page(canvas: Any, doc: Any, dossier_id: str, created: str) -> None:
    """Render header and footer on every non-cover page."""
    if canvas.getPageNumber() == 1:
        return
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_GRAY)

    # Header
    canvas.drawString(MARGIN, PAGE_H - 0.65 * inch, "CHORUS AI  \u00b7  INTELLIGENCE DOSSIER")
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.65 * inch, dossier_id)
    canvas.setStrokeColor(_RULE_COLOR)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, PAGE_H - 0.72 * inch, PAGE_W - MARGIN, PAGE_H - 0.72 * inch)

    # Footer
    canvas.line(MARGIN, 0.72 * inch, PAGE_W - MARGIN, 0.72 * inch)
    canvas.drawString(MARGIN, 0.52 * inch, f"Generated {created} UTC")
    canvas.drawRightString(PAGE_W - MARGIN, 0.52 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_dossier_pdf(dossier: Dict[str, Any], out_path: Path) -> None:
    """
    Render a FinalDossier dict to a formatted PDF at out_path.

    Sections rendered:
      Cover page (dossier ID, SHA, pipeline metadata)
      01 – Executive Overview
      02 – Compiled Summary
      03 – Contextual Analysis
      04 – Risks, Limitations, and Warnings
      05 – Verification Receipt (key claims fact-check log)
      06 – Audit Trail
    """
    s = _styles()
    sections = dossier.get("sections", {})
    dossier_id = dossier.get("dossier_id", "UNKNOWN")
    created = dossier.get("created_at", "")[:19].replace("T", " ")

    def _on_page(canvas: Any, doc: Any) -> None:
        _draw_page(canvas, doc, dossier_id, created)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    story: List = []

    # Cover
    story.extend(_cover_elements(dossier, s))

    # 01 — Executive Overview
    story.extend(_section_block(1, "EXECUTIVE OVERVIEW", s))
    overview = sections.get("executive_overview", "[Not available.]")
    story.append(Paragraph(_e(overview), s["body"]))

    # 02 — Compiled Summary
    story.extend(_section_block(2, "COMPILED SUMMARY", s))
    story.extend(_compiled_summary_elements(
        sections.get("compiled_summary", "[Not available.]"), s
    ))

    # 03 — Contextual Analysis
    story.extend(_section_block(3, "CONTEXTUAL ANALYSIS", s))
    story.append(Paragraph(
        "External context provided by contextualizer models. All claims in this section "
        "are sourced from external references and are explicitly labeled as such.",
        s["body_italic"],
    ))
    story.extend(_contextual_analysis_elements(
        sections.get("contextual_analysis", "[No contextual analysis available.]"), s
    ))

    # 04 — Risks, Limitations, and Warnings
    story.extend(_section_block(4, "RISKS, LIMITATIONS, AND WARNINGS", s))
    risks = sections.get("risks_and_limitations", "[No risks or limitations identified.]")
    story.append(Paragraph(_e(risks), s["body"]))

    # 05 — Verification Receipt
    story.extend(_section_block(5, "VERIFICATION RECEIPT", s))
    story.extend(_verification_receipt_elements(sections.get("key_claims", []), s))

    # 06 — Audit Trail
    story.extend(_section_block(6, "AUDIT TRAIL", s))
    story.extend(_audit_table_elements(sections.get("audit_trail", {}), s))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
