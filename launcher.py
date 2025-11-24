"""
Standalone MCP server launcher for Patent File Wrapper

This script can be used as an alternative entry point for the MCP server
if there are issues with the module-based approach.
"""

import sys
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add the source directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

def main():
    """Main entry point for standalone launcher"""
    try:
        logger.info("Loading Patent File Wrapper MCP...")
        
        # Import and run the MCP server
        from patent_filewrapper_mcp.main import mcp
        
        logger.info("Starting MCP server...")
        mcp.run()
        
    except ImportError as e:
        logger.error(f"Failed to import MCP module: {e}")
        logger.error("Make sure all dependencies are installed:")
        logger.error("pip install -e .")
        sys.exit(1)
        
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
