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

def register_prompts(mcp_server):
    """Register all prompts with the MCP server.

    This function is called from main.py after the mcp object is created.
    It imports and registers all prompt modules with the server.

    Args:
        mcp_server: The FastMCP server instance to register prompts with
    """
    # Store mcp server globally for prompt modules to use
    global mcp
    mcp = mcp_server

    # Import all prompt modules to register them with the MCP server
    from . import complete_patent_package_retrieval_PTAB_FPD
    from . import patent_search
    from . import art_unit_quality_assessment_FPD
    from . import litigation_research_setup_PTAB_FPD
    from . import inventor_portfolio_analysis
    from . import technology_landscape_mapping_PTAB
    from . import document_filtering_assistant
    from . import patent_explanation_for_attorneys
    from . import prior_art_analysis_CITATION
    from . import examiner_behavior_intelligence_CITATION
    from . import patent_invalidity_analysis_defense_Pinecone_PTAB_FPD_Citations

__all__ = [
    'register_prompts',
]
