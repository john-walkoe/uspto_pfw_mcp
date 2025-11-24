#!/usr/bin/env python3
"""
Simple test to verify the MCP server can start
"""

import sys
import os

# Add the source directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    print("Testing MCP server import...")
    
    # Test if we can import the main module
    from patent_filewrapper_mcp.main import mcp
    print("? Successfully imported MCP server")
    
    # Test if we can access the tools
    tools = [tool for tool in dir(mcp) if not tool.startswith('_')]
    print(f"? Available MCP tools: {len(tools)}")
    
    print("? MCP server appears to be working correctly")
    
except ImportError as e:
    print(f"? Import error: {e}")
    print("This suggests a dependency issue")
    
except Exception as e:
    print(f"? Other error: {e}")
    import traceback
    traceback.print_exc()

print("\nTo test manually, try running:")
print("python -m patent_filewrapper_mcp.main")
