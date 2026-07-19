"""
Modular reflection system for USPTO MCP ecosystem

This package provides structured USPTO guidance as both MCP Resources
and traditional tool reflections for enhanced client compatibility.
"""

from .base_reflection import BaseReflection
from .reflection_manager import ReflectionManager

__all__ = ['BaseReflection', 'ReflectionManager']
