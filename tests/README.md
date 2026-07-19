# Test Suite — USPTO Patent File Wrapper MCP

## Start Here: Manual End-to-End Tests

**[TEST_SUITE.md](TEST_SUITE.md)** — 19 manual tests covering all 14 tools against the live USPTO API. Run these first after setup, upgrades, or code changes.

These tests confirm real API behavior with verified expected outputs. They run via Claude Desktop — no code required. See `TEST_SUITE.md` for the full prompt to paste.

**Last validated:** 2026-03-29 (Claude Desktop, STDIO)

---

## Available MCP Tools (14 Total)

The server provides these tools for patent research:

### Search Tools
- **`pfw_search_applications`** - Full search with custom field selection
- **`pfw_search_applications_minimal`** - Minimal fields (95-99% context reduction) — always loaded
- **`pfw_search_applications_balanced`** - Balanced fields (85-95% context reduction)
- **`pfw_search_inventor`** - Full inventor search with custom fields
- **`pfw_search_inventor_minimal`** - Minimal inventor search
- **`pfw_search_inventor_balanced`** - Balanced inventor search

### Document Tools
- **`pfw_get_application_documents`** - Get prosecution documents (documentBag) — always loaded
- **`pfw_get_document_content_with_ocr`** - Extract text with 3-tier chain: PyPDF2 → Mistral OCR → Docling
- **`pfw_get_document_download`** - Secure browser-accessible download URLs
- **`pfw_get_patent_or_application_xml`** - Clean XML content for patents/applications with 91-99% token reduction
- **`pfw_get_granted_patent_documents_download`** - All granted patent components (abstract, claims, drawings, spec)

### Office Action Tools (OA APIs)
- **`pfw_get_oa_rejections`** - Rejection indicators from OA Rejections API (§101/§102/§103/§112, Alice, Bilski, etc.) — coverage from Oct 1, 2017
- **`pfw_get_oa_text`** - Full office action body text or section-filtered rejection text, directly from USPTO ODP text API

### Utility Tools
- **`pfw_get_guidance`** - Workflow guidance, tool descriptions, document code reference — always loaded

---

## Developer Tests (pytest)

These tests cover unit logic, security, proxy server, and integration patterns. They do not replace the manual `TEST_SUITE.md` tests — both serve different purposes.

### Core Functionality Tests
- **`test_fields_fix.py`** - Tests core search functionality and field mapping
- **`test_proxy_simple.py`** - Tests the secure browser download proxy server
- **`test_mcp_server.py`** - Tests basic MCP server startup and configuration
- **`test_quality_detection.py`** - Tests document extraction quality detection logic

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

---

## API Key Setup

### Option 1: Unified Secure Storage (Recommended)

API keys can be stored in unified secure storage (shared across USPTO MCPs) which is encrypted and persistent:

```bash
# View stored keys across all USPTO MCPs (shows metadata only, not actual values)
uv run python tests/test_unified_key_management.py
```

Keys are automatically loaded from secure storage with environment variable fallback. See `SECURITY_GUIDELINES.md` for setup instructions.

### Option 2: Environment Variables

```bash
# Windows Command Prompt
set USPTO_API_KEY=your_api_key_here
set MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
set DOCLING_SERVE_URL=http://localhost:5001_OPTIONAL

# Windows PowerShell
$env:USPTO_API_KEY="your_api_key_here"
$env:MISTRAL_API_KEY="your_mistral_api_key_here_OPTIONAL"
$env:DOCLING_SERVE_URL="http://localhost:5001_OPTIONAL"

# Linux/macOS
export USPTO_API_KEY=your_api_key_here
export MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
export DOCLING_SERVE_URL=http://localhost:5001  # optional, for Docling OCR
```

**Notes on optional keys:**
- `MISTRAL_API_KEY` — enables Mistral OCR (~$0.001/page). Preferred for scanned USPTO docs. Without it, falls back to Docling (free) or returns a message recommending one of the two.
- `DOCLING_SERVE_URL` — enables Docling OCR (free self-hosted fallback). Requires a running [Docling-serve](https://github.com/DS4SD/docling-serve) instance. Without it, extraction falls back to PyPDF2 (text-only PDFs) or returns an actionable message.

### Option 3: Testing Without Real API Key

If you don't have a USPTO API key yet, test files will use a placeholder key for basic logic testing. Actual API calls will fail without a real key.

---

## Running Developer Tests

### With uv (Recommended)
```bash
# Core functionality tests
uv run python tests/test_fields_fix.py
uv run python tests/test_proxy_simple.py
uv run python tests/test_mcp_server.py
uv run python tests/test_quality_detection.py

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
uv run python tests/test_unified_key_management.py
```

### With traditional Python
```bash
python tests/test_fields_fix.py
python tests/test_proxy_simple.py
python tests/test_mcp_server.py
python tests/test_quality_detection.py
```

---

## Prerequisites

### Required Setup
- **Python 3.10+** with required dependencies installed (`uv sync`)
- **Internet connection** for USPTO API access
- **USPTO API Key** — see below

### Getting a USPTO API Key
1. Visit [USPTO Open Data Portal](https://data.uspto.gov/myodp/)
2. Register for an account — select "I don't have a MyUSPTO account and need to create one"
3. Log in
4. Generate an API key for the Patent File Wrapper API
5. Set the key in your environment as shown above

**Security Note:** Never commit API keys to version control.

---

## Archive

The `archive/` folder contains legacy test scripts from development iterations. Preserved for reference but not required for normal operation.
