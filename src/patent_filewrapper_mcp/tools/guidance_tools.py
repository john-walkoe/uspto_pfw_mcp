"""Guidance tool (audit F2 split from main.py); content in guidance.py."""



from ..api.helpers import (
    format_error_response,
)
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler

logger = get_safe_logger(__name__)


def register(mcp) -> None:
    """Register PFW_get_guidance."""
    @mcp.tool(name="PFW_get_guidance", annotations={"defer_loading": False, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_guidance(section: str = "overview") -> str:
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

        🔑 COMMON WORKFLOW: Reading patent claims
        1. PFW_search_applications_minimal(query/app_number) → get applicationNumberText + XML metadata
        2. PFW_get_patent_or_application_xml(app_number) → structured claims + abstract (PTGRXML for granted, APPXML for pending)
           - Granted patent: returns final claims, no OCR needed
           - Pending application: returns original claims as filed
        3. For amended/latest claims: PFW_get_application_documents(document_code='CLM') → PFW_get_document_content_with_ocr

        🔑 COMMON WORKFLOW: Reading office actions (do NOT start from the document bag)
        1. PFW_get_oa_rejections(application_number) → structured triage: which OAs carry
           101/102/103/112, Alice flags, citation counts (coverage Oct 1, 2017 onward)
        2. PFW_get_oa_text(application_number, action_type='CTNF'|'CTFR'|'NOA'|'CTRS') →
           the examiner's text in one call, no PDF and no scanning step. section='103' etc.
           narrows to a single rejection. Coverage reaches OAs mailed roughly 2008 onward,
           so it works on far older cases than PFW_get_oa_rejections does.
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
        - document_codes: Comprehensive document code decoder (50+ codes)
        - fields: Field selection strategies, context reduction, and search index coverage
        - family: Continuity family graph + patent term adjustment
        - tools: Tool-specific guidance and parameters
        - errors: Common error patterns and troubleshooting
        - advanced: Advanced workflows and optimization
        - cost: Extraction and context efficiency strategies
        - limits: Active response budgets, the _bounds/_window markers, and paging

        Args:
            section: Which guidance section to retrieve (default: overview)

        Returns:
            str: Focused guidance section (1-12K chars vs 62K full content)
        """
        try:
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

