# USPTO Patent File Wrapper MCP — Test Suite

## What this is

A manual end-to-end test suite of 21 tests (Test 0 through Test 20) covering 12 of the 16 PFW MCP
data tools against the live USPTO API
(it does not exercise `PFW_get_family`, `PFW_get_term_adjustment`, `PFW_search_inventor` or
`PFW_search_inventor_balanced`)
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

> **Tool visibility caveat (2026-09-02):** `defer_loading: false` is advisory
> metadata that each client applies by its own policy, so an expected tool
> being invisible in a given client is not, by itself, a server defect. If a
> tool this suite calls does not appear in the client, record two facts
> separately: whether the server lists it (direct stdio or in-container probe
> of `tools/list`), and that this client did not. A tool the server does not
> list is a server defect and must be reported as one; a tool the server lists
> but the client hides is a client-visibility finding. Never fold one into the
> other. Load-bearing workflow content deliberately also rides in per-tool
> docstrings and return-path notes for exactly this reason.


---

Stack: FastMCP 4.0.1 on MCP Python SDK 2.x, protocol revision 2026-07-28.
Last validated: 2026-03-29 (Claude Desktop, STDIO); identifier formats updated 2026-09-02;
document counts and OA expectations re-verified 2026-09-03 (see warning below)

Reference application: **11/752,072** (Walkoe DRM patent US-7971071-B2, 151 prosecution documents)
Reference application (OA APIs): **15/992,176** (post-2017, confirmed in OA rejections dataset)

> **⚠ Identifier ambiguity (behavior change 2026-08-31, suite updated 2026-09-02):**
> the bare 8-digit form `11752072` is ALSO a valid granted patent number
> (11,752,072 — an unrelated dental-cement patent, application 16816197). The
> identifier-taking tools (`PFW_get_application_documents`, `PFW_get_oa_rejections`,
> `PFW_get_oa_text`, `PFW_get_family`, `PFW_get_term_adjustment`,
> `PFW_get_granted_patent_documents_download`) now resolve a bare ambiguous
> 8-digit identifier **patent-number-first**, self-reporting via
> `identifier_note` / `identifier_ambiguous: true`. This is deliberate, not a
> bug: a slashed serial (`11/752,072`) or `content_type='application'` is
> unambiguous and short-circuits to the application lane. As of 2026-09-02 all
> six of those tools expose `content_type` ('auto' default, 'patent',
> 'application'); before that it was only on `PFW_get_family` and
> `PFW_get_patent_or_application_xml`. Tests 7, 8, 12 and
> 14–18 therefore use the slash format. `PFW_get_document_content_with_ocr` and
> `PFW_get_document_download` take a literal application number alongside a
> `document_identifier` from a prior listing call and do not lane-resolve —
> also deliberate.
>
> **Updated 2026-09-03:** the note on a slashed serial no longer reads "Pre-2001
> application format". The slash is how USPTO prints a serial in every era, and
> the note said otherwise even for a 2022 filing (17/996,652). It now reads
> "Slash-form serial, unambiguous". A pre-grant PUBLICATION number
> (`20080141381`, or the print forms `US20080141381A1` / `US 2008/0141381 A1`)
> also resolves now, through `applicationMetaData.earliestPublicationNumber`,
> with `identifier_resolved_as = publication`; it used to come back as
> "Could not resolve" on every tool.

---

## Section 1: Search Tools — 7 Tests

### Test 0: Guidance

```
PFW_get_guidance
{
  "section": "tools"
}
```
**Expect:** Section listing all 17 registered tool names (16 data tools plus `pfw_manage_users`, which is registered only on OAuth deployments with `PFW_ENABLE_USER_MANAGEMENT=true`) with defer_loading status and descriptions. Three always-loaded tools: `PFW_search_applications_minimal`, `PFW_get_application_documents`, `PFW_get_guidance`.

---

### Test 1: Application Search by Number (API Field)

```
PFW_search_applications_minimal
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
PFW_search_applications_minimal
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
PFW_search_applications_minimal
{
  "limit": 3,
  "query": "\"artificial intelligence\"",
  "fields": ["applicationNumberText", "inventionTitle"]
}
```
**Expect:** 3 results. `inventionTitle` values contain AI/ML related terms. `numFound` in the thousands.

> Note (2026-09-02): the quotes are load-bearing. An unquoted multi-word query
> is standard Lucene term matching ("artificial" OR "intelligence" — expect
> artificial flowers and fingernails in the results); the quoted form is a
> phrase query. `escape_lucene_query_term` deliberately does not escape quotes
> so callers can do this.

---

### Test 4: Inventor Search

```
PFW_search_inventor_minimal
{
  "name": "Walkoe",
  "limit": 3,
  "fields": ["applicationNumberText", "inventionTitle", "patentNumber"]
}
```
**Expect:** At least 2 results including app 11752072 (patent 7971071) - the API returns `applicationNumberText` as bare digits. Inventor "Walkoe" matched via comprehensive strategy.

**Read as a sample, not a census.** The inventor tiers fan one name out into several name-variant queries and de-duplicate, so there is no single upstream result set to page: they take no `offset`, `paging.total` is null, and `total_unique_applications` counts only what the response holds. A real census needs a change on USPTO's side and is NOT expected here; each inventor tool's description states the limit as of 2026-09-03. Narrow with `art_unit` / `status_code` / `filing_date_start` instead of trying to page.

---

### Test 5: Convenience Parameter Search (Examiner Name)

```
PFW_search_applications_minimal
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
PFW_search_applications_balanced
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
PFW_get_application_documents
{
  "app_number": "11/752,072",
  "document_code": "ABST",
  "limit": 2
}
```
**Expect:** 1 document returned. `documentCode = ABST`, `documentIdentifier = F20VG7DBPPOPPY4`, `pageTotalQuantity = 1`. Reduction 99.3% (1 of 151 docs). ⭐ Note `F20VG7DBPPOPPY4` — used in Tests 9 and 10.

---

### Test 8: Document Listing — NOA Filter ⭐

```
PFW_get_application_documents
{
  "app_number": "11/752,072",
  "document_code": "NOA",
  "limit": 1
}
```
**Expect:** 1 document. `documentCode = NOA`, `documentIdentifier = GN23NLY2PPOPPY5`, `pageTotalQuantity = 7`, `officialDate = 2011-04-28`. Reduction 99.3%. ⭐ Note `GN23NLY2PPOPPY5` — used in Test 11.

---

### Test 8b: Document Listing, Several Codes in One Call (new 2026-09-03)

```
PFW_get_application_documents
{
  "app_number": "11/752,072",
  "document_code": ["CTFR", "CTNF"]
}
```
**Expect:** the union of both codes (application 11/752,072 holds 2 CTFRs and 3 CTNFs), `summary.filtering.filters_applied = ["document_code='CTFR|CTNF'"]`. The pipe-joined string `"CTFR|CTNF"` is accepted and behaves identically. Before this change the filter compared the whole string as one code, so every pipe-joined example the guidance and prompts taught returned an EMPTY bag that looked exactly like "this application has no such document". Each code is still an exact, case-insensitive match: `document_code='A...'` returns only the `A...` documents and never `A.NE`, because there is no wildcard.

---

## Section 3: Content & Downloads — 4 Tests

### Test 9: OCR Document Content Extraction (ABST — 1 page)

```
PFW_get_document_content_with_ocr
{
  "app_number": "11752072",
  "document_identifier": "F20VG7DBPPOPPY4",
  "auto_optimize": true
}
```
**Expect:** `success = true`, `extracted_content` contains abstract text about securing a digital device and digital rights verification. `extraction_method` is one of: `PyPDF2`, `Mistral OCR`, or `Docling OCR` (whichever is available). `page_count = 1`. Progress notifications visible in Claude Desktop during call.

**New 2026-09-03:** adding `"max_pages": 10` to this call returns a 400 naming the four parameters that DO bound the response (`char_offset`, `max_chars`, `page_from`, `page_to`) instead of a schema error naming nothing. `max_pages` has never been a parameter of this tool; it is accepted only so the error can say so.

**Note on `PyPDF2` as an expected value (2026-09-03):** the underlying library is now `pypdf` (`PyPDF2` 3.0.1 is the terminal release of a renamed, end-of-life project, PYSEC-2026-1835). The served `extraction_method` string stays `PyPDF2` — it is the tier's wire identifier, and the PTAB MCP kept its own served value for the same reason. Only the library name in prose changed.

**Note:** ABST (1 page) chosen over NOA (7 pages) to save context during testing. For OCR fallback testing specifically, use the NOA (`GN23NLY2PPOPPY5`) or a CTNF (`GF7AGXYVPPOPPY5`, 15 pages).

---

### Test 10: Document Download Link (ABST)

```
PFW_get_document_download
{
  "app_number": "11752072",
  "document_identifier": "F20VG7DBPPOPPY4"
}
```
**Expect:** `proxy_url` returned as a `/document/persistent/...` link. URL is clickable in browser and downloads the PDF without exposing the USPTO API key. Provide this link to the user. The HOST varies by deployment and both forms PASS: `http://localhost:8080/...` running locally (stdio), or your own public proxy origin (e.g. `https://your-server.example.com/...`) on hosted deployments where `PFW_PROXY_BASE_URL` is set.

---

### Test 11: XML Content — Claims Only (91% Token Reduction)

```
PFW_get_patent_or_application_xml
{
  "identifier": "7971071",
  "include_fields": ["claims"],
  "include_raw_xml": false
}
```
**Expect:** `xml_type = PTGRXML` (granted patent). `structured_content.claims` populated with independent and dependent claims about digital device security. No `raw_xml` field present. Token count ~1,500 (vs ~55,000 with raw XML).

---

### Test 11b: XML Content, Description Pinpoints and Window (new 2026-09-03)

```
PFW_get_patent_or_application_xml
{
  "identifier": "7971071",
  "include_fields": ["description"],
  "description_paragraph_from": 6,
  "description_paragraph_to": 8
}
```
**Expect:** `structured_content.description_paragraphs` with one entry per paragraph carrying `position`, `id` and `num`: the XML `<p>` attributes a claim chart cites, which previously reached a caller only through `include_raw_xml=True`. Either attribute may be null when the XML omits it. `description_paragraph_from = 6`, `description_paragraph_to = 8`, `description_paragraphs_returned = 3`, `description_paragraphs_total` the whole specification's count, and `description` the three paragraphs joined. Omitting the window parameters returns the historical first-5-paragraph summary unchanged; `fields_metadata.fields_included` still lists `description` alone.

---

### Test 11c: XML Content, Publication Number (new 2026-09-03)

```
PFW_get_patent_or_application_xml
{
  "identifier": "20080141381"
}
```
**Expect:** `identifier_resolved_as = publication`, resolution through `applicationMetaData.earliestPublicationNumber` reported in `identifier_lanes_tried`, `application_number = 11752072`, and `xml_type = APPXML` (a publication number names the PRE-GRANT publication; pass the patent number or `content_type='patent'` for issued claims). The ST.16 print forms `US20080141381A1` and `US 2008/0141381 A1` resolve identically. Before this change every tool answered "Could not resolve" for a publication number.

---

### Test 12: Complete Granted Patent Package

```
PFW_get_granted_patent_documents_download
{
  "app_number": "11/752,072",
  "include_drawings": true,
  "generate_persistent_links": true
}
```
**Expect:** Proxy download URLs for Abstract, Drawings, Specification, and Claims components; all 4 present with working links (this is a granted patent). Specification MUST be the complete 21-page original (`F20VG77SPPOPPY4`, 2007-05-22) carrying a `version_selection_note` saying 2 SPEC documents exist and the most complete was chosen; a 2-page specification (`F5CXQRJ3PPOPPY4`, the 2007-08-14 replacement-paragraphs amendment) is the regression this test now guards (fixed 2026-09-02: amendment papers share the component's document code, so the pick is by most PDF pages, earliest date on ties). `total_pages = 32` (abstract 1, drawings 2, specification 21, claims 8; claims is the latest version by design). The tool also reports `versions_considered`/`versions_available` per component.

---

## Section 4: OA APIs — New Tools — 6 Tests

### Test 13: OA Rejections — Post-2017 Application (Has Coverage)

```
PFW_get_oa_rejections
{
  "application_number": "15/992,176",
  "latest_only": true
}
```
**Expect:** `success = true`, `num_found > 0` (confirmed: 19 records), `summary.has_101 = true`, `summary.has_112 = true`, `summary.has_103 = false`. Art unit 2100 / 1765. `data_note` confirms coverage from Oct 1, 2017. This is a post-2017 application with §101 and §112 rejections.

**Changed 2026-09-03, two keys in `summary`:**
- `rejection_rows_total` (rows the dataset holds) now sits next to `office_actions_in_returned_rows` (distinct `submission_date` + `doc_code` pairs among the rows this response carries, a floor while `has_more` is true). `office_actions_count` is retained for one release as a documented alias of `rejection_rows_total`; it was named as if it counted office actions and always held the row count. Measured on application 15/603,285: `num_found` 10, all one CTNF mailed 2018-01-10, which `PFW_get_oa_text` confirms with `num_found` 1.
- `has_103` now requires USPTO's `hasRej103` flag AND at least one §103 citation. The raw flag alone fires on nonstatutory (obviousness-type) double-patenting boilerplate: on application 15/603,285 it was true with `cite_103_max: 0` and no §103 rejection anywhere in the action's text. `has_103_indicator_raw` reports the unqualified flag, per row and in the summary, and `summary.has_103_note` explains a disagreement.

---

### Test 14: OA Rejections — Pre-2017 Application (Coverage Gap)

```
PFW_get_oa_rejections
{
  "application_number": "11/752,072",
  "latest_only": true
}
```
**Expect:** `num_found = 0`, `note` message explaining coverage starts Oct 1, 2017 and this application predates that window. Confirms graceful handling of pre-coverage applications.

---

### Test 15: OA Text — Full CTNF Body Text

```
PFW_get_oa_text
{
  "application_number": "11/752,072",
  "action_type": "CTNF",
  "latest_only": true,
  "section": "all"
}
```
**Expect:** `success = true`, `doc_code = CTNF`, `submission_date = 2010-10-13`, `art_unit = 2432`. `text` contains full office action body including §103 rejections citing Qawami and Rohrbach references. `text_length_chars` in the thousands. **No PDF download or OCR required** — text returned directly from USPTO ODP text API.

**Changed 2026-09-03:** `latest_only=True` now returns the action with the LATEST `submission_date` among the matches, not the dataset's first row. The dataset answers in ascending date order, so the old behavior handed back the OLDEST action of a type (measured on application 16/319,040, which carries two CTFRs, 2021-12-21 and 2022-12-27, and returned the 2021 one). Every response now carries `order = "submission_date_desc"`, `order_note`, and `candidates_considered` (how many matches were sorted before one was taken); `rows_applied` is 10 on every call, because a one-row request cannot be sorted.

---

### Test 16: OA Text — Section Filter (§103 Only)

```
PFW_get_oa_text
{
  "application_number": "11/752,072",
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
PFW_get_oa_text
{
  "application_number": "11/752,072",
  "action_type": "CTNF",
  "section": "103"
}
```

**Step 2 — CTNF document discovery:**
```
PFW_get_application_documents
{
  "app_number": "11/752,072",
  "document_code": "CTNF",
  "limit": 1
}
```
Note the `documentIdentifier` (should be `GF7AGXYVPPOPPY5`, 15 pages).

**Expect from Step 1:** Text returned instantly, no PDF download. Use this path for reading rejection reasoning.
**Expect from Step 2:** Document identifier confirmed for use with `PFW_get_document_download` when the attorney needs the original formatted PDF.

**Key insight:** `PFW_get_oa_text` is the right tool for reading rejection text in LLM context. `PFW_get_document_download` is for giving attorneys the original formatted PDF. `PFW_get_document_content_with_ocr` is for documents not covered by the OA text API (e.g., applicant responses, drawings, specifications).

---

### Test 18: OA Text — All OAs for Application (latest_only=False)

```
PFW_get_oa_text
{
  "application_number": "11/752,072",
  "action_type": "CTNF",
  "latest_only": false,
  "section": "all"
}
```
**Expect:** `num_found = 3` (app 11/752,072 has 3 CTNFs: 2010-10-13, 2009-01-29, and 2008-09-08; re-verified 2026-09-03). Text returned for all non-final rejections. Confirms `latest_only=False` returns full prosecution history OA text.

**Note:** The 2008-09-08 OA (Mathers, art unit 2132) predates the 2009 RCE round and was initially missed in the reference sheet. Corrected 2026-03-29.

**Changed 2026-09-03:** `office_actions` is ordered NEWEST FIRST (`office_actions[0].submission_date = 2010-10-13`), and the per-document split is now tightened until the WHOLE serialized envelope fits the content budget. This call previously came back at about 106,000 characters and was discarded by the client; expect `per_document_char_budget` at or below `max_chars // 3`, a `_bounds` block with `reason = "window"` reporting `items_returned` / `items_total` in characters, and a `_window.next_offset` cursor on each entry that was cut. Actions that fit carry no `_window`, no `truncated`, and the envelope carries no `_bounds`: the no-op contract is unchanged.

---

## Section 5: Context Reduction Validation — 2 Tests

### Test 19: High-Volume Search — Ultra-Minimal Fields (99% Reduction)

```
PFW_search_applications
{
  "limit": 5,
  "query": "applicationMetaData.groupArtUnitNumber:2432",
  "fields": ["applicationNumberText", "applicationMetaData.examinerNameText"]
}
```
**Expect:** 5 results. Each result has exactly 2 fields: `applicationNumberText` and `examinerNameText` (via full API path). Confirms the custom `fields` parameter works on `PFW_search_applications` and that API-path field names are accepted alongside user-friendly names.

---

### Test 20: MCP App Filter Buttons — Multi-Result with Examiner Field Returned

Tests that examiner and applicant filter pills appear when those fields are present in returned data, and that sort buttons are suppressed for fields not requested.

```
PFW_search_applications_minimal
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
PFW_search_applications_minimal
{
  "applicant_name": "Sandisk Corporation",
  "fields": ["applicationNumberText", "inventionTitle", "applicationMetaData.firstInventorName", "applicationMetaData.examinerNameText"],
  "limit": 15
}
```
Expect: Inventor filter pills appear showing multiple inventors (Fabrice Jogand-Coulomb and others). Confirms inventor filter works when `firstInventorName` field is in the return set.

---

## Quick Reference: Verified Document IDs

All identifiers are for application **11/752,072** (US-7971071-B2):

| Document | Code | Identifier | Pages | Date |
|----------|------|-----------|-------|------|
| Abstract | ABST | `F20VG7DBPPOPPY4` | 1 | 2007-05-22 |
| Notice of Allowance | NOA | `GN23NLY2PPOPPY5` | 7 | 2011-04-28 |
| Non-Final Rejection (latest) | CTNF | `GF7AGXYVPPOPPY5` | 15 | 2010-10-13 |
| Non-Final Rejection (earlier) | CTNF | `FQIV4W4DPPOPPY5` | 17 | 2009-01-29 |

---

## Quick Reference: OA API Coverage Notes

| API | Coverage | App 11/752,072 | App 15/992,176 |
|-----|----------|-------------|-------------|
| `PFW_get_oa_rejections` | Oct 1, 2017 → ~30 days before today (documented coverage, not probe-verified) | ❌ No data (pre-2017) | ✅ 19 records |
| `PFW_get_oa_text` | office actions mailed roughly 2008 onward (documented coverage, deliberately hedged and NOT probe-verified - see the module docstring in `tools/oa_tools.py`) | ✅ CTNF text available | ✅ Available |

**When to use which tool for office action text:**

| Goal | Use |
|------|-----|
| Read rejection reasoning in LLM context | `PFW_get_oa_text` |
| Check what rejection types (§101/§102/§103/§112) appeared | `PFW_get_oa_rejections` |
| Give attorney the original formatted PDF | `PFW_get_document_download` |
| Extract text from applicant responses, specs, drawings | `PFW_get_document_content_with_ocr` |

---

## Known Dataset Characteristics

| Observation | Notes |
|-------------|-------|
| App 11/752,072 | 151 total prosecution documents - heavily prosecuted, good for filter reduction testing |
| OA rejections coverage | Oct 1, 2017 forward only — pre-2017 apps return `num_found = 0` gracefully |
| OA text coverage | Office actions mailed roughly 2008 onward. This is documented coverage, hedged and not probe-verified anywhere in this repo (see the `tools/oa_tools.py` module docstring); app 11/752,072, filed 2007, has covered office actions from 2008 on |
| Document identifiers | Only valid with their specific `applicationNumberText` — not portable |
| `PFW_get_oa_text` bodyText | Returned as joined plain text (underlying API returns list — joined server-side) |
| CTNF vs CTFR | CTNF = Non-Final rejection (common), CTFR = Final rejection — don't swap them |
| `PFW_get_oa_rejections` for 15/992,176 | 19 records, §101+§112 only, no §103 - art units 2100 / 1765, eligibility focus |
| Docling OCR progress | Visible as "Sending to Docling OCR (N pages — this may take a minute)..." in Claude Desktop status |
| DOCLING_MAX_PAGES | Default 25 - a longer document skips Docling and the advice names `page_from`/`page_to` plus `DOCLING_MAX_PAGES`; `MISTRAL_API_KEY` is suggested only when no Docling URL is configured |
