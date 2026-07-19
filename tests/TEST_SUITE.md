# USPTO Patent File Wrapper MCP — Test Suite

## What this is

A manual end-to-end test suite for verifying all 14 PFW MCP tools against the live USPTO API
with known inputs and expected outputs. These are not unit tests — they confirm real API behavior
and validate tool correctness after setup, upgrades, or code changes.

**Who it's for:** Developers and maintainers who want confidence the tools behave as documented
before deploying changes to Claude Desktop. Run after setup, after migrations, or after modifying
tool logic.

## How to run

1. Open Claude Desktop with this MCP server connected
2. Paste this prompt to run the whole suite:

> **"Please perform these MCP tests in order. For each test, call the tool with the parameters
> shown and tell me whether the result matches the expected output. Report PASS, PARTIAL, or
> FAIL for each. At the end provide a summary table."**
> *(then paste the test cases below)*

3. Or run tests individually: *"Call `[tool_name]` with these parameters: `[paste JSON]`"*
4. Tests marked ⭐ produce output (document IDs) needed by later tests — note the values before continuing

**Both STDIO and HTTP transport modes should pass all tests.**

---

Feature branch: `feature/fastmcp3-mcp-apps`
Last validated: 2026-03-29 (Claude Desktop, STDIO)

Reference application: **11752072** (Walkoe DRM patent US-7971071-B2, 151 prosecution documents)
Reference application (OA APIs): **15992176** (post-2017, confirmed in OA rejections dataset)

---

## Section 1: Search Tools — 7 Tests

### Test 0: Guidance

```
pfw_get_guidance
{
  "section": "tools"
}
```
**Expect:** Section listing all 14 tools with defer_loading status and descriptions. Three always-loaded tools: `pfw_search_applications_minimal`, `pfw_get_application_documents`, `pfw_get_guidance`.

---

### Test 1: Application Search by Number (API Field)

```
pfw_search_applications_minimal
{
  "limit": 3,
  "query": "applicationNumberText:11752072",
  "fields": ["applicationNumberText", "inventionTitle"]
}
```
**Expect:** 1 result. `applicationNumberText = 11752072`, `inventionTitle` contains "INTEGRATED DELIVERY AND PROTECTION DEVICE FOR DIGITAL OBJECTS". Only 2 fields returned (ultra-minimal mode).

---

### Test 2: Patent Number Search (User-Friendly Field Mapping)

```
pfw_search_applications_minimal
{
  "limit": 3,
  "query": "patentNumber:7971071",
  "fields": ["applicationNumberText", "inventionTitle", "patentNumber"]
}
```
**Expect:** 1 result. `patentNumber = 7971071`, `applicationNumberText = 11752072`. Confirms user-friendly field mapping (`patentNumber` → `applicationMetaData.patentNumber`).

---

### Test 3: Keyword Search

```
pfw_search_applications_minimal
{
  "limit": 3,
  "query": "artificial intelligence",
  "fields": ["applicationNumberText", "inventionTitle"]
}
```
**Expect:** 3 results. `inventionTitle` values contain AI/ML related terms. `numFound` in the thousands.

---

### Test 4: Inventor Search

```
pfw_search_inventor_minimal
{
  "name": "Walkoe",
  "limit": 3,
  "fields": ["applicationNumberText", "inventionTitle", "patentNumber"]
}
```
**Expect:** At least 2 results including app 11752072 (patent 7971071). Inventor "Walkoe" matched via comprehensive strategy.

---

### Test 5: Convenience Parameter Search (Examiner Name)

```
pfw_search_applications_minimal
{
  "examiner_name": "LANIER, BENJAMIN",
  "limit": 3,
  "fields": ["applicationNumberText", "inventionTitle", "groupArtUnitNumber"]
}
```
**Expect:** 3 results. All show examiner LANIER, BENJAMIN. Confirms convenience parameter works (not a raw query string — parameter is translated server-side).

---

### Test 6: Balanced Search with Custom Fields

```
pfw_search_applications_balanced
{
  "limit": 3,
  "query": "inventionTitle:digital AND inventionTitle:protection",
  "fields": ["applicationNumberText", "inventionTitle", "patentNumber", "examinerNameText", "groupArtUnitNumber"]
}
```
**Expect:** 3 results. All 5 requested fields present. `inventionTitle` values contain "digital" and/or "protection". Confirms balanced tool with custom field override.

---

## Section 2: Document Discovery — 2 Tests

### Test 7: Document Listing — ABST Filter ⭐

```
pfw_get_application_documents
{
  "app_number": "11752072",
  "document_code": "ABST",
  "limit": 2
}
```
**Expect:** 1 document returned. `documentCode = ABST`, `documentIdentifier = F20VG7DBPPOPPY4`, `pageTotalQuantity = 1`. Reduction 99.3% (1 of 151 docs). ⭐ Note `F20VG7DBPPOPPY4` — used in Tests 9 and 10.

---

### Test 8: Document Listing — NOA Filter ⭐

```
pfw_get_application_documents
{
  "app_number": "11752072",
  "document_code": "NOA",
  "limit": 1
}
```
**Expect:** 1 document. `documentCode = NOA`, `documentIdentifier = GN23NLY2PPOPPY5`, `pageTotalQuantity = 7`, `officialDate = 2011-04-28`. Reduction 99.3%. ⭐ Note `GN23NLY2PPOPPY5` — used in Test 11.

---

## Section 3: Content & Downloads — 4 Tests

### Test 9: OCR Document Content Extraction (ABST — 1 page)

```
pfw_get_document_content_with_ocr
{
  "app_number": "11752072",
  "document_identifier": "F20VG7DBPPOPPY4",
  "auto_optimize": true
}
```
**Expect:** `success = true`, `extracted_content` contains abstract text about securing a digital device and digital rights verification. `extraction_method` is one of: `PyPDF2`, `Mistral OCR`, or `Docling OCR` (whichever is available). `page_count = 1`. Progress notifications visible in Claude Desktop during call.

**Note:** ABST (1 page) chosen over NOA (7 pages) to save context during testing. For OCR fallback testing specifically, use the NOA (`GN23NLY2PPOPPY5`) or a CTNF (`GF7AGXYVPPOPPY5`, 15 pages).

---

### Test 10: Document Download Link (ABST)

```
pfw_get_document_download
{
  "app_number": "11752072",
  "document_identifier": "F20VG7DBPPOPPY4"
}
```
**Expect:** `proxy_url` returned in format `http://localhost:8080/document/persistent/...`. URL is clickable in browser and downloads the PDF without exposing the USPTO API key. Provide this link to the user.

---

### Test 11: XML Content — Claims Only (91% Token Reduction)

```
pfw_get_patent_or_application_xml
{
  "identifier": "7971071",
  "include_fields": ["claims"],
  "include_raw_xml": false
}
```
**Expect:** `xml_type = PTGRXML` (granted patent). `structured_content.claims` populated with independent and dependent claims about digital device security. No `raw_xml` field present. Token count ~1,500 (vs ~55,000 with raw XML).

---

### Test 12: Complete Granted Patent Package

```
pfw_get_granted_patent_documents_download
{
  "app_number": "11752072",
  "include_drawings": true,
  "generate_persistent_links": true
}
```
**Expect:** Proxy download URLs for Abstract, Drawings, Specification, and Claims components. `total_pages` ~40-80. All 4 components available (this is a granted patent). Provide all download links to the user.

---

## Section 4: OA APIs — New Tools — 6 Tests

### Test 13: OA Rejections — Post-2017 Application (Has Coverage)

```
pfw_get_oa_rejections
{
  "application_number": "15992176",
  "latest_only": true
}
```
**Expect:** `success = true`, `num_found > 0` (confirmed: 19 records), `summary.has_101 = true`, `summary.has_112 = true`, `summary.has_103 = false`. Art unit 2100 / 1765. `data_note` confirms coverage from Oct 1, 2017. This is a post-2017 application with §101 and §112 rejections.

---

### Test 14: OA Rejections — Pre-2017 Application (Coverage Gap)

```
pfw_get_oa_rejections
{
  "application_number": "11752072",
  "latest_only": true
}
```
**Expect:** `num_found = 0`, `note` message explaining coverage starts Oct 1, 2017 and this application predates that window. Confirms graceful handling of pre-coverage applications.

---

### Test 15: OA Text — Full CTNF Body Text

```
pfw_get_oa_text
{
  "application_number": "11752072",
  "action_type": "CTNF",
  "latest_only": true,
  "section": "all"
}
```
**Expect:** `success = true`, `doc_code = CTNF`, `submission_date = 2010-10-13`, `art_unit = 2432`. `text` contains full office action body including §103 rejections citing Qawami and Rohrbach references. `text_length_chars` in the thousands. **No PDF download or OCR required** — text returned directly from USPTO ODP text API.

---

### Test 16: OA Text — Section Filter (§103 Only)

```
pfw_get_oa_text
{
  "application_number": "11752072",
  "action_type": "CTNF",
  "latest_only": true,
  "section": "103"
}
```
**Expect:** `section_returned = 103`. `text` contains only the §103 obviousness rejection section (references to 35 U.S.C. 103, Graham v. John Deere factors, Qawami and Rohrbach citations). Shorter than `section = all`. Confirms section filtering works for targeted rejection analysis.

---

### Test 17: OA Text vs OCR — Preferred Path for Rejection Text

**Step 1 — OA Text API (fast, no OCR):**
```
pfw_get_oa_text
{
  "application_number": "11752072",
  "action_type": "CTNF",
  "section": "103"
}
```

**Step 2 — CTNF document discovery:**
```
pfw_get_application_documents
{
  "app_number": "11752072",
  "document_code": "CTNF",
  "limit": 1
}
```
Note the `documentIdentifier` (should be `GF7AGXYVPPOPPY5`, 15 pages).

**Expect from Step 1:** Text returned instantly, no PDF download. Use this path for reading rejection reasoning.
**Expect from Step 2:** Document identifier confirmed for use with `pfw_get_document_download` when the attorney needs the original formatted PDF.

**Key insight:** `pfw_get_oa_text` is the right tool for reading rejection text in LLM context. `pfw_get_document_download` is for giving attorneys the original formatted PDF. `pfw_get_document_content_with_ocr` is for documents not covered by the OA text API (e.g., applicant responses, drawings, specifications).

---

### Test 18: OA Text — All OAs for Application (latest_only=False)

```
pfw_get_oa_text
{
  "application_number": "11752072",
  "action_type": "CTNF",
  "latest_only": false,
  "section": "all"
}
```
**Expect:** `num_found = 3` (app 11752072 has 3 CTNFs: 2010-10-13, 2009-01-29, and 2008-09-08). Text returned for all non-final rejections. Confirms `latest_only=False` returns full prosecution history OA text.

**Note:** The 2008-09-08 OA (Mathers, art unit 2132) predates the 2009 RCE round and was initially missed in the reference sheet. Corrected 2026-03-29.

---

## Section 5: Context Reduction Validation — 2 Tests

### Test 19: High-Volume Search — Ultra-Minimal Fields (99% Reduction)

```
pfw_search_applications
{
  "limit": 5,
  "query": "applicationMetaData.groupArtUnitNumber:2432",
  "fields": ["applicationNumberText", "applicationMetaData.examinerNameText"]
}
```
**Expect:** 5 results. Each result has exactly 2 fields: `applicationNumberText` and `examinerNameText` (via full API path). Confirms the custom `fields` parameter works on `pfw_search_applications` and that API-path field names are accepted alongside user-friendly names.

---

### Test 20: MCP App Filter Buttons — Multi-Result with Examiner Field Returned

Tests that examiner and applicant filter pills appear when those fields are present in returned data, and that sort buttons are suppressed for fields not requested.

```
pfw_search_applications_minimal
{
  "applicant_name": "Sandisk Corporation",
  "fields": ["applicationNumberText", "inventionTitle", "applicationMetaData.examinerNameText", "applicationMetaData.groupArtUnitNumber"],
  "limit": 10
}
```

**Expect:**
- Multiple results (SanDisk has extensive patent portfolio)
- MCP App shows **Examiner** filter pills (examiner field was requested and returned, multiple unique examiners expected)
- MCP App shows **Art Unit** filter pills (field requested)
- MCP App does **NOT** show Patent #, Filing Date, or Applicant sort/filter options (not requested)
- Sort bar shows only App # and Art Unit (the only fields with data that support sorting)
- Query bar shows: `Fields: applicationNumberText, inventionTitle, applicationMetaData.examinerNameText, applicationMetaData.groupArtUnitNumber`

**Note on examiner filter absence:** If the search uses `examiner_name` as a *convenience parameter* (search filter) but does NOT include `examinerNameText` in `fields`, the examiner column shows "—" and no examiner filter pill appears. This is expected — the parameter filters which records come back, but the field must also be requested to appear in results.

**Alternative test for filter button verification (Inventor filter):**
```
pfw_search_applications_minimal
{
  "applicant_name": "Sandisk Corporation",
  "fields": ["applicationNumberText", "inventionTitle", "applicationMetaData.firstInventorName", "applicationMetaData.examinerNameText"],
  "limit": 15
}
```
Expect: Inventor filter pills appear showing multiple inventors (Fabrice Jogand-Coulomb and others). Confirms inventor filter works when `firstInventorName` field is in the return set.

---

## Quick Reference: Verified Document IDs

All identifiers are for application **11752072** (US-7971071-B2):

| Document | Code | Identifier | Pages | Date |
|----------|------|-----------|-------|------|
| Abstract | ABST | `F20VG7DBPPOPPY4` | 1 | 2007-05-22 |
| Notice of Allowance | NOA | `GN23NLY2PPOPPY5` | 7 | 2011-04-28 |
| Non-Final Rejection (latest) | CTNF | `GF7AGXYVPPOPPY5` | 15 | 2010-10-13 |
| Non-Final Rejection (earlier) | CTNF | `FQIV4W4DPPOPPY5` | 17 | 2009-01-29 |

---

## Quick Reference: OA API Coverage Notes

| API | Coverage | App 11752072 | App 15992176 |
|-----|----------|-------------|-------------|
| `pfw_get_oa_rejections` | Oct 1, 2017 → present | ❌ No data (pre-2017) | ✅ 19 records |
| `pfw_get_oa_text` | ~12-series apps onward | ✅ CTNF text available | ✅ Available |

**When to use which tool for office action text:**

| Goal | Use |
|------|-----|
| Read rejection reasoning in LLM context | `pfw_get_oa_text` |
| Check what rejection types (§101/§102/§103/§112) appeared | `pfw_get_oa_rejections` |
| Give attorney the original formatted PDF | `pfw_get_document_download` |
| Extract text from applicant responses, specs, drawings | `pfw_get_document_content_with_ocr` |

---

## Known Dataset Characteristics

| Observation | Notes |
|-------------|-------|
| App 11752072 | 151 total prosecution documents — heavily prosecuted, good for filter reduction testing |
| OA rejections coverage | Oct 1, 2017 forward only — pre-2017 apps return `num_found = 0` gracefully |
| OA text coverage | ~12-series applications onward (app 11752072 filed 2007 still covered) |
| Document identifiers | Only valid with their specific `applicationNumberText` — not portable |
| `pfw_get_oa_text` bodyText | Returned as joined plain text (underlying API returns list — joined server-side) |
| CTNF vs CTFR | CTNF = Non-Final rejection (common), CTFR = Final rejection — don't swap them |
| `pfw_get_oa_rejections` for 15992176 | 19 records, §101+§112 only, no §103 — chemistry art unit, eligibility focus |
| Docling OCR progress | Visible as "Sending to Docling OCR (N pages — this may take a minute)..." in Claude Desktop status |
| DOCLING_MAX_PAGES | Default 25 — documents over this skip Docling and suggest Mistral OCR |
