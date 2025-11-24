"""
Patent File Wrapper MCP reflections

Contains comprehensive guidance for USPTO Patent File Wrapper API tools,
workflows, and attorney-specific use cases.
"""

from typing import List
from .base_reflection import BaseReflection


class PFWReflection(BaseReflection):
    """
    Patent File Wrapper MCP guidance reflection

    Provides comprehensive guidance for PFW tools including:
    - Progressive disclosure workflow (minimal → balanced → detailed)
    - Field customization and context reduction strategies
    - Document selection and extraction patterns
    - Cross-MCP integration workflows
    - Attorney-specific use cases and cost optimization
    """

    def __init__(self):
        super().__init__(
            name="USPTO PFW Tool Guidance",
            description="Comprehensive Patent File Wrapper MCP guidance covering progressive workflows, field customization, document extraction, and cross-MCP integration patterns",
            version="3.0"
        )

    def _get_tags(self) -> List[str]:
        """Get PFW-specific tags for categorization"""
        return [
            'patent-prosecution',
            'document-extraction',
            'field-customization',
            'progressive-disclosure',
            'context-reduction',
            'workflow-guidance',
            'attorney-tools',
            'api-optimization',
            'cross-mcp-integration',
            'cost-optimization'
        ]

    def _get_mcp_type(self) -> str:
        """Get MCP type identifier"""
        return 'pfw'

    def get_content(self) -> str:
        """
        Get the complete PFW guidance content

        Returns:
            Full PFW guidance as markdown (61K+ characters)
        """
        # UPDATED: Use the new comprehensive guidance content
        # This provides the complete guidance that was previously in get_all_tool_reflections()
        # but now sourced from the sectioned guidance system
        return self._get_comprehensive_guidance()

    def get_quick_reference(self) -> str:
        """
        Get a quick reference version for resource-constrained clients

        Returns:
            Condensed guidance focusing on essential workflows
        """
        return """# USPTO PFW MCP - Quick Reference

## Essential Workflow Patterns

### 1. Progressive Disclosure Strategy
- **Minimal Search** → Discovery (20-50 results OR 50-200 ultra-minimal with custom fields)
- **Balanced Search** → Analysis (5-20 results)
- **Custom Fields** → Targeted extraction (2-3 fields for 99% reduction)

### 2. Document Access Patterns
- **Proxy Downloads** → Browser-accessible PDFs
- **Content Extraction** → Text analysis (PyPDF2 + Mistral OCR)
- **Persistent Links** → 7-day encrypted access

### 3. Context Reduction Techniques
- Use minimal searches for discovery (95% context reduction)
- Customize fields via field_configs.yaml
- Leverage cross-MCP integration for comprehensive analysis

### 4. Key Tools by Use Case
- **Discovery**: `pfw_search_applications_minimal`
- **Analysis**: `pfw_search_applications_balanced`
- **Documents**: `pfw_get_application_documents`
- **Downloads**: `pfw_get_document_download`
- **Content**: `pfw_get_document_content`

### 5. Cross-MCP Integration
- **FPD**: Check petition history for prosecution quality
- **PTAB**: Verify trial proceedings impact
- **Pinecone Assistant MCP**: Access MPEP knowledge base with AI-powered chat (`assistant_context`, `assistant_strategic_multi_search_context`)
- **Pinecone RAG MCP**: Access MPEP knowledge base with custom embeddings (`semantic_search`, `strategic_semantic_search`)

For complete guidance, use the full tool reflections resource."""

    def _get_comprehensive_guidance(self) -> str:
        """
        Get comprehensive guidance content from all sections combined

        Returns:
            Complete PFW guidance combining all sections
        """
        # This reconstructs the comprehensive guidance by combining all sections
        # from the new pfw_get_guidance system
        sections_content = []

        # Add header
        sections_content.append("# USPTO Patent File Wrapper MCP Server - Complete Tool Guidance")
        sections_content.append("")
        sections_content.append("**Version:** 3.0")
        sections_content.append("**Last Updated:** 2025-11-09")
        sections_content.append("")
        sections_content.append("Comprehensive guidance for Patent File Wrapper, cross-MCP workflows, and patent attorney use cases.")
        sections_content.append("")

        # Note: The full content is now delivered through pfw_get_guidance() sections
        # for context efficiency. This method provides a comprehensive overview.
        overview_content = """
## Migration Notice

This comprehensive guidance has been migrated to a context-efficient sectioned approach using `pfw_get_guidance()`.

### Available Sections:
- **overview**: Available sections and tool summary
- **workflows_pfw**: PFW-only workflows (litigation, due diligence, prior art)
- **workflows_ptab**: PFW + PTAB integration workflows
- **workflows_fpd**: PFW + FPD integration workflows
- **workflows_citations**: PFW + Citations integration workflows
- **workflows_complete**: Four-MCP complete lifecycle analysis
- **documents**: Document downloads, codes, and selection guidance
- **fields**: Field selection strategies and context reduction
- **tools**: Tool-specific guidance and parameters
- **errors**: Common error patterns and troubleshooting
- **advanced**: Advanced workflows and optimization
- **cost**: Cost optimization strategies

### Usage:
```python
# Get specific section (1-12K chars vs 62K total)
guidance = pfw_get_guidance(section='tools')

# Quick reference chart
guidance = pfw_get_guidance(section='overview')
```

### Key Benefits:
- **95% context reduction** (1-12KB per section vs 62KB total)
- **Targeted guidance** for specific workflows
- **Same comprehensive content** organized for efficiency
- **Backwards compatible** with MCP Resources

For complete guidance access, use the `pfw_get_guidance(section='...')` function with specific section names listed above.
"""

        sections_content.append(overview_content)
        return '\n'.join(sections_content)

    def get_tool_specific_guidance(self, tool_name: str) -> str:
        """
        Get guidance for a specific tool

        Args:
            tool_name: Name of the specific tool

        Returns:
            Tool-specific guidance or general guidance if tool not found
        """
        # UPDATED: Direct tool-specific guidance for common tools
        # Use the new sectioned approach instead of deleted function
        return f"""# Tool Guidance: {tool_name}

## Migration Notice
Tool-specific guidance has been migrated to the new sectioned approach.

**To get detailed guidance for this tool:**
```python
# Get comprehensive tool guidance
guidance = pfw_get_guidance(section='tools')

# Get workflow guidance
guidance = pfw_get_guidance(section='workflows_pfw')

# Get field strategies
guidance = pfw_get_guidance(section='fields')
```

**Quick Reference:**
- Use `pfw_get_guidance(section='overview')` to see all available sections
- Use `pfw_get_guidance(section='tools')` for detailed tool guidance
- Use `pfw_get_guidance(section='errors')` for troubleshooting

The new sectioned approach provides the same comprehensive guidance with 95% context reduction (1-12KB per section vs 62KB total).
"""
