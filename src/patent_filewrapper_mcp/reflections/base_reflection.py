"""
Base reflection class for USPTO MCP ecosystem guidance

Provides common structure and functionality for all USPTO guidance modules.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime


class BaseReflection(ABC):
    """
    Base class for all USPTO guidance reflections
    
    Features:
    - Structured metadata for resource discovery
    - Consistent formatting for cross-MCP compatibility
    - Version tracking for guidance updates
    - Abstract methods for implementation-specific content
    """
    
    def __init__(self, name: str, description: str, version: str = "1.0"):
        """
        Initialize base reflection
        
        Args:
            name: Human-readable name for this reflection
            description: Brief description of the guidance provided
            version: Version string for tracking updates
        """
        self.name = name
        self.description = description
        self.version = version
        self.created_at = datetime.now().isoformat()
        self.tags = self._get_tags()
        self.mcp_type = self._get_mcp_type()
    
    @abstractmethod
    def _get_tags(self) -> List[str]:
        """
        Get tags for categorizing this reflection
        
        Returns:
            List of descriptive tags for discovery and filtering
        """
        pass
    
    @abstractmethod
    def _get_mcp_type(self) -> str:
        """
        Get the MCP type this reflection belongs to
        
        Returns:
            MCP identifier (e.g., 'pfw', 'fpd', 'ptab')
        """
        pass
    
    @abstractmethod
    def get_content(self) -> str:
        """
        Get the main guidance content as markdown
        
        Returns:
            Formatted markdown content with USPTO guidance
        """
        pass
    
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get reflection metadata for resource discovery
        
        Returns:
            Metadata dictionary with reflection information
        """
        return {
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'created_at': self.created_at,
            'tags': self.tags,
            'mcp_type': self.mcp_type,
            'content_type': 'text/markdown',
            'size_estimate': len(self.get_content()),
            'resource_uri': f"/reflections/{self.mcp_type}/{self.name.lower().replace(' ', '_')}"
        }
    
    def get_summary(self) -> str:
        """
        Get a brief summary of this reflection's content
        
        Returns:
            Concise summary suitable for resource listings
        """
        content = self.get_content()
        
        # Extract first meaningful paragraph
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and len(line) > 50:
                # Truncate to reasonable length
                if len(line) > 200:
                    return line[:197] + "..."
                return line
        
        # Fallback to description
        return self.description
    
    def matches_filter(self, tags: Optional[List[str]] = None, mcp_type: Optional[str] = None) -> bool:
        """
        Check if this reflection matches the given filters
        
        Args:
            tags: Required tags for filtering (any match)
            mcp_type: Required MCP type
            
        Returns:
            True if reflection matches all filters
        """
        if mcp_type and self.mcp_type != mcp_type:
            return False
        
        if tags:
            if not any(tag in self.tags for tag in tags):
                return False
        
        return True
    
    def to_resource_format(self) -> Dict[str, Any]:
        """
        Convert reflection to MCP Resource format
        
        Returns:
            MCP Resource-compatible dictionary
        """
        metadata = self.get_metadata()
        return {
            'uri': metadata['resource_uri'],
            'name': self.name,
            'description': self.description,
            'mimeType': metadata['content_type'],
            'metadata': metadata
        }