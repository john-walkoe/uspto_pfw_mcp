"""
Pydantic models for proxy server request/response validation
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class FPDDocumentRegistration(BaseModel):
    """
    FPD document registration request model

    Used by FPD MCP to register documents with PFW centralized proxy
    """
    source: str = Field(
        ...,
        description="Source MCP identifier (should be 'fpd')",
        pattern="^fpd$"
    )
    petition_id: str = Field(
        ...,
        description="UUID of the petition",
        min_length=36,
        max_length=36
    )
    document_identifier: str = Field(
        ...,
        description="Document identifier from FPD",
        min_length=1,
        max_length=100
    )
    download_url: str = Field(
        ...,
        description="Full USPTO API download URL",
        min_length=10,
        max_length=2000
    )
    access_token: str = Field(
        ...,
        description="Secure access token for authentication (replaces direct API key)",
        min_length=10,
        max_length=1000
    )
    application_number: Optional[str] = Field(
        None,
        description="Optional application number for cross-reference",
        max_length=20
    )
    enhanced_filename: Optional[str] = Field(
        None,
        description="Enhanced human-readable filename for document downloads (e.g., PET-2025-09-03_APP-18462633_DECISION.pdf)",
        max_length=255
    )

    @field_validator('enhanced_filename')
    @classmethod
    def validate_filename(cls, v: Optional[str]) -> Optional[str]:
        """Validate enhanced filename format and safety"""
        if v is None:
            return None

        # Must end with .pdf
        if not v.endswith('.pdf'):
            raise ValueError('Filename must end with .pdf')

        # Check length
        if len(v) > 255:
            raise ValueError('Filename too long (max 255 chars)')

        # Safe characters only: uppercase letters, numbers, underscores, hyphens, dots
        import re
        if not re.match(r'^[A-Z0-9_.-]+\.pdf$', v):
            raise ValueError('Filename contains invalid characters. Only A-Z, 0-9, _, -, and . are allowed')

        return v

    @field_validator('download_url')
    @classmethod
    def validate_download_url(cls, v: str) -> str:
        """Validate download URL is a proper USPTO API endpoint"""
        if not v.startswith('https://'):
            raise ValueError('Download URL must use HTTPS')
        if 'api.uspto.gov' not in v and 'uspto.gov' not in v:
            raise ValueError('Download URL must be from uspto.gov domain')
        return v

    @field_validator('petition_id')
    @classmethod
    def validate_petition_id(cls, v: str) -> str:
        """Validate petition ID is a valid UUID format"""
        import re
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, v.lower()):
            raise ValueError('Petition ID must be a valid UUID')
        return v.lower()


class FPDDocumentRegistrationResponse(BaseModel):
    """Response model for FPD document registration"""
    success: bool
    message: str
    petition_id: Optional[str] = None
    document_identifier: Optional[str] = None
    download_url: Optional[str] = None


class PTABDocumentRegistration(BaseModel):
    """
    PTAB document registration request model

    Used by future PTAB MCP to register documents with PFW centralized proxy
    when PTAB moves to USPTO Open Data Portal
    """
    source: str = Field(
        ...,
        description="Source MCP identifier (should be 'ptab')",
        pattern="^ptab$"
    )
    proceeding_number: str = Field(
        ...,
        description="PTAB proceeding number (AIA Trials: IPR2025-00895, PGR2025-00456; Appeals: 2025000950)",
        min_length=10,
        max_length=15
    )
    document_identifier: str = Field(
        ...,
        description="Document identifier from PTAB API",
        min_length=1,
        max_length=100
    )
    download_url: str = Field(
        ...,
        description="Full USPTO API download URL",
        min_length=10,
        max_length=2000
    )
    access_token: str = Field(
        ...,
        description="Secure access token for authentication (replaces direct API key)",
        min_length=10,
        max_length=1000
    )
    patent_number: Optional[str] = Field(
        None,
        description="Patent number being challenged (for cross-reference)",
        max_length=20
    )
    application_number: Optional[str] = Field(
        None,
        description="Application number (for PFW cross-reference)",
        max_length=20
    )
    proceeding_type: Optional[str] = Field(
        None,
        description="Type of PTAB proceeding (IPR, PGR, CBM, DER for AIA Trials; Appeal for Appeals)",
        pattern="^(IPR|PGR|CBM|DER|Appeal)$"
    )
    document_type: Optional[str] = Field(
        None,
        description="Type of document (petition, response, decision, etc.)",
        max_length=50
    )
    enhanced_filename: Optional[str] = Field(
        None,
        description="Enhanced human-readable filename for document downloads (e.g., PTAB-2024-05-15_IPR2024-00123_PAT-8524787_DECISION.pdf)",
        max_length=255
    )

    @field_validator('enhanced_filename')
    @classmethod
    def validate_filename(cls, v: Optional[str]) -> Optional[str]:
        """Validate enhanced filename format and safety"""
        if v is None:
            return None

        # Must end with .pdf
        if not v.endswith('.pdf'):
            raise ValueError('Filename must end with .pdf')

        # Check length
        if len(v) > 255:
            raise ValueError('Filename too long (max 255 chars)')

        # Safe characters only: uppercase letters, numbers, underscores, hyphens, dots
        import re
        if not re.match(r'^[A-Z0-9_.-]+\.pdf$', v):
            raise ValueError('Filename contains invalid characters. Only A-Z, 0-9, _, -, and . are allowed')

        return v

    @field_validator('download_url')
    @classmethod
    def validate_download_url(cls, v: str) -> str:
        """Validate download URL is a proper USPTO API endpoint"""
        if not v.startswith('https://'):
            raise ValueError('Download URL must use HTTPS')
        if 'api.uspto.gov' not in v and 'uspto.gov' not in v:
            raise ValueError('Download URL must be from uspto.gov domain')
        return v

    @field_validator('proceeding_number')
    @classmethod
    def validate_proceeding_number(cls, v: str) -> str:
        """Validate PTAB proceeding number format"""
        import re

        # AIA Trials: TYPE[4-digit-year]-[5-digit-number]
        aia_trial_pattern = r'^(IPR|PGR|CBM|DER)\d{4}-\d{5}$'
        if re.match(aia_trial_pattern, v.upper()):
            return v.upper()

        # Appeals: 10-digit numeric (e.g., 2025000950)
        appeal_pattern = r'^\d{10}$'
        if re.match(appeal_pattern, v):
            return v  # Keep numeric format as-is

        raise ValueError('Proceeding number must match format: AIA Trials (IPR2025-00895, PGR2025-00456) or Appeals (2025000950)')


class PTABDocumentRegistrationResponse(BaseModel):
    """Response model for PTAB document registration"""
    success: bool
    message: str
    proceeding_number: Optional[str] = None
    document_identifier: Optional[str] = None
    download_url: Optional[str] = None
