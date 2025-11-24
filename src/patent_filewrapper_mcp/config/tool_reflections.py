"""
Tool reflections for USPTO Patent File Wrapper MCP Server

MIGRATION NOTICE: The comprehensive tool reflection functionality has been migrated 
to a more efficient sectioned guidance approach using pfw_get_guidance().

For tool guidance, use: pfw_get_guidance(section='tools')
For workflows, use: pfw_get_guidance(section='workflows_pfw') 
For field strategies, use: pfw_get_guidance(section='fields')
For error troubleshooting, use: pfw_get_guidance(section='errors')

This provides context-efficient access to the same comprehensive guidance content
with 95% token reduction (1-12KB vs 62KB) while maintaining full functionality.
"""

# DEPRECATED: Moved to pfw_get_guidance() for context efficiency
# The large function get_all_tool_reflections() has been removed
# Use pfw_get_guidance(section='overview') to see available sections

# DEPRECATED: Moved to pfw_get_guidance() for context efficiency  
# The function get_tool_reflection() has been removed
# Use pfw_get_guidance(section='tools') for tool-specific guidance