"""Field Configuration Manager for Patent File Wrapper MCP"""

import yaml
import os
import logging
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

class FieldConfigManager:
    """Manages field configuration for patent search functions"""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize with optional custom config path"""
        if config_path is None:
            # Look for field_configs.yaml in project root (3 levels up from this file)
            config_path = Path(__file__).parent.parent.parent.parent / "field_configs.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except (FileNotFoundError, yaml.YAMLError) as e:
            logger.warning(f"Config load failed: {e}. Using defaults.")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration if file not found"""
        return {
            "predefined_sets": {
                "minimal": {
                    "description": "Ultra-minimal fields for 95-99% context reduction",
                    "fields": ["applicationNumberText", "applicationMetaData.inventionTitle"]
                },
                "balanced": {
                    "description": "Key fields for 85-95% context reduction",
                    "fields": [
                        "applicationNumberText", "applicationMetaData.inventionTitle",
                        "applicationMetaData.filingDate", "applicationMetaData.patentNumber",
                        "applicationMetaData.applicationStatusDescriptionText",
                        "parentContinuityBag.parentPatentNumber"
                    ]
                }
            }
        }
    
    def get_field_set(self, set_name: str) -> List[str]:
        """Get fields for a named set (predefined or custom)"""
        # Check predefined sets first
        predefined = self.config.get("predefined_sets", {})
        if set_name in predefined:
            return predefined[set_name]["fields"]
        
        # Check custom sets
        custom = self.config.get("custom_sets", {})
        if set_name in custom:
            return custom[set_name]["fields"]
        
        # Fallback to minimal if not found
        logger.warning(f"Field set '{set_name}' not found, using minimal")
        return self.get_field_set("minimal")
    
    def validate_fields(self, fields: List[str]) -> Tuple[List[str], List[str]]:
        """Validate fields against known USPTO API fields
        
        Returns:
            tuple: (valid_fields, invalid_fields)
        """
        from ..api.helpers import map_user_fields_to_api_fields
        
        valid_fields = []
        invalid_fields = []
        
        # Use existing field mapping for validation
        mapped_fields = map_user_fields_to_api_fields(fields)
        
        for original, mapped in zip(fields, mapped_fields):
            if mapped != original or self._is_known_api_field(mapped):
                valid_fields.append(mapped)
            else:
                invalid_fields.append(original)
        
        return valid_fields, invalid_fields
    
    def _is_known_api_field(self, field: str) -> bool:
        """Check if field is a known USPTO API field"""
        # Basic validation - could be enhanced with comprehensive field list
        known_prefixes = [
            "applicationNumberText",
            "applicationMetaData.",
            "parentContinuityBag.",
            "childContinuityBag.",
            "termAdjustmentBag",
            "transactionBag",
            "assignmentBag",
            "documentBag"
        ]
        return any(field.startswith(prefix) for prefix in known_prefixes)
    
    def get_available_sets(self) -> Dict[str, str]:
        """Get all available field sets with descriptions"""
        sets = {}
        
        # Add predefined sets
        for name, config in self.config.get("predefined_sets", {}).items():
            sets[name] = config.get("description", f"Predefined set: {name}")
        
        # Add custom sets  
        for name, config in self.config.get("custom_sets", {}).items():
            sets[name] = config.get("description", f"Custom set: {name}")
        
        return sets
    
    def add_custom_set(self, name: str, fields: List[str], description: str = "") -> bool:
        """Add a new custom field set to configuration"""
        try:
            valid_fields, invalid_fields = self.validate_fields(fields)
            
            if invalid_fields:
                logger.warning(f"Invalid fields in custom set: {invalid_fields}")
                return False
            
            if "custom_sets" not in self.config:
                self.config["custom_sets"] = {}
            
            self.config["custom_sets"][name] = {
                "description": description or f"Custom field set: {name}",
                "fields": valid_fields
            }
            
            # Save back to file
            return self.save_config()
            
        except Exception as e:
            logger.error(f"Failed to add custom set: {e}")
            return False
    
    def save_config(self) -> bool:
        """Save configuration back to YAML file"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, indent=2, default_flow_style=False)
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def get_field_categories(self) -> Dict[str, List[str]]:
        """Get field categories for organization"""
        return self.config.get("field_categories", {})
    
    def get_usage_instructions(self) -> Dict[str, str]:
        """Get usage instructions for the configuration system"""
        return self.config.get("usage_instructions", {})

    def reload_config(self) -> bool:
        """Reload configuration from YAML file

        This allows updating field configurations without restarting the server.
        Call this after editing field_configs.yaml to apply changes.

        Returns:
            bool: True if reload successful, False otherwise
        """
        try:
            self.config = self._load_config()
            logger.info(f"Configuration reloaded successfully from {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")
            return False

# Global instance for use across the application
field_manager = FieldConfigManager()