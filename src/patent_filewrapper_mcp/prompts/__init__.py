"""
PFW MCP Prompt Templates

This module contains comprehensive prompt templates for Patent File Wrapper analysis workflows.
Each prompt provides complete implementation guidance with working code, error handling, safety rails,
and cross-MCP integration patterns (PTAB, FPD, Citations).

All prompts follow the comprehensive implementation pattern:
- Complete working code with loops and data processing
- Error handling with try/except for cross-MCP calls
- Safety rails with explicit context limits
- Presentation formatting with markdown tables
- Result aggregation and scoring systems
- Cross-MCP integration workflows

Available Prompts:
- complete_patent_package_retrieval_PTAB_FPD: Complete patent document package retrieval
- patent_search: Fuzzy patent search for partial information
- art_unit_quality_assessment_FPD: Art unit prosecution quality via petition patterns
- litigation_research_setup_PTAB_FPD: Comprehensive litigation research package
- inventor_portfolio_analysis: Inventor portfolio analysis with PTAB/FPD risk
- technology_landscape_mapping_PTAB: Technology landscape competitive intelligence
- document_filtering_assistant: Purpose-driven document filtering
- patent_explanation_for_attorneys: Attorney-friendly patent explanations
- prior_art_analysis_CITATION: Citation-enhanced prior art analysis
- examiner_behavior_intelligence_CITATION: Examiner citation behavior intelligence
- patent_invalidity_analysis_defense_Pinecone_PTAB_FPD_Citations: Multi-MCP patent invalidity defense (PFW+PTAB+FPD+Citations+Pinecone)
"""

import os

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# Registration gate for the prompt templates (same pattern as the
# pfw_manage_users tool gate in tools/admin_tools.py: filtered at
# registration time, never appears in prompts/list). Default OFF.
PROMPTS_ENABLED = (
    os.getenv("PFW_ENABLE_PROMPTS", "false").lower() == "true"
)


def register_prompts(mcp_server):
    """Register all prompts with the MCP server.

    This function is called from main.py after the mcp object is created.
    It imports and registers all prompt modules with the server.

    Gated by PFW_ENABLE_PROMPTS (default off): when unset/false, no prompts
    are registered on the server at all.

    Args:
        mcp_server: The FastMCP server instance to register prompts with
    """
    if not PROMPTS_ENABLED:
        logger.info(
            "Prompt templates not registered (PFW_ENABLE_PROMPTS is off; default)."
        )
        return

    # Store mcp server globally for prompt modules to use
    global mcp
    mcp = mcp_server

    # Import all prompt modules to register them with the MCP server.
    # These are intentionally unused at the Python module level — they register
    # themselves with the global `mcp` on import. F401 suppressed intentionally.
    from . import complete_patent_package_retrieval_PTAB_FPD  # noqa: F401
    from . import patent_search  # noqa: F401
    from . import art_unit_quality_assessment_FPD  # noqa: F401
    from . import litigation_research_setup_PTAB_FPD  # noqa: F401
    from . import inventor_portfolio_analysis  # noqa: F401
    from . import technology_landscape_mapping_PTAB  # noqa: F401
    from . import document_filtering_assistant  # noqa: F401
    from . import patent_explanation_for_attorneys  # noqa: F401
    from . import prior_art_analysis_CITATION  # noqa: F401
    from . import examiner_behavior_intelligence_CITATION  # noqa: F401
    from . import patent_invalidity_analysis_defense_Pinecone_PTAB_FPD_Citations  # noqa: F401

__all__ = [
    'register_prompts',
]
