# Test Suite

This directory contains the test scripts for the USPTO Patent File Wrapper MCP Server.

## Available MCP Tools (11 Total)

The server provides these tools for patent research:

### Search Tools
- **`pfw_search_applications`** - Full search with custom field selection
- **`pfw_search_applications_minimal`** - Minimal fields (95-99% context reduction)
- **`pfw_search_applications_balanced`** - Balanced fields (85-95% context reduction)
- **`pfw_search_inventor`** - Full inventor search with custom fields
- **`pfw_search_inventor_minimal`** - Minimal inventor search
- **`pfw_search_inventor_balanced`** - Balanced inventor search

### Document Tools
- **`pfw_get_application_documents`** - Get prosecution documents (documentBag)
- **`pfw_get_document_content`** - Extract text with hybrid PyPDF2/OCR approach
- **`pfw_get_document_download`** - Secure browser-accessible download URLs
- **`pfw_get_patent_or_application_xml`** - Clean XML content for patents/applications with 91-99% token reduction via `include_raw_xml=False` (recommended) and optional `include_fields` for selective extraction

### Utility Tools
- **`pfw_get_guidance`** - **RECOMMENDED**: Context-efficient selective guidance (see quick reference chart)
- **`pfw_get_tool_reflections`** - Legacy comprehensive guidance (use pfw_get_guidance instead)

## Essential Tests

### Core Functionality Tests
- **`test_fields_fix.py`** - Tests core search functionality and field mapping
- **`test_proxy_simple.py`** - Tests the secure browser download proxy server
- **`test_mcp_server.py`** - Tests basic MCP server startup and configuration
- **`test_quality_detection.py`** - Tests document extraction quality detection logic
- **`test_tool_reflections.py`** - Tests tool reflection metadata and LLM guidance system

### Integration Tests
- **`test_fpd_integration.py`** - Tests FPD MCP centralized proxy integration
- **`test_ptab_simple.py`** - Tests PTAB future Open Data Portal integration readiness

### Additional Tests
- **`test_granted_patent_documents_download.py`** - Tests granted patent document retrieval functionality
- **`test_download.py`** - Tests document download functionality
- **`simple_test.py`** - Basic functionality test
- **`test_mistral_key_logic.py`** - Tests optional Mistral API key handling logic
- **`test_optional_mistral.py`** - Tests document extraction without Mistral API key
- **`test_placeholder_detection.py`** - Tests placeholder API key detection and validation
- **`test_resilience_features.py`** - Tests circuit breaker and retry logic functionality
- **`test_utils.py`** - Test utilities for standardized configuration and API key management

### Diagnostic & Demonstration Tests
- **`test_field_mapping_diagnostic.py`** - Demonstrates field mapping functionality (user-friendly → API field names)
- **`test_include_fields.py`** - Demonstrates XML field selection and token reduction with `include_fields` and `include_raw_xml` parameters
- **`test_document_codes_section.py`** - Tests document_codes section in pfw_get_guidance tool

### Cross-MCP Integration Tests
- **`test_enhanced_filename.py`** - Tests FPD enhanced filename integration for petition documents
- **`test_unified_key_management.py`** - Tests unified secure storage system across USPTO MCPs (PFW, FPD, PTAB, Citations)

### Legacy Development Tests (Can Be Archived)
These tests were created to diagnose and fix specific issues during development. The fixes have been validated and integrated. Consider moving to `archive/` directory:

- **`test_all_convenience_parameters.py`** - Comprehensive test of all 7 convenience parameters (one-time validation)
- **`test_art_unit_fix.py`** - Art unit search colon escaping fix (✅ fixed and working)
- **`test_audit_fixes.py`** - Lucene escaping and circuit breaker tests (✅ fixed and working)
- **`test_date_ranges.py`** - Date range query construction validation (✅ fixed and working)
- **`test_examiner_search.py`** - Examiner name tokenization debugging (✅ fixed and working)
- **`test_exact_query_construction.py`** - Query construction debugging (✅ fixed and working)
- **`test_quote_escaping.py`** - Quote escaping in queries debugging (✅ fixed and working)
- **`test_final_escape_fix.py`** - Final Lucene escape fix validation (✅ fixed and working)

### API Key Setup

**Option 1: Unified Secure Storage (Recommended)**

API keys can be stored in unified secure storage (shared across USPTO MCPs) which is encrypted and persistent:

```bash
# View stored keys across all USPTO MCPs (shows metadata only, not actual values)
uv run python tests/test_unified_key_management.py
```

Keys are automatically loaded from secure storage with environment variable fallback. See `SECURITY_GUIDELINES.md` for setup instructions.

**Option 2: Environment Variables**
```bash
# Windows Command Prompt
set USPTO_API_KEY=your_api_key_here
set MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL

# Windows PowerShell
$env:USPTO_API_KEY="your_api_key_here"
$env:MISTRAL_API_KEY="your_mistral_api_key_here_OPTIONAL"

# Linux/macOS
export USPTO_API_KEY=your_api_key_here
export MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
```

**Option 3: Testing Without Real API Key**
If you don't have a USPTO API key yet, the test files will automatically use a test key for basic functionality testing. However, actual API calls will fail without a real key.

**Note:** The MISTRAL_API_KEY is optional. Without it, document extraction uses free PyPDF2 (works for text-based PDFs). With it, OCR capabilities are available for scanned documents (~$0.001/page cost).

## Running Tests

### With uv (Recommended)
```bash
# Core functionality tests
uv run python tests/test_fields_fix.py
uv run python tests/test_proxy_simple.py
uv run python tests/test_mcp_server.py
uv run python tests/test_quality_detection.py
uv run python tests/test_tool_reflections.py

# Integration tests
uv run python tests/test_fpd_integration.py
uv run python tests/test_ptab_simple.py

# Additional functionality tests
uv run python tests/test_granted_patent_documents_download.py
uv run python tests/test_download.py
uv run python tests/simple_test.py

# Diagnostic & demonstration tests
uv run python tests/test_field_mapping_diagnostic.py
uv run python tests/test_include_fields.py
uv run python tests/test_document_codes_section.py

# Cross-MCP integration tests
uv run python tests/test_enhanced_filename.py
uv run python tests/test_ptab_integration.py
uv run python tests/test_unified_key_management.py
```

### With traditional Python
```bash
# Core functionality tests
python tests/test_fields_fix.py
python tests/test_proxy_simple.py
python tests/test_mcp_server.py
python tests/test_quality_detection.py
python tests/test_tool_reflections.py

# Integration tests
python tests/test_fpd_integration.py
python tests/test_ptab_simple.py

# Additional functionality tests
python tests/test_granted_patent_documents_download.py
python tests/test_download.py
python tests/simple_test.py

# Diagnostic & demonstration tests
python tests/test_field_mapping_diagnostic.py
python tests/test_include_fields.py
python tests/test_document_codes_section.py

# Cross-MCP integration tests
python tests/test_enhanced_filename.py
python tests/test_ptab_integration.py
python tests/test_unified_key_management.py
```

## Expected Results

### test_fields_fix.py
```
✅ ALL TESTS PASSED - Fields fix is working correctly!
```

### test_proxy_simple.py
```
============================================================
ALL TESTS PASSED!
Server-side proxy implementation is working correctly
Users can now download patent PDFs directly in browser
USPTO API keys remain secure server-side
============================================================
```

### test_mcp_server.py
```
✅ Successfully imported MCP server
✅ Found tools: [...]
✅ MCP server can be imported and accessed successfully
```

### test_quality_detection.py
```
Testing Quality Detection Logic
========================================
PASS: Good patent text -> True (expected True)
PASS: Empty text -> False (expected False)
[... 8 more test cases ...]
Results: 10/10 tests passed
All quality detection tests passed!
```

### test_tool_reflections.py
```
Testing Tool Reflections System
========================================
Loaded 4 tool reflections
PASS: pfw_get_document_content reflection found
PASS: pfw_get_document_download reflection found
PASS: pfw_search_applications_balanced reflection found
PASS: pfw_get_application_documents reflection found
PASS: Session 5 enhancement documented
PASS: Download tool UX requirements found
All tool reflection tests passed!
```

### test_fpd_integration.py
```
✅ FPD Integration: ALL TESTS PASSED
✅ Document registration with PFW centralized proxy working
✅ Enhanced filenames stored and retrieved correctly
✅ Cross-MCP workflows verified
```

### test_ptab_simple.py
```
[PASS] PTAB Integration: ALL TESTS PASSED
✅ Document registration working
✅ Document retrieval working
✅ Proceeding number validation working
✅ Pydantic model validation working

SUCCESS: PTAB integration is ready for Open Data Portal!
```

### test_granted_patent_documents.py
```
✅ Granted patent document retrieval working correctly
✅ All 4 components (Abstract, Drawings, Specification, Claims) found
✅ Download URLs generated successfully
```

### test_download.py
```
✅ Document download functionality working
✅ Proxy server started successfully
✅ Download URLs generated correctly
```

### simple_test.py
```
✅ Basic MCP server functionality verified
✅ API client initialization successful
✅ Essential tools accessible
```

### test_field_mapping_diagnostic.py
```
Application number (top-level field):
  Input:  applicationNumberText:11752072
  Output: applicationNumberText:11752072

Patent number (needs prefix):
  Input:  patentNumber:7971071
  Output: applicationMetaData.patentNumber:7971071

Patent number (already prefixed):
  Input:  applicationMetaData.patentNumber:7971071
  Output: applicationMetaData.patentNumber:7971071
```

### test_include_fields.py
```
================================================================================
XML FIELD SELECTION EXAMPLES
================================================================================

1. Default (optimized for general patent analysis)
   Call: pfw_get_patent_or_application_xml(identifier='7971071')
   Returns: xml_type, abstract, claims, description
   Context: ~5K tokens

2. Just claims (for claim analysis)
   Call: pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims'])
   Returns: xml_type, claims
   Context: ~2K tokens

3. Claims + citations (for prior art analysis)
   Call: pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims', 'citations'])
   Returns: xml_type, claims, citations
   Context: ~3K tokens

[... additional examples ...]

CONTEXT OPTIMIZATION TIPS
================================================================================

1. Default includes core content only (abstract, claims, description)
2. For metadata, prefer pfw_search_applications_balanced (already in context)
3. For citations, consider uspto_enriched_citation_mcp (richer data)
4. Request only what you need to minimize token usage
```

### test_document_codes_section.py
```
Testing pfw_get_guidance('document_codes')...
================================================================================
PASS: All assertions passed!
PASS: Result length: ~3500 characters
PASS: document_codes section contains 50+ document codes with examples
```

### test_enhanced_filename.py
```
================================================================================
ENHANCED FILENAME INTEGRATION TEST
================================================================================

[+] TEST 1: Store document WITH enhanced filename
--------------------------------------------------------------------------------
[PASS] Document registered successfully
[PASS] Enhanced filename stored correctly

[+] TEST 2: Retrieve document and verify enhanced filename
--------------------------------------------------------------------------------
[PASS] Document retrieved successfully
[PASS] Enhanced filename matches: PET-2025-09-03_APP-18462633_...

[SUCCESS] All enhanced filename tests passed!
```

### test_ptab_integration.py
```
[TEST] Testing PTAB Document Store...
[PASS] Document registered successfully
[PASS] Document retrieved correctly
[PASS] Proceeding number validation working
[PASS] Enhanced filename stored and retrieved

[SUCCESS] PTAB integration is ready for Open Data Portal!
```

### test_unified_key_management.py
```
============================================================
Unified Secure Storage Test - USPTO MCPs
============================================================

Testing unified storage functionality...
[OK] Storage file exists
[OK] Keys found: USPTO_API_KEY, MISTRAL_API_KEY
[OK] Cross-MCP compatibility verified
[OK] Security: Only showing last 5 digits

[SUCCESS] All unified key management tests passed!
```

## Prerequisites

### Required Setup
- **Python 3.10+** with required dependencies installed
- **Internet connection** for USPTO API access
- **USPTO API Key** (see setup instructions below)

**Getting a USPTO API Key:**
1. Visit [USPTO Open Data Portal](https://data.uspto.gov/myodp/)
2. Register for an account - Select "I don’t have a MyUSPTO account and need to create one"
3. Log in
4. Generate an API key for the Patent File Wrapper API
5. Set the key in your environment as shown above

**Security Note:** Never commit API keys to version control. The test files now use secure environment variable patterns.

## Archive

The `archive/` folder contains legacy test scripts from development iterations. These are preserved for reference but not required for normal operation.
