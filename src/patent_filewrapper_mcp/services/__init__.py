"""
Service modules for Patent File Wrapper MCP

This package contains specialized service classes extracted from the 
monolithic EnhancedPatentClient to follow SOLID principles.
"""

from .ocr_service import OCRService

__all__ = ['OCRService']