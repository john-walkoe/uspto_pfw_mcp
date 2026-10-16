"""Guidance tool (audit F2 split from main.py); content in guidance.py."""



from typing import Optional

from ..api.helpers import (
    format_error_response,
)
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler

logger = get_safe_logger(__name__)


#: Ceiling on a prefix lookup. A one-letter prefix matches dozens of codes and
#: the answer to "what is A?" is the exact code A, not eighty of its neighbours.
_LOOKUP_LIMIT = 25


def _render_code_lookup(code: str) -> str:
    """Decode one document code, or list the codes sharing a prefix.

    Reads the curated decoder AND the EFS-Web CSV: the CSV is what an applicant
    may FILE, so it contains no outgoing examiner code at all, and a lookup
    limited to it would answer "unknown" for CTNF, CTFR, NOA, CTAV and PETDEC
    — the codes most worth asking about.
    """
    from ..reference.doc_codes import lookup_doc_codes

    query = str(code).strip()
    matches = lookup_doc_codes(query, limit=_LOOKUP_LIMIT)
    header = f"# USPTO Document Code Lookup - `{query}`\n"

    if not matches:
        return (
            f"{header}\nNo document code matches `{query}` in either the curated "
            "decoder or the USPTO EFS-Web Document Description List.\n\n"
            "**This is not proof the code is invalid.** USPTO uses roughly 3,100 "
            "document codes and both sources here are working subsets. The "
            "authority for any code you actually hold is the "
            "`documentCodeDescriptionText` returned beside it in its own "
            "documentBag: call "
            "`PFW_get_application_documents(app_number)` and read the field.\n\n"
            "Try a shorter prefix, or "
            "`PFW_get_guidance(section='document_codes')` for the full curated "
            "decoder."
        )

    lines = [header]
    if len(matches) == 1:
        entry = matches[0]
        lines.append(f"**`{entry['code']}`** - {entry['description']}\n")
        if entry.get("process"):
            lines.append(f"- Business process: {entry['process']}")
        if entry.get("category"):
            lines.append(f"- Category: {entry['category']}")
        lines.append(f"- Source: {entry['source']}")
        lines.append(
            f"\nPull it with "
            f"`PFW_get_application_documents(app_number, document_code='{entry['code']}')`."
        )
    else:
        lines.append(
            f"{len(matches)} codes start with `{query.upper()}`"
            + (f" (showing the first {_LOOKUP_LIMIT})" if len(matches) >= _LOOKUP_LIMIT else "")
            + ":\n"
        )
        lines.append("| Code | Description | Source |")
        lines.append("|------|-------------|--------|")
        for entry in matches:
            lines.append(
                f"| `{entry['code']}` | {entry['description']} | {entry['source']} |"
            )
        lines.append(
            "\nAsk for one of these codes exactly to get its business process "
            "and category."
        )

    lines.append(
        "\n*The `documentCodeDescriptionText` beside a document in its own "
        "documentBag outranks this table.*"
    )
    return "\n".join(lines)


def register(mcp) -> None:
    """Register PFW_get_guidance."""
    @mcp.tool(name="PFW_get_guidance", annotations={"defer_loading": False, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_guidance(section: str = "overview", code: Optional[str] = None) -> str:
        """Get selective USPTO PFW guidance sections for context-efficient workflows

        🎯 QUICK REFERENCE - What section for your question?

        🔍 "Find patents by inventor/company/art unit" → fields
        🌳 "Continuations, divisionals, family structure, foreign priority, term adjustment" → family
        📄 "Get complete patent package/documents" → documents
        🔖 "Decode document codes (NOA, CTFR, 892, etc.)" → document_codes
        🤝 "Research IPR vs prosecution patterns" → workflows_ptab
        🚩 "Analyze petition red flags + prosecution" → workflows_fpd
        📊 "Citation analysis for examiner behavior" → workflows_citations
        🧠 "Domain-based RAG for legal framework" → workflows_pinecone
        🏢 "Complete company due diligence" → workflows_complete
        ⚙️ "Convenience parameter searches" → tools
        📏 "Why was my response truncated / how do I page it?" → limits
        ❌ "Search errors or download issues" → errors
        ⚡ "Optimize extraction and context usage" → cost

        🔗 CITATIONS ARE LINKS. Every citable record carries `cite_as`, a ready-made
        markdown link (search hits, family nodes, office actions, documentBag rows,
        the XML response, the term-adjustment response). Paste it after each sentence,
        table row or memo line it supports. An application number, a document code or
        a date with no link is not a citation. `PFW_get_guidance('overview')` carries
        the per-tool table of what each link points at.

        🔑 COMMON WORKFLOW: Reading patent claims
        1. PFW_search_applications_minimal(query/app_number) → get applicationNumberText + XML metadata
        2. PFW_get_patent_or_application_xml(app_number) → structured claims + abstract (PTGRXML for granted, APPXML for pending)
           - Granted patent: returns final claims, no OCR needed
           - Pending application: returns original claims as filed
        3. For amended/latest claims: PFW_get_application_documents(document_code='CLM') → PFW_get_document_content_with_ocr

        🔑 COMMON WORKFLOW: Reading office actions (do NOT start from the document bag)
        1. PFW_get_oa_rejections(application_number) → structured triage: which rejections
           carry 101/102/103/112 (rejectionTypeBag) plus per-section statement counts from
           each action's text
        2. PFW_get_oa_text(application_number, action_type='CTNF'|'CTFR'|'NOA'|'CTRS') →
           the examiner's text in one call, no PDF and no scanning step. section='103' etc.
           narrows to a single rejection. Both tools read the ODP Office Action API: OAs
           mailed from 2007-07-27 onward.
        3. Only if that returns num_found=0, or the document is not an office action:
           PFW_get_application_documents → PFW_get_document_content_with_ocr

        Available sections:
        - overview: Available sections and tool summary
        - workflows_pfw: PFW-only workflows (litigation, due diligence, prior art)
        - workflows_ptab: PFW + PTAB integration workflows
        - workflows_fpd: PFW + FPD integration workflows
        - workflows_citations: PFW + Citations integration workflows
        - workflows_pinecone: PFW + Pinecone RAG/Assistant domain-based strategic search
        - workflows_complete: Four-MCP complete lifecycle analysis
        - documents: Document downloads, codes, and selection guidance
        - document_codes: Comprehensive document code decoder (50+ codes). Pass
          `code=` to decode ONE code or list a prefix instead of reading the whole
          section: `PFW_get_guidance(section='document_codes', code='CTAV')` →
          Advisory Action. This reaches all 392 known codes, including the outgoing
          examiner codes (CTNF, CTFR, NOA, CTAV, PETDEC). The `uspto://pfw/doc-codes`
          resource carries the same office-issued codes in one table beside the
          applicant-filed ones, each row marked in an Origin column.
        - fields: Field selection strategies, context reduction, and search index coverage
        - family: Continuity family graph + patent term adjustment
        - tools: Tool-specific guidance and parameters
        - errors: Common error patterns and troubleshooting
        - advanced: Advanced workflows and optimization
        - cost: Extraction and context efficiency strategies
        - limits: Active response budgets, the _bounds/_window markers, and paging

        Args:
            section: Which guidance section to retrieve (default: overview)
            code: A document code or prefix to decode (e.g. 'CTAV', 'PET'). When
                given, the answer is that code's decode rather than a section, so
                `section` is not required alongside it.

        Returns:
            str: Focused guidance section (1-12K chars vs 62K full content)
        """
        try:
            # A code lookup answers about one code, so it short-circuits the
            # section dispatch entirely rather than appending to a 12K section.
            if code is not None and str(code).strip():
                result = _render_code_lookup(code)
                logger.info(f"Document code lookup returned {len(result)} characters")
                return result

            # Static sectioned guidance content lives in guidance.py
            from ..guidance import get_guidance_sections
            sections = get_guidance_sections()

            if section not in sections:
                available = ", ".join(sections.keys())
                return f"Invalid section '{section}'. Available: {available}"

            result = f"# USPTO PFW MCP Guidance - {section.title()} Section\n\n{sections[section]}"

            logger.info(f"Retrieved PFW guidance section '{section}' ({len(result)} characters)")
            return result

        except Exception as e:
            logger.error(f"Error accessing PFW guidance section '{section}': {e}")
            return format_error_response(f"Failed to access guidance section '{section}': {str(e)}")

