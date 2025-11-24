"""
Helper functions for Patent File Wrapper MCP
"""
import re
import logging
import uuid
from typing import Dict, Any, List, Optional

from ..exceptions import ValidationError
from .field_constants import USPTOFields, QueryFieldNames

logger = logging.getLogger(__name__)

def validate_app_number(app_number: str) -> str:
    """
    Validate and normalize application number
    
    Args:
        app_number: Raw application number
        
    Returns:
        Normalized application number
        
    Raises:
        ValidationError: If application number is invalid
    """
    if not app_number:
        raise ValidationError("Application number cannot be empty")
        
    # Remove common prefixes and clean up
    app_number = str(app_number).strip()
    app_number = re.sub(r'^(US|us)', '', app_number)
    app_number = re.sub(r'[^\d]', '', app_number)  # Keep only digits
    
    if not app_number:
        raise ValidationError("Application number must contain digits")
        
    if len(app_number) < 6:
        raise ValidationError("Application number too short")
        
    return app_number


def escape_lucene_query_term(term: str) -> str:
    """
    Escape special characters for Lucene query terms to prevent query injection.

    Lucene query syntax characters: + - && || ! ( ) { } [ ] ^ ~ * ? : " \

    Characters NOT escaped (safe in value positions):
    - Colon (:) - Used for field:value syntax. User input only in VALUE positions.
    - Quotes (") - We add quotes externally for phrase queries. Escaping would break them.
    - Brackets [, ] - Used for range queries. Safe in values (e.g., dates).
    - Dash (-) - Used in dates and ranges. Safe in values (e.g., "2024-01-01").
    - Asterisk (*) - Wildcard operator. If user wants wildcard, it's intentional.
    - Question mark (?) - Single-char wildcard. If user wants it, it's intentional.

    Args:
        term: User input term to be used in a Lucene query VALUE (not field name)

    Returns:
        Escaped term safe for use in Lucene queries
    """
    if not term:
        return term

    # Escape Lucene special characters by prefixing with backslash
    # Note: Backslash itself needs to be escaped first
    # Many characters are NOT escaped because they're legitimate query syntax or safe in values
    specials = r'[\\\+&|\!\(\)\{\}\^~]'
    escaped = re.sub(specials, lambda m: '\\' + m.group(0), str(term))

    # Additional validation - limit length to prevent DoS
    if len(escaped) > 1000:
        raise ValidationError(f"Query term too long after escaping: {len(escaped)} characters")

    return escaped


def sanitize_traceback(tb_str: str) -> str:
    """
    Remove sensitive information from tracebacks

    Sanitizes:
    - File paths (replaces usernames)
    - API keys and tokens
    - Environment variables that might contain secrets

    Args:
        tb_str: Original traceback string

    Returns:
        Sanitized traceback safe for logging
    """
    import re
    import os

    # Remove file paths - replace username
    tb_str = re.sub(r'/home/[^/]+/', '/home/USER/', tb_str)
    tb_str = re.sub(r'/Users/[^/]+/', '/Users/USER/', tb_str)
    tb_str = re.sub(r'C:\\Users\\[^\\]+\\', r'C:\\Users\\USER\\', tb_str)

    # Remove API keys (pattern: key=value with alphanumeric)
    tb_str = re.sub(
        r'(api[_-]?key|token|password|secret|auth)[=\s:][\'"]?[\w-]+',
        r'\1=***REDACTED***',
        tb_str,
        flags=re.IGNORECASE
    )

    # Remove environment variables that might contain keys
    tb_str = re.sub(
        r'(USPTO_API_KEY|MISTRAL_API_KEY|API_KEY)[=\s:][\'"]?[^\s\'",]+',
        r'\1=***REDACTED***',
        tb_str
    )

    return tb_str


def format_error_response(
    message: str,
    status_code: int = 500,
    request_id: Optional[str] = None,
    error_type: Optional[str] = None,
    actionable_guidance: Optional[str] = None,
    exception: Optional[Exception] = None
) -> Dict[str, Any]:
    """
    Format a consistent error response with environment-aware detail levels

    Provides different detail levels for development vs production:
    - Production: User-friendly message, guidance, request ID
    - Development: Same + exception details, sanitized traceback

    Args:
        message: Error message
        status_code: HTTP-style status code for error categorization
        request_id: Optional request ID for tracing
        error_type: Optional error type categorization
        actionable_guidance: Optional guidance on how to resolve the error
        exception: Optional exception for debug information (dev only)

    Returns:
        Formatted error response with enhanced metadata
    """
    import os

    if request_id is None:
        request_id = generate_request_id()

    response = {
        "error": True,
        "success": False,
        "status_code": status_code,
        "message": message,
        "request_id": request_id,
        "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
    }

    if error_type:
        response["error_type"] = error_type

    if actionable_guidance:
        response["guidance"] = actionable_guidance

    # Add debug info only in development
    is_development = os.getenv("ENVIRONMENT", "production").lower() in ["development", "dev", "local"]

    if is_development and exception:
        import traceback
        tb_str = traceback.format_exc()
        sanitized_tb = sanitize_traceback(tb_str)

        response["debug"] = {
            "exception_type": type(exception).__name__,
            "exception_args": str(exception.args),
            "traceback": sanitized_tb
        }

    return response


def import_time():
    """Import time module to avoid circular imports"""
    import time
    return time


# Error message templates with actionable guidance
ERROR_TEMPLATES = {
    "invalid_app_number": {
        "message": "Invalid application number format",
        "guidance": "Application numbers should be 6+ digits (e.g., '17896175'). Remove any prefixes like 'US'."
    },
    "query_too_long": {
        "message": "Search query exceeds maximum length",
        "guidance": "Simplify your search query or use more specific terms. Consider using convenience parameters instead."
    },
    "invalid_limit": {
        "message": "Invalid limit parameter",
        "guidance": "Limit must be between 1 and 500. Use smaller values for faster responses."
    },
    "invalid_offset": {
        "message": "Invalid offset parameter", 
        "guidance": "Offset must be non-negative. Start with offset=0 for the first page of results."
    },
    "empty_query": {
        "message": "No search criteria provided",
        "guidance": "Provide either a 'query' parameter or at least one convenience parameter (art_unit, examiner_name, etc.)"
    },
    "api_auth_failed": {
        "message": "USPTO API authentication failed",
        "guidance": "Check your USPTO_API_KEY environment variable. Get a free API key from developer.uspto.gov"
    },
    "api_timeout": {
        "message": "USPTO API request timed out",
        "guidance": "Try again with a smaller limit or simpler query. The USPTO API may be experiencing high load."
    },
    "invalid_inventor_name": {
        "message": "Invalid inventor name",
        "guidance": "Inventor name cannot be empty and must be under 100 characters. Use format: 'Last, First' or 'First Last'."
    },
    "invalid_strategy": {
        "message": "Invalid search strategy",
        "guidance": "Strategy must be 'exact', 'fuzzy', or 'comprehensive'. Use 'comprehensive' for best results."
    },
    "rate_limit_exceeded": {
        "message": "Rate limit exceeded",
        "guidance": "Wait before making another request. USPTO allows 5 downloads per 10 seconds."
    },
    "document_not_found": {
        "message": "Document not found",
        "guidance": "Verify the application number and document identifier. The document may not be publicly available."
    }
}


def create_error_response(error_key: str, custom_message: Optional[str] = None, 
                         status_code: int = 400, request_id: Optional[str] = None, 
                         additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create standardized error response using predefined templates
    
    Args:
        error_key: Key for error template
        custom_message: Optional custom message to override template
        status_code: HTTP-style status code
        request_id: Request ID for tracing
        additional_context: Additional context to include in error
        
    Returns:
        Formatted error response with guidance
    """
    template = ERROR_TEMPLATES.get(error_key, {
        "message": "An error occurred",
        "guidance": "Please check your request parameters and try again."
    })
    
    message = custom_message or template["message"]
    guidance = template.get("guidance")
    
    response = format_error_response(
        message=message,
        status_code=status_code,
        request_id=request_id,
        error_type=error_key,
        actionable_guidance=guidance
    )
    
    if additional_context:
        response.update(additional_context)
        
    return response

def generate_request_id() -> str:
    """Generate a unique request ID for tracing"""
    return str(uuid.uuid4())[:8]  # Short UUID for readability

def create_inventor_queries(name: str, strategy: str = "comprehensive") -> List[str]:
    """
    Create multiple search queries for inventor name using Patent File Wrapper API fields
    
    Args:
        name: Inventor name
        strategy: Search strategy
        
    Returns:
        List of search queries to try
    """
    queries = []
    
    # Clean up the name and escape it for Lucene queries
    clean_name = name.strip()
    escaped_name = escape_lucene_query_term(clean_name)
    
    if strategy == "exact":
        queries = [
            f'{USPTOFields.INVENTOR_NAME_TEXT}:"{escaped_name}"',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:"{escaped_name}"'
        ]
    elif strategy == "fuzzy":
        # Create variations
        name_parts = clean_name.split()
        escaped_parts = [escape_lucene_query_term(part) for part in name_parts]

        queries = [
            f'{USPTOFields.INVENTOR_NAME_TEXT}:{escaped_name}',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:{escaped_name}',
        ]

        # Add wildcard variations
        if len(escaped_parts) >= 2:
            queries.extend([
                f'{USPTOFields.INVENTOR_NAME_TEXT}:{escaped_parts[0]}* AND {escaped_parts[-1]}*',
                f'{USPTOFields.INVENTOR_NAME_TEXT}:({" OR ".join(escaped_parts)})',
            ])

    else:  # comprehensive
        name_parts = clean_name.split()
        escaped_parts = [escape_lucene_query_term(part) for part in name_parts]

        queries = [
            # Exact matches with quotes
            f'{USPTOFields.INVENTOR_NAME_TEXT}:"{escaped_name}"',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:"{escaped_name}"',

            # Partial matches without quotes
            f'{USPTOFields.INVENTOR_NAME_TEXT}:{escaped_name}',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:{escaped_name}',
        ]

        # Add name variations
        if len(escaped_parts) >= 2:
            first_name = escaped_parts[0]
            last_name = escaped_parts[-1]

            # Try different name orders and combinations
            queries.extend([
                f'{USPTOFields.INVENTOR_NAME_TEXT}:{first_name}* AND {last_name}*',
                f'{USPTOFields.INVENTOR_NAME_TEXT}:"{first_name} {last_name}"',
                f'{USPTOFields.FIRST_INVENTOR_NAME}:"{first_name} {last_name}"',
                f'{USPTOFields.INVENTOR_NAME_TEXT}:{last_name}* AND {first_name}*',
            ])

            # Add middle initial variations if there are 3+ parts
            if len(name_parts) >= 3:
                middle = name_parts[1]
                queries.extend([
                    f'{USPTOFields.INVENTOR_NAME_TEXT}:"{first_name} {middle} {last_name}"',
                    f'{USPTOFields.INVENTOR_NAME_TEXT}:"{first_name} {middle[0]}. {last_name}"',
                ])

        # Add wildcard searches
        if clean_name:
            queries.append(f'{USPTOFields.INVENTOR_NAME_TEXT}:{clean_name}*')
            
    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique_queries.append(query)
            
    return unique_queries[:10]  # Limit to first 10 queries

def format_application_summary(app_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format application data into a readable summary for Patent File Wrapper data
    
    Args:
        app_data: Raw application data from Patent File Wrapper API
        
    Returns:
        Formatted summary
    """
    try:
        metadata = app_data.get('applicationMetaData', {})
        
        summary = {
            "application_number": app_data.get('applicationNumberText', 'N/A'),
            "patent_number": metadata.get('patentNumber', 'N/A'),
            "title": metadata.get('inventionTitle', 'N/A'),
            "filing_date": metadata.get('filingDate', 'N/A'),
            "grant_date": metadata.get('grantDate', 'N/A'),
            "status": metadata.get('applicationStatusDescriptionText', 'N/A'),
            "status_code": metadata.get('applicationStatusCode', 'N/A'),
            "first_inventor": metadata.get('firstInventorName', 'N/A'),
            "inventors": [],
            "applicants": [],
            "classification": {
                "uspc": metadata.get('uspcSymbolText', 'N/A'),
                "cpc": metadata.get('cpcClassificationBag', [])
            },
            "entity_status": metadata.get('entityStatusData', {}).get('businessEntityStatusCategory', 'N/A'),
            "customer_number": metadata.get('customerNumber', 'N/A'),
            "examiner": metadata.get('examinerNameText', 'N/A'),
            "group_art_unit": metadata.get('groupArtUnitNumber', 'N/A')
        }
        
        # Extract inventors
        inventor_bag = metadata.get('inventorBag', [])
        for inventor in inventor_bag:
            if isinstance(inventor, dict):
                name = inventor.get('inventorNameText', 'N/A')
                summary["inventors"].append(name)
                
        # Extract applicants
        applicant_bag = metadata.get('applicantBag', [])
        for applicant in applicant_bag:
            if isinstance(applicant, dict):
                name = applicant.get('applicantNameText', 'N/A')
                summary["applicants"].append(name)
                
        # Add publication info if available
        if metadata.get('publicationDateBag'):
            summary["publication_date"] = metadata.get('publicationDateBag', [])[0] if metadata.get('publicationDateBag') else 'N/A'
            summary["publication_number"] = metadata.get('earliestPublicationNumber', 'N/A')
            
        return summary
        
    except Exception as e:
        logger.warning(f"Error formatting application summary: {e}")
        return {"error": f"Failed to format summary: {str(e)}"}

def extract_patent_families(applications: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group applications by patent family based on continuity data
    
    Args:
        applications: List of application data from Patent File Wrapper API
        
    Returns:
        Dictionary grouped by family ID
    """
    families = {}
    
    for app in applications:
        try:
            # Try to extract family identifier from continuity data
            family_id = None
            
            # Check parent continuity
            parent_continuity = app.get('parentContinuityBag', [])
            if parent_continuity:
                # Use the earliest parent as family root
                family_id = parent_continuity[0].get('parentApplicationNumberText')
                
            # Check child continuity
            if not family_id:
                child_continuity = app.get('childContinuityBag', [])
                if child_continuity:
                    family_id = child_continuity[0].get('childApplicationNumberText')
                    
            # Fall back to application number itself
            if not family_id:
                family_id = app.get('applicationNumberText', 'unknown')
            
            if family_id not in families:
                families[family_id] = []
                
            families[family_id].append(app)
            
        except Exception as e:
            logger.warning(f"Error processing application for family grouping: {e}")
            continue
            
    return families

def format_document_summary(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format document data into a readable summary
    
    Args:
        document: Raw document data from Patent File Wrapper API
        
    Returns:
        Formatted document summary
    """
    try:
        download_options = document.get('downloadOptionBag', [])
        pdf_available = any(opt.get('mimeTypeIdentifier') == 'PDF' for opt in download_options)
        
        summary = {
            "document_code": document.get('documentCode', 'Unknown'),
            "description": document.get('documentCodeDescriptionText', ''),
            "official_date": document.get('officialDate', ''),
            "document_identifier": document.get('documentIdentifier', ''),
            "direction": document.get('directionCategory', ''),
            "pdf_available": pdf_available,
            "total_options": len(download_options),
            "page_count": None
        }
        
        # Get page count from PDF option if available
        for option in download_options:
            if option.get('mimeTypeIdentifier') == 'PDF':
                summary["page_count"] = option.get('pageTotalQuantity', 0)
                break
                
        return summary
        
    except Exception as e:
        logger.warning(f"Error formatting document summary: {e}")
        return {"error": f"Failed to format document summary: {str(e)}"}

def get_query_field_mapping() -> Dict[str, str]:
    """
    Get the mapping of user-friendly field names to USPTO API field names
    for use in both query construction and field selection.

    Returns:
        Dictionary mapping user-friendly names to API field names
    """
    return {
        # Top-level fields (no prefix needed)
        "applicationNumberText": USPTOFields.APPLICATION_NUMBER_TEXT,

        # ApplicationMetaData fields (need applicationMetaData. prefix)
        "inventionTitle": USPTOFields.INVENTION_TITLE,
        "patentNumber": USPTOFields.PATENT_NUMBER,
        "filingDate": USPTOFields.FILING_DATE,
        "grantDate": USPTOFields.GRANT_DATE,
        "applicationStatusDescriptionText": USPTOFields.APPLICATION_STATUS_DESCRIPTION_TEXT,
        "applicationStatusCode": USPTOFields.APPLICATION_STATUS_CODE,
        "firstInventorName": USPTOFields.FIRST_INVENTOR_NAME,
        "examinerNameText": USPTOFields.EXAMINER_NAME_TEXT,
        "groupArtUnitNumber": USPTOFields.GROUP_ART_UNIT_NUMBER,
        "customerNumber": USPTOFields.CUSTOMER_NUMBER,
        "entityStatusData": USPTOFields.ENTITY_STATUS_DATA,
        "inventorBag": USPTOFields.INVENTOR_BAG,
        "applicantBag": USPTOFields.APPLICANT_BAG,
        "assigneeBag": USPTOFields.ASSIGNEE_BAG,
        "uspcSymbolText": USPTOFields.USPC_SYMBOL_TEXT,
        "cpcClassificationBag": USPTOFields.CPC_CLASSIFICATION_BAG,
        "applicationTypeCode": USPTOFields.APPLICATION_TYPE_CODE,
        "applicationTypeLabelName": USPTOFields.APPLICATION_TYPE_LABEL_NAME,
        "earliestPublicationNumber": USPTOFields.EARLIEST_PUBLICATION_NUMBER,
        "publicationDateBag": USPTOFields.PUBLICATION_DATE_BAG,

        # High Priority Fields for Patent Analysis
        "applicationStatusDate": USPTOFields.APPLICATION_STATUS_DATE,
        "firstApplicantName": USPTOFields.FIRST_APPLICANT_NAME,
        "applicationConfirmationNumber": USPTOFields.APPLICATION_CONFIRMATION_NUMBER,
        "docketNumber": USPTOFields.DOCKET_NUMBER,
        "effectiveFilingDate": USPTOFields.EFFECTIVE_FILING_DATE,
        "nationalStageIndicator": USPTOFields.NATIONAL_STAGE_INDICATOR,

        # Medium Priority Fields for Enhanced Analysis
        "earliestPublicationDate": USPTOFields.EARLIEST_PUBLICATION_DATE,
        "firstInventorToFileIndicator": USPTOFields.FIRST_INVENTOR_TO_FILE_INDICATOR,
        "pctPublicationNumber": USPTOFields.PCT_PUBLICATION_NUMBER,
        "pctPublicationDate": USPTOFields.PCT_PUBLICATION_DATE,
        "class": USPTOFields.CLASS,
        "subclass": USPTOFields.SUBCLASS,
        "applicationTypeCategory": USPTOFields.APPLICATION_TYPE_CATEGORY,
        "publicationSequenceNumberBag": USPTOFields.PUBLICATION_SEQUENCE_NUMBER_BAG,
        "publicationCategoryBag": USPTOFields.PUBLICATION_CATEGORY_BAG,
        "internationalRegistrationNumber": USPTOFields.INTERNATIONAL_REGISTRATION_NUMBER,
        "internationalRegistrationPublicationDate": USPTOFields.INTERNATIONAL_REGISTRATION_PUBLICATION_DATE,

        # Parent/Child continuity fields
        "parentPatentNumber": USPTOFields.PARENT_PATENT_NUMBER,
        "parentApplicationNumberText": USPTOFields.PARENT_APPLICATION_NUMBER_TEXT,
        "childApplicationNumberText": USPTOFields.CHILD_APPLICATION_NUMBER_TEXT,

        # Document fields
        "documentBag": USPTOFields.DOCUMENT_BAG,
        "associatedDocuments": USPTOFields.ASSOCIATED_DOCUMENTS,

        # Already prefixed fields (pass through as-is using constants)
        USPTOFields.INVENTION_TITLE: USPTOFields.INVENTION_TITLE,
        USPTOFields.PATENT_NUMBER: USPTOFields.PATENT_NUMBER,
        USPTOFields.FILING_DATE: USPTOFields.FILING_DATE,
        USPTOFields.GRANT_DATE: USPTOFields.GRANT_DATE,
        USPTOFields.APPLICATION_STATUS_DESCRIPTION_TEXT: USPTOFields.APPLICATION_STATUS_DESCRIPTION_TEXT,
        USPTOFields.APPLICATION_STATUS_CODE: USPTOFields.APPLICATION_STATUS_CODE,
        USPTOFields.FIRST_INVENTOR_NAME: USPTOFields.FIRST_INVENTOR_NAME,
        USPTOFields.EXAMINER_NAME_TEXT: USPTOFields.EXAMINER_NAME_TEXT,
        USPTOFields.GROUP_ART_UNIT_NUMBER: USPTOFields.GROUP_ART_UNIT_NUMBER,
        USPTOFields.CUSTOMER_NUMBER: USPTOFields.CUSTOMER_NUMBER,
        USPTOFields.ENTITY_STATUS_DATA: USPTOFields.ENTITY_STATUS_DATA,
        USPTOFields.INVENTOR_BAG: USPTOFields.INVENTOR_BAG,
        USPTOFields.APPLICANT_BAG: USPTOFields.APPLICANT_BAG,
        USPTOFields.ASSIGNEE_BAG: USPTOFields.ASSIGNEE_BAG,
        USPTOFields.USPC_SYMBOL_TEXT: USPTOFields.USPC_SYMBOL_TEXT,
        USPTOFields.CPC_CLASSIFICATION_BAG: USPTOFields.CPC_CLASSIFICATION_BAG,
        USPTOFields.APPLICATION_TYPE_CODE: USPTOFields.APPLICATION_TYPE_CODE,
        USPTOFields.APPLICATION_TYPE_LABEL_NAME: USPTOFields.APPLICATION_TYPE_LABEL_NAME,
        USPTOFields.EARLIEST_PUBLICATION_NUMBER: USPTOFields.EARLIEST_PUBLICATION_NUMBER,
        USPTOFields.PUBLICATION_DATE_BAG: USPTOFields.PUBLICATION_DATE_BAG,

        # Already prefixed high priority fields
        USPTOFields.APPLICATION_STATUS_DATE: USPTOFields.APPLICATION_STATUS_DATE,
        USPTOFields.FIRST_APPLICANT_NAME: USPTOFields.FIRST_APPLICANT_NAME,
        USPTOFields.APPLICATION_CONFIRMATION_NUMBER: USPTOFields.APPLICATION_CONFIRMATION_NUMBER,
        USPTOFields.DOCKET_NUMBER: USPTOFields.DOCKET_NUMBER,
        USPTOFields.EFFECTIVE_FILING_DATE: USPTOFields.EFFECTIVE_FILING_DATE,
        USPTOFields.NATIONAL_STAGE_INDICATOR: USPTOFields.NATIONAL_STAGE_INDICATOR,
        USPTOFields.EARLIEST_PUBLICATION_DATE: USPTOFields.EARLIEST_PUBLICATION_DATE,
        USPTOFields.FIRST_INVENTOR_TO_FILE_INDICATOR: USPTOFields.FIRST_INVENTOR_TO_FILE_INDICATOR,
        USPTOFields.PCT_PUBLICATION_NUMBER: USPTOFields.PCT_PUBLICATION_NUMBER,
        USPTOFields.PCT_PUBLICATION_DATE: USPTOFields.PCT_PUBLICATION_DATE,
        USPTOFields.CLASS: USPTOFields.CLASS,
        USPTOFields.SUBCLASS: USPTOFields.SUBCLASS,
        USPTOFields.APPLICATION_TYPE_CATEGORY: USPTOFields.APPLICATION_TYPE_CATEGORY,
        USPTOFields.PUBLICATION_SEQUENCE_NUMBER_BAG: USPTOFields.PUBLICATION_SEQUENCE_NUMBER_BAG,
        USPTOFields.PUBLICATION_CATEGORY_BAG: USPTOFields.PUBLICATION_CATEGORY_BAG,
        USPTOFields.INTERNATIONAL_REGISTRATION_NUMBER: USPTOFields.INTERNATIONAL_REGISTRATION_NUMBER,
        USPTOFields.INTERNATIONAL_REGISTRATION_PUBLICATION_DATE: USPTOFields.INTERNATIONAL_REGISTRATION_PUBLICATION_DATE,
        USPTOFields.PARENT_PATENT_NUMBER: USPTOFields.PARENT_PATENT_NUMBER,
        USPTOFields.PARENT_APPLICATION_NUMBER_TEXT: USPTOFields.PARENT_APPLICATION_NUMBER_TEXT,
        USPTOFields.CHILD_APPLICATION_NUMBER_TEXT: USPTOFields.CHILD_APPLICATION_NUMBER_TEXT,
        USPTOFields.DOCUMENT_BAG: USPTOFields.DOCUMENT_BAG,
        USPTOFields.ASSOCIATED_DOCUMENTS: USPTOFields.ASSOCIATED_DOCUMENTS,
    }


def map_query_field_names(query: str) -> str:
    """
    Map user-friendly field names in a Lucene query to USPTO API field names.

    This allows users to write queries with friendly field names like:
        patentNumber:7971071

    Which get automatically converted to API field names:
        applicationMetaData.patentNumber:7971071

    Args:
        query: Lucene query string with user-friendly or API field names

    Returns:
        Query string with all field names converted to API field names

    Examples:
        >>> map_query_field_names('patentNumber:7971071')
        'applicationMetaData.patentNumber:7971071'

        >>> map_query_field_names('inventionTitle:"machine learning"')
        'applicationMetaData.inventionTitle:"machine learning"'

        >>> map_query_field_names('examinerNameText:SMITH AND patentNumber:7971071')
        'applicationMetaData.examinerNameText:SMITH AND applicationMetaData.patentNumber:7971071'
    """
    if not query or not query.strip():
        return query

    field_mapping = get_query_field_mapping()

    # Pattern to match field:value pairs in Lucene queries
    # Matches: fieldName:value or fieldName:"quoted value" or fieldName:[range]
    # Handles: field:value, field:"phrase", field:[start TO end], field:(a OR b)
    field_pattern = r'(\w+(?:\.\w+)*)\s*:'

    def replace_field(match):
        field_name = match.group(1)

        # If already an API field name (has dot), pass through
        if '.' in field_name:
            return match.group(0)

        # Map user-friendly name to API name
        api_field = field_mapping.get(field_name, field_name)

        # Return the mapped field with the colon
        return f"{api_field}:"

    # Replace all field names in the query
    mapped_query = re.sub(field_pattern, replace_field, query)

    logger.debug(f"Mapped query fields: '{query}' -> '{mapped_query}'")

    return mapped_query


def map_user_fields_to_api_fields(user_fields: List[str]) -> List[str]:
    """
    Map user-friendly field names to USPTO API field names

    Args:
        user_fields: List of user-friendly field names

    Returns:
        List of API field names
    """
    # Use the shared field mapping
    field_mapping = get_query_field_mapping()

    mapped_fields = []
    for field in user_fields:
        mapped_field = field_mapping.get(field, field)  # Default to original if not found
        mapped_fields.append(mapped_field)

        # Log unmapped fields for debugging
        if mapped_field == field and field not in field_mapping:
            logger.debug(f"Field '{field}' not found in mapping, using as-is")

    return mapped_fields

def get_document_priority_order() -> List[str]:
    """
    Return document codes in priority order for downloading
    
    Returns:
        List of document codes in priority order
    """
    return [
        'SPEC',      # Specification
        'CLM',       # Claims  
        'ABST',      # Abstract
        'DRW',       # Drawings
        'NOA',       # Notice of Allowance
        'CTFR',      # Final Rejection
        'CTNF',      # Non-Final Rejection
        'IFEE',      # Issue Fee Payment
        'OATH',      # Oath or Declaration
        'IDS',       # Information Disclosure Statement
        'A...',      # Amendment
        'RCEX',      # Request for Continued Examination
        'PA..',      # Power of Attorney
        'EXIN',      # Examiner Interview Summary
        'PET.',      # Petition
        'APP.FILE.REC'  # Filing Receipt
    ]

def generate_safe_filename(app_number: str, invention_title: str, doc_code: str, 
                          patent_number: str = None, max_title_length: int = 40) -> str:
    """
    Generate a safe filename using invention title and optional patent number.
    
    Args:
        app_number: Patent application number
        invention_title: Invention title from applicationMetaData.inventionTitle
        doc_code: Document code (e.g., 'ABST', 'CLM', 'SPEC')
        patent_number: Patent number from applicationMetaData.patentNumber (if application was granted)
        max_title_length: Maximum length for title portion (default: 40)
        
    Returns:
        Safe filename in format: APP-{app_number}_PAT-{patent_number}_{safe_title}_{doc_code}.pdf
        or APP-{app_number}_{safe_title}_{doc_code}.pdf if no patent granted
        
    Examples:
        generate_safe_filename("11752072", "Integrated Delivery System", "ABST", "7971071")
        -> "APP-11752072_PAT-7971071_INTEGRATED_DELIVERY_SYSTEM_ABST.pdf"
        
        generate_safe_filename("17896175", "Communication Method and Apparatus", "ABST")
        -> "APP-17896175_COMMUNICATION_METHOD_AND_APPARATUS_ABST.pdf"
    """
    # Handle empty or None title
    if not invention_title or invention_title.strip() == "":
        safe_title = "UNTITLED"
    else:
        # Clean up the title
        title = invention_title.strip()
        
        # Convert to uppercase and replace spaces with underscores
        title = title.upper().replace(' ', '_')
        
        # Remove or replace problematic characters for cross-platform compatibility
        # Keep only alphanumeric, underscores, and hyphens
        title = re.sub(r'[^A-Z0-9_\-]', '', title)
        
        # Remove multiple consecutive underscores
        title = re.sub(r'_+', '_', title)
        
        # Remove leading/trailing underscores
        title = title.strip('_')
        
        # Truncate to max length
        if len(title) > max_title_length:
            title = title[:max_title_length]
            # Try to break at word boundary (underscore) if possible
            last_underscore = title.rfind('_')
            if last_underscore > max_title_length // 2:  # Only if we're not cutting too much
                title = title[:last_underscore]
        
        # Ensure we have something after all the cleaning
        safe_title = title if title else "UNTITLED"
    
    # Construct the filename with APP- prefix and optional PAT- prefix
    if patent_number and patent_number.strip():
        # Clean patent number (remove any non-alphanumeric except hyphens)
        clean_patent = re.sub(r'[^A-Z0-9\-]', '', str(patent_number).strip().upper())
        filename = f"APP-{app_number}_PAT-{clean_patent}_{safe_title}_{doc_code}.pdf"
    else:
        filename = f"APP-{app_number}_{safe_title}_{doc_code}.pdf"
    
    # Final safety check - ensure total filename isn't too long
    if len(filename) > 100:  # Conservative limit for most filesystems
        # Calculate space available for title
        base_length = len(f"APP-{app_number}_{doc_code}.pdf")
        if patent_number and patent_number.strip():
            clean_patent = re.sub(r'[^A-Z0-9\-]', '', str(patent_number).strip().upper())
            base_length = len(f"APP-{app_number}_PAT-{clean_patent}_{doc_code}.pdf")
        
        max_title_for_length = 100 - base_length - 1  # 1 for underscore before title
        if max_title_for_length > 5:  # Minimum reasonable title length
            return generate_safe_filename(app_number, invention_title, doc_code, patent_number, max_title_for_length)
        else:
            # Fallback to minimal format with prefixes
            if patent_number and patent_number.strip():
                clean_patent = re.sub(r'[^A-Z0-9\-]', '', str(patent_number).strip().upper())
                return f"APP-{app_number}_PAT-{clean_patent}_{doc_code}.pdf"
            else:
                return f"APP-{app_number}_{doc_code}.pdf"
    
    return filename

def extract_patent_number(app_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract patent number from application data (the application's own granted patent).
    
    Patent numbers are found in:
    applicationMetaData.patentNumber (when the application has been granted)
    
    Args:
        app_data: Application data from USPTO API
        
    Returns:
        Patent number as string, or None if application hasn't been granted
    """
    try:
        # Check if this application itself has been granted
        metadata = app_data.get('applicationMetaData', {})
        patent_number = metadata.get('patentNumber')
        
        if patent_number and str(patent_number).strip():
            return str(patent_number).strip()
        
        return None
        
    except Exception as e:
        logger.warning(f"Error extracting patent number: {e}")
        return None
