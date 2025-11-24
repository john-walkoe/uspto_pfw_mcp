"""
Reflection manager for coordinating USPTO MCP guidance across the ecosystem

Provides unified access to all USPTO guidance content as both traditional
tool reflections and modern MCP Resources for optimal client compatibility.
"""

import logging
from typing import Dict, List, Optional, Any
from .base_reflection import BaseReflection
from .pfw_reflections import PFWReflection

logger = logging.getLogger(__name__)


class ReflectionManager:
    """
    Central manager for all USPTO MCP reflections

    Features:
    - Unified access to all USPTO guidance
    - MCP Resources capability for advanced clients
    - Traditional tool reflection fallback
    - Cross-MCP integration support
    - Efficient content caching and delivery
    """

    def __init__(self):
        """Initialize reflection manager with all available reflections"""
        self._reflections: Dict[str, BaseReflection] = {}
        self._load_reflections()

    def _load_reflections(self):
        """Load all available reflections"""
        try:
            # Load PFW reflections
            pfw_reflection = PFWReflection()
            self._reflections[pfw_reflection.name.lower().replace(' ', '_')] = pfw_reflection

            logger.info(f"Loaded {len(self._reflections)} USPTO MCP reflections")

        except Exception as e:
            logger.error(f"Error loading reflections: {e}")

    def list_resources(self, mcp_type: Optional[str] = None, tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        List available resources for MCP Resources capability

        Args:
            mcp_type: Filter by MCP type (pfw, fpd, ptab)
            tags: Filter by tags (any match)

        Returns:
            List of MCP Resource-compatible dictionaries
        """
        resources = []

        for reflection in self._reflections.values():
            if reflection.matches_filter(tags=tags, mcp_type=mcp_type):
                resources.append(reflection.to_resource_format())

        # Sort by MCP type and name for consistent ordering
        resources.sort(key=lambda r: (r['metadata']['mcp_type'], r['name']))

        return resources

    def get_resource(self, resource_path: str) -> Optional[str]:
        """
        Get specific resource content for MCP Resources capability

        Args:
            resource_path: Resource path (e.g., "/reflections/pfw/tool_guidance")

        Returns:
            Resource content as markdown, or None if not found
        """
        # Parse resource path
        if not resource_path.startswith('/reflections/'):
            return None

        path_parts = resource_path[13:].split('/')  # Remove '/reflections/'
        if len(path_parts) < 2:
            return None

        mcp_type = path_parts[0]
        resource_name = path_parts[1]

        # Find matching reflection
        for reflection in self._reflections.values():
            if (reflection.mcp_type == mcp_type and
                reflection.name.lower().replace(' ', '_') == resource_name):
                return reflection.get_content()

        return None

    def get_reflection_by_name(self, name: str) -> Optional[BaseReflection]:
        """
        Get reflection by name for traditional tool reflection access

        Args:
            name: Reflection name (case-insensitive)

        Returns:
            BaseReflection instance or None if not found
        """
        normalized_name = name.lower().replace(' ', '_')
        return self._reflections.get(normalized_name)

    # DEPRECATED: Tool reflection methods have been removed
    # These methods were used for legacy comprehensive guidance delivery (62KB)
    #
    # MIGRATION: Use the new pfw_get_guidance() function instead for context-efficient
    # sectioned guidance (1-12KB per section vs 62KB total)
    #
    # MCP Resources implementation (above methods) remains active and functional

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about available reflections

        Returns:
            Statistics dictionary for monitoring
        """
        stats = {
            'total_reflections': len(self._reflections),
            'by_mcp_type': {},
            'total_content_size': 0,
            'available_tags': set()
        }

        for reflection in self._reflections.values():
            # Count by MCP type
            mcp_type = reflection.mcp_type
            stats['by_mcp_type'][mcp_type] = stats['by_mcp_type'].get(mcp_type, 0) + 1

            # Sum content size
            stats['total_content_size'] += len(reflection.get_content())

            # Collect tags
            stats['available_tags'].update(reflection.tags)

        # Convert set to sorted list
        stats['available_tags'] = sorted(list(stats['available_tags']))

        return stats


# Global reflection manager instance
_reflection_manager = None

def get_reflection_manager() -> ReflectionManager:
    """Get global reflection manager instance"""
    global _reflection_manager
    if _reflection_manager is None:
        _reflection_manager = ReflectionManager()
    return _reflection_manager
