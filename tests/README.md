# Test Suite — USPTO Patent File Wrapper MCP

## Start Here: Manual End-to-End Tests

**[TEST_SUITE.md](TEST_SUITE.md)** - 21 manual tests (Test 0 through Test 20) covering 12 of the 16 data tools against the live USPTO API. Run these first after setup, upgrades, or code changes.

These tests confirm real API behavior with verified expected outputs. They run via Claude Desktop — no code required. See `TEST_SUITE.md` for the full prompt to paste.

**Last validated:** 2026-03-29 (Claude Desktop, STDIO); document counts and OA expectations re-verified 2026-09-03

---

## Available MCP Tools (16, plus one admin tool)

The server provides these tools for patent research:

### Search Tools
- **`PFW_search_applications`** - Full search with custom field selection
- **`PFW_search_applications_minimal`** - Minimal fields (95-99% context reduction) — always loaded
- **`PFW_search_applications_balanced`** - Balanced fields (85-95% context reduction)
- **`PFW_search_inventor`** - Full inventor search with custom fields
- **`PFW_search_inventor_minimal`** - Minimal inventor search
- **`PFW_search_inventor_balanced`** - Balanced inventor search

### Document Tools
- **`PFW_get_application_documents`** - Get prosecution documents (documentBag) — always loaded
- **`PFW_get_document_content_with_ocr`** - Extract text through four capability tiers: USPTO free-text variants → pypdf native text layer → Mistral OCR → Docling OCR
- **`PFW_get_document_download`** - Secure browser-accessible download URLs
- **`PFW_get_patent_or_application_xml`** - Clean XML content for patents/applications with 91-99% token reduction
- **`PFW_get_granted_patent_documents_download`** - All granted patent components (abstract, claims, drawings, spec)

### Office Action Tools (OA APIs)
- **`PFW_get_oa_rejections`** - Rejection indicators from OA Rejections API (§101/§102/§103/§112, Alice, Bilski, etc.) — coverage from Oct 1, 2017
- **`PFW_get_oa_text`** - Full office action body text or section-filtered rejection text, directly from USPTO ODP text API

### Family & Term Tools
- **`PFW_get_family`** - Normalized continuity graph (parents, children, CON/CIP/DIV) plus foreign priority claims
- **`PFW_get_term_adjustment`** - Patent Term Adjustment days and event history (no expiration date is computed)

### Utility Tools
- **`PFW_get_guidance`** - Workflow guidance, tool descriptions, document code reference — always loaded

### Admin Tool (OAuth deployments only)
- **`pfw_manage_users`** - Registered-user management; registered only when `PFW_ENABLE_USER_MANAGEMENT=true` and gated on the `pfw:admin` scope

---

## Developer Tests (pytest)

These tests cover unit logic, security, proxy server, and integration patterns. They do not replace the manual `TEST_SUITE.md` tests — both serve different purposes.

### How to run them

```bash
# Whole suite. test_unified_key_management.py is excluded because it overwrites
# the REAL secure-storage keys mid-test - only run that one deliberately.
uv run pytest --ignore=tests/test_unified_key_management.py

# No download proxy running on port 8080? Skip the proxy integration test:
SKIP_PROXY_TESTS=1 uv run pytest --ignore=tests/test_unified_key_management.py

# One file
uv run pytest tests/test_identifier_resolution_order.py
```

Live-API tests are gated OFF by default. They run only with an explicit opt-in
(`PFW_RUN_LIVE_TESTS=1` plus a real `USPTO_API_KEY`); the presence of a key is
deliberately not treated as consent.

### What the files cover

**Search, fields and identifiers**
- `test_fields_fix.py` - core search and field mapping
- `test_identifier_logic.py`, `test_identifier_resolution_order.py`,
  `test_content_type_validation.py` - patent-vs-application lane resolution, the
  resolve-then-validate order, and `content_type` rejection
- `test_free_text_variants.py`, `test_no_matches_404.py`

**Documents, extraction and downloads**
- `test_ocr_hybrid_tiers.py`, `test_quality_detection.py` - the extraction tier waterfall
- `test_mistral_key_logic.py`, `test_optional_mistral.py`, `test_placeholder_detection.py`
- `test_download.py`, `test_download_url_validation.py`, `test_safe_filename.py`,
  `test_enhanced_filename.py`, `test_granted_component_selection.py`,
  `test_granted_patent_documents_download.py`
- `test_doc_codes_parser.py`, `test_document_codes_section.py`

**Family, term and office actions**
- `test_family_normalizer.py`, `test_family_ambiguity_note.py`, `test_family_tools_registration.py`
- `test_term_adjustment_normalizer.py`

**Response bounds and paging**
- `test_response_bounds.py`, `test_documents_response_bound.py`,
  `test_bounds_bug_fixes.py`, `test_ingress_bounds.py`, `test_persistent_link_bounds.py`

**Proxy and downloads ingress**
- `test_proxy_simple.py`, `test_proxy_routes.py`, `test_proxy_route_hardening.py`,
  `test_proxy_startup_gate.py`, `test_proxy_token.py`, `test_registration_token_binding.py`

**Auth, secrets and logging**
- `test_auth_provider.py`, `test_user_management_gate.py`, `test_spend_and_scoping.py`
- `test_linux_secret_store.py`, `test_key_and_alert_lifecycle.py`,
  `test_rotate_internal_auth_secret.py`, `test_unified_key_management.py` (excluded by default)
- `test_logging_hardening.py`, `test_security_log_attribution.py`,
  `test_rate_limit_and_log_perms.py`, `test_injection_scan.py`, `test_ui_view_escaping.py`

**Server contract and resilience**
- `test_defer_loading_annotation.py`, `test_probe_middleware_accept.py`,
  `test_prompts_gate.py`, `test_tool_reflections.py`
- `test_resilience_features.py`, `test_client_hardening.py`,
  `test_error_and_header_handling.py`, `test_shared_rate_limiter.py`
- `test_medium_security_fixes.py`, `test_open_items_fixes.py`, `test_evals_findings_fixes.py`

**Cross-MCP**
- `test_fpd_integration.py` (needs a live proxy on 8080; `SKIP_PROXY_TESTS=1` to skip),
  `test_ptab_integration.py`, `test_ptab_simple.py`,
  `test_cross_repo_internal_auth_compat.py` (skips when the sibling repos are not checked out alongside this one)

**Helpers**
- `test_utils.py`, `conftest.py`

---

## API Key Setup

### Option 1: Unified Secure Storage (Recommended)

API keys can be stored in unified secure storage (shared across USPTO MCPs) which is encrypted and persistent:

Keys are automatically loaded from secure storage with environment variable
fallback. See `SECURITY_GUIDELINES.md` for setup instructions.

> Do NOT run `tests/test_unified_key_management.py` to inspect stored keys: it
> WRITES to the shared secure store and overwrites the real keys. It is
> excluded from the default pytest run for that reason.

### Option 2: Environment Variables

```bash
# Windows Command Prompt
set USPTO_API_KEY=your_api_key_here
set MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
set DOCLING_SERVE_URL=http://localhost:5001  REM optional, for Docling OCR

# Windows PowerShell
$env:USPTO_API_KEY="your_api_key_here"
$env:MISTRAL_API_KEY="your_mistral_api_key_here_OPTIONAL"
$env:DOCLING_SERVE_URL="http://localhost:5001"  # optional, for Docling OCR

# Linux/macOS
export USPTO_API_KEY=your_api_key_here
export MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
export DOCLING_SERVE_URL=http://localhost:5001  # optional, for Docling OCR
```

**Notes on optional keys:**
- `MISTRAL_API_KEY` - enables the Mistral OCR tier for scanned USPTO documents. Optional.
- `DOCLING_SERVE_URL` - enables the self-hosted Docling OCR tier. Requires a running [docling-serve](https://github.com/docling-project/docling-serve) instance. Optional.

Both are OCR backends for the same tier of the waterfall, and neither is required: without either, extraction still runs the USPTO free-text and pypdf native-text-layer tiers and returns an actionable message when a scanned page cannot be read. With both configured, Mistral runs first and Docling is the next tier; with only Docling configured, Docling is the OCR tier.

### Option 3: Testing Without Real API Key

If you don't have a USPTO API key yet, test files will use a placeholder key for basic logic testing. Actual API calls will fail without a real key.

---

## Running Developer Tests

The suite is pytest with `asyncio_mode=auto`. Run it through pytest, not by
executing individual files as scripts.

```bash
# Everything except the key-overwriting file
uv run pytest --ignore=tests/test_unified_key_management.py

# Quiet, and skipping the proxy integration test when no proxy is on 8080
SKIP_PROXY_TESTS=1 uv run pytest -q --ignore=tests/test_unified_key_management.py

# One file, or one test
uv run pytest tests/test_response_bounds.py
uv run pytest tests/test_identifier_resolution_order.py -k validate

# Lint
uv run ruff check src tests
```

`test_unified_key_management.py` is excluded by default because it overwrites
the REAL secure-storage keys while it runs. Run it only when you mean to.

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

