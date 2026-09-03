"""Sectioned guidance content for PFW_get_guidance (audit: metrics 6/10 —
~950 lines of pure string literals carved out of main.py).

Every function returns a static markdown string; get_guidance_sections()
exposes the section->content mapping the tool dispatches on.
"""


def get_guidance_sections() -> dict:
    """Section name -> guidance content, as served by PFW_get_guidance."""
    return {
        "overview": _get_overview_section(),
        "workflows_pfw": _get_workflows_pfw_section(),
        "workflows_ptab": _get_workflows_ptab_section(),
        "workflows_fpd": _get_workflows_fpd_section(),
        "workflows_citations": _get_workflows_citations_section(),
        "workflows_pinecone": _get_workflows_pinecone_section(),
        "workflows_complete": _get_workflows_complete_section(),
        "documents": _get_documents_section(),
        "document_codes": _get_document_codes_section(),
        "fields": _get_fields_section(),
        "family": _get_family_section(),
        "tools": _get_tools_section(),
        "errors": _get_errors_section(),
        "advanced": _get_advanced_section(),
        "cost": _get_cost_section(),
        "limits": _get_limits_section(),
    }

# =============================================================================

def _get_overview_section() -> str:
    """Overview section with available sections and quick reference"""
    return """## Available Sections and Quick Reference

### 🎯 Quick Reference Chart - What section for your question?

- 🔍 **"Find patents by inventor/company/art unit"** → `fields`
- 🌳 **"Continuations, divisionals, parent/child family, foreign priority, patent term adjustment"** → `family`
- 📝 **"Read an office action / what did the examiner reject"** → use `PFW_get_oa_rejections` then `PFW_get_oa_text` directly. One call for the text, no document bag and no scanning step in between. See `documents` and `cost` for the boundary against the bag fallback.
- 📄 **"Get complete patent package/documents"** → `documents`
- 🔖 **"Decode document codes (NOA, CTFR, 892, etc.)"** → `document_codes`
- 🤝 **"Research IPR vs prosecution patterns"** → `workflows_ptab`
- 🚩 **"Analyze petition red flags + prosecution"** → `workflows_fpd`
- 📊 **"Citation analysis for examiner behavior"** → `workflows_citations`
- 🧠 **"Domain-based RAG for legal framework (§101, §103, §112)"** → `workflows_pinecone`
- 🏢 **"Complete company due diligence"** → `workflows_complete`
- ⚙️ **"Tool guidance and parameters"** → `tools`
- ❌ **"Search errors or download issues"** → `errors`
- ⚡ **"Optimize extraction and context usage"** → `cost`
- 📏 **"Why was my response truncated / how do I page it?"** → `limits`

### Available Sections:
- **overview**: Available sections and tool summary (this section)
- **workflows_pfw**: PFW-only workflows (litigation, due diligence, prior art)
- **workflows_ptab**: PFW + PTAB integration workflows
- **workflows_fpd**: PFW + FPD integration workflows
- **workflows_citations**: PFW + Citations integration workflows
- **workflows_pinecone**: PFW + Pinecone RAG/Assistant domain-based strategic search (9 domains: §101, §103, §112, etc.)
- **workflows_complete**: Four-MCP complete lifecycle analysis
- **documents**: Document downloads, codes, and selection guidance
- **document_codes**: Comprehensive document code decoder (50+ codes)
- **fields**: Field selection strategies, context reduction, and what the search index covers
- **family**: Continuity family graph + patent term adjustment (PFW_get_family, PFW_get_term_adjustment)
- **tools**: Tool-specific guidance and parameters
- **errors**: Common error patterns and troubleshooting
- **advanced**: Advanced workflows and optimization
- **cost**: Extraction and context efficiency strategies
- **limits**: Active response budgets, the `_bounds`/`_window` markers, paging

### Context Efficiency Benefits:
- **95% token reduction** (1-12KB per section vs 62KB total)
- **Targeted guidance** for specific workflows
- **Same comprehensive content** organized for efficiency
- **Backwards compatible** with MCP Resources"""

def _get_tools_section() -> str:
    """Tools section with tool-specific guidance"""
    return """## All 16 PFW MCP Tools

### Always-Loaded Tools (3) — Available immediately, no tool search required
- **PFW_search_applications_minimal** — Primary entry point: high-volume discovery (15 preset fields or custom ultra-minimal). Use first.
- **PFW_get_application_documents** — Get prosecution document metadata, filter by document code (CLM, 892, 1449, IDS, etc.). NOT the way to read an office action: `PFW_get_oa_text` returns OA text directly with no bag lookup and no scanning step.
- **PFW_get_guidance** — Context-efficient sectioned guidance (this tool). Use section parameter for targeted help.

### Search Tools (5) — Deferred, loaded on demand
- **PFW_search_applications** — Full search with custom field selection
- **PFW_search_applications_balanced** — Detailed analysis with 21 fields including cross-MCP integration fields and family awareness (parent/child application numbers, foreign priority)
- **PFW_search_inventor** — Inventor search with custom fields
- **PFW_search_inventor_minimal** — Efficient inventor portfolio discovery
- **PFW_search_inventor_balanced** — Comprehensive inventor analysis

### Document & Content Tools (4) — Deferred, loaded on demand
- **PFW_get_document_content_with_ocr** — text extraction: downloadOptionBag text variants (.docx → xmlarchive → as-uploaded PDF text layer) → PyPDF2 → OCR → Docling. Use for prosecution docs.
- **PFW_get_document_download** — Secure proxy download URL for browser access. Pass to attorney for formatted PDF.
- **PFW_get_patent_or_application_xml** — Structured XML content (claims, abstract, etc.) with 91-99% token reduction via include_raw_xml=False
- **PFW_get_granted_patent_documents_download** — All granted patent components (abstract, claims, drawings, spec) as download links

### Office Action Tools (2) — Deferred, loaded on demand. THE primary path for reading office actions.
- **PFW_get_oa_rejections** — Rejection indicators: hasRej101/102/103/112, Alice/Bilski/Mayo/Myriad flags, citation counts. Structured data, small context. Coverage: Oct 1, 2017 to ~30 days ago. Rows are per rejection group, not per OA — one OA usually yields several rows sharing a submission_date and doc_code; use the `summary` block and `office_actions_count` for the roll-up.
- **PFW_get_oa_text** — Full office action body text or section-filtered (101/102/103/112), in ONE call with no document bag, no PDF and no scanning step in between. Coverage is office actions mailed roughly 2008 onward (10-series applications and later), materially broader than the OA-rejections floor — an empty PFW_get_oa_rejections result does NOT mean the text is unavailable.

### Family & Term Tools (2) — Deferred, loaded on demand
- **PFW_get_family** — Normalized continuity family graph: nodes + edges with CON/CIP/DIV relation types, direct parents and children, earliest ancestors, and foreign priority claims. One USPTO call at the default max_depth=1. See the `family` section for the depth-2 cost and the per-direction emptiness semantics.
- **PFW_get_term_adjustment** — Patent Term Adjustment from the ODP /adjustment endpoint: total days, A/B/C delay, applicant delay, and a capped most-recent-first event history. Does NOT compute an expiration date.

**Coverage floors differ per tool — do not lump them together.** Oct 1, 2017 is the PFW_get_oa_rejections floor (and the Citations MCP floor). PFW_get_oa_text reaches back roughly a decade further.

**PFW_get_oa_text practicalities.** `latest_only` defaults True (single most recent matching OA); set False for up to 10. `action_type` takes the document code — CTNF, CTFR, NOA, CTRS. `section=` accepts only 101/102/103/112, and USPTO populates those sub-documents sparsely: 101/102/112 are frequently empty even when 103 is present, and when the requested section is empty the tool transparently falls back to the FULL body, so a section= request can return far more text than expected. Check `section_returned` and `text_length_chars`. Full bodies observed in practice range from ~3K chars (NOA) to ~69K chars (a heavy CTNF). No coverage is not an error: `success=True`, `num_found=0`, empty text — branch on num_found.

### Admin Tool (optional, not counted above)
- **pfw_manage_users** — Registered-user management. Only registered when PFW_ENABLE_USER_MANAGEMENT=true (OAuth deployments); requires the pfw:admin scope. Absent in STDIO.

## Progressive Disclosure Strategy

### Stage 1: Discovery (Minimal Search)
- Use `PFW_search_applications_minimal` for broad exploration
- 15 preset fields (~500 chars/result) OR custom fields (~100 chars/result)
- Present top results to user for selection on vague queries

### Stage 2: Analysis (Balanced Search)
- Use `PFW_search_applications_balanced` for detailed metadata
- 21 fields including cross-MCP integration fields and family awareness (~2KB/result)
- Limit to 10-20 user-selected results

### Stage 3: Office Actions (whenever the question is about rejections, examiner reasoning, or allowance)
- Start with `PFW_get_oa_rejections` — structured triage of which OAs carry 101/102/103/112 and Alice flags. Cheap, small.
- Then `PFW_get_oa_text` for the ones that matter — the examiner's actual words in one call, nothing in between.
- Only fall through to Stage 4 for what these two cannot serve.

### Stage 4: Documents
- Use `PFW_get_application_documents` to see document metadata
- Strategic selection of most valuable documents
- This is the FALLBACK for office actions, not the default. Use it when: the OA predates the OA text dataset (roughly pre-2008); the document is not an office action (claims, amendments, 892/1449 forms, IDS, specifications, drawings); an actual PDF or an attorney-shareable download link is wanted; or `PFW_get_oa_text` returned num_found=0.
- Note this endpoint can return HTTP 403 on some older applications, so the bag is not guaranteed to be available even when the OA text is.

### Stage 5: Content
- Try `PFW_get_patent_or_application_xml` first (free)
- Use document extraction tools for prosecution documents
- `PFW_get_document_content_with_ocr` runs a full OCR pass on scanned PDFs. Never use it on an office action `PFW_get_oa_text` can already serve.
- Use proxy downloads for browser access

## XML Field Selection (PFW_get_patent_or_application_xml)

### Two Parameters for Maximum Control

**1. include_fields** - Select which structured fields to return:
- Default: ["abstract", "claims", "description"]
- Available: abstract, claims, description, inventors, applicants, classifications, citations, publication_info
- Use to get surgical precision on content needed

**2. include_raw_xml** - Control raw XML inclusion:
- Default: True (backward compatibility - includes ~50K character raw XML)
- **RECOMMENDED: False** (removes raw XML overhead - most workflows don't need it)
- Raw XML useful ONLY for: debugging, custom XML parsing, or raw XML analysis
- For 95%+ of use cases: Set to False

### Why Set include_raw_xml=False?

**Problem with default:**
- Returns structured_content (~5K tokens) + raw_xml (~50K tokens) = 55K tokens total
- Raw XML is the full patent XML document (50,000+ characters)
- Wastes context unless you're doing custom XML parsing

**Solution:**
- Set include_raw_xml=False
- Get ONLY structured_content with selected fields
- Achieves 91-99% token reduction depending on field selection

### Ultra-Efficient Usage (RECOMMENDED)

**Just Claims without raw XML (~1.5K tokens - 95% reduction!):**
```python
PFW_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['claims'],
    include_raw_xml=False
)
```
Use for: Claim construction, infringement analysis, claim scope assessment

**Claims + Citations without raw XML (~2.5K tokens):**
```python
PFW_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['claims', 'citations'],
    include_raw_xml=False
)
```
Use for: Prior art analysis, claim differentiation
Note: Consider uspto_enriched_citation_mcp for deeper citation trees

**Inventors + Applicants without raw XML (~500 tokens - 99% reduction!):**
```python
PFW_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['inventors', 'applicants'],
    include_raw_xml=False
)
```
Use for: Portfolio reports, entity analysis, assignment tracking

**Default fields without raw XML (~5K tokens):**
```python
PFW_get_patent_or_application_xml(
    identifier='7971071',
    include_raw_xml=False
)
```
Use for: Standard patent analysis without raw XML overhead

### Available Fields
- **Core:** abstract, claims, description
- **Metadata:** inventors, applicants, classifications, publication_info
- **References:** citations

### Context Optimization Tips
- **Always set include_raw_xml=False unless you need raw XML for custom parsing**
- Default is optimal for field selection, but includes raw XML overhead
- Check if metadata already available from PFW_search_applications_balanced
- For inventor/applicant reports: Add include_fields=['inventors', 'applicants'] if using minimal search
- Request only what you need - each field adds tokens

## Key Parameters

### Field Customization
```python
# Ultra-minimal for discovery
fields=["applicationNumberText", "inventionTitle"]

# Cross-MCP integration
fields=["applicationNumberText", "examinerNameText", "groupArtUnitNumber"]
```

### Convenience Parameters
- `applicant_name`: Direct applicant search
- `inventor_name`: Direct inventor search
- `examiner_name`: Find by specific examiner
- `art_unit`: Filter by group art unit
- `filing_date_start/end`: Date range filtering
- `application_status`: Filter by status"""

def _get_documents_section() -> str:
    """Documents section with codes, selection, and download guidance"""
    return """## Document Selection Guide

### Read this first: office actions do not need the document bag
CTNF, CTFR, NOA and CTRS are served directly as text by `PFW_get_oa_text` — one call, no
document identifier, no PDF, no scanning step, back to office actions mailed roughly 2008.
Triage first with `PFW_get_oa_rejections`. Everything below is for the documents the OA
tools do NOT cover (amendments, responses, IDS and 1449/892 forms, claims, specifications,
drawings), for office actions older than that dataset, and for when an actual PDF is wanted.
`PFW_get_application_documents` can also return HTTP 403 on some older applications, so the
bag is not always available even where the OA text still is.

### Identifier formats: a bare 8-digit number is ambiguous

US patent numbers crossed 10,000,000 in mid-2018, so an 8-digit number is now BOTH a
valid granted patent number and a valid application serial. Nothing in the digits tells
the two apart, so no heuristic can choose; the API chooses, and the order is fixed:
`applicationMetaData.patentNumber:<n>` is queried FIRST and `applicationNumberText:<n>`
is the fallback. An 8-digit application serial therefore gets captured by an unrelated
granted patent whenever one carries the same digits (live example: 12539322 resolves to
PATENT 12,539,322, application 17996652, not to application 12/539,322).

**Forcing the application lane.** Two ways, both reliable:
- **The slash-comma serial format, `11/752,072`**, the form printed on every USPTO
  filing receipt. Resolution types it as an application before any lane is queried, so
  it always works and costs no extra call. Prefer this.
- **`content_type='application'`** on the resolving tools: `PFW_get_application_documents`,
  `PFW_get_granted_patent_documents_download`, `PFW_get_family`, `PFW_get_term_adjustment`,
  `PFW_get_oa_rejections`, `PFW_get_oa_text`, `PFW_get_patent_or_application_xml`.
  Values are `'auto'` (default, patent lane first), `'patent'` and `'application'`.

**Every resolving response self-reports.** Read `identifier_resolved_as`
('patent' | 'application' | 'publication'), `identifier_lanes_tried` (the queries that
ran and what each matched) and `identifier_note` (plain-language explanation), plus
`identifier_ambiguous: true` when the input could have gone either way. If
`identifier_resolved_as` is not what you meant, re-call in the slash format or with
`content_type`.

**The document tools do NOT resolve.** `PFW_get_document_download` and
`PFW_get_document_content_with_ocr` take a LITERAL application number plus a
`document_identifier` obtained from `PFW_get_application_documents`. They run no lane
probe and emit no identifier fields, so resolve the identifier upstream with a resolving
tool and carry its `application_number` forward.

### Text variants are not the same document as the PDF

`PFW_get_document_content_with_ocr` prefers the text variants USPTO serves alongside
the PDF render (.docx, then xmlarchive, then an as-uploaded PDF's text layer) — that is
what keeps OCR out of the loop on USPTO-authored papers. The variants carry the BODY text
only: **the .docx variant of an order or office action omits the USPTO form pages the PDF
carries** (observed 2026-08-30: a reexam order's PTOL-471G form page, which states the
response deadline and the consequence of filing no statement, is in the PDF and absent
from the .docx). `downloadOptionBag` gives no hint of this, so check
`extraction_method` in the response: anything other than "PyPDF2", "Mistral OCR ..." or
"Docling OCR" means you are reading a text variant and any form page is missing. When a
deadline, a form paragraph or a signature block matters, pull the PDF with
`PFW_get_document_download`, or force the render path.

### Most Important Document Types
- **CTFR**: Office Action (rejection/objection) — text via `PFW_get_oa_text(action_type='CTFR')`
- **NOA**: Notice of Allowance (examiner's final reasoning) — text via `PFW_get_oa_text(action_type='NOA')`
- **892**: Examiner's Prior Art Citations — for the citation LIST prefer `Citations_search_oa_citations_minimal` (broader coverage than the enriched index)
- **REM / A... / A.NE**: the applicant's actual arguments and amendments — genuine document-bag work
- **N417**: EFS Acknowledgment Receipt (a filing receipt, NOT an applicant response — verified 2026-08-30)
- **EXIN**: Examiner Interview Summary Record (PTOL-413) — genuine document-bag work

### Document Selection by Use Case

#### Litigation Research
**Priority:** NOA → Final CTFR → 892 → REM/A...
**Focus:** Examiner's reasoning and prior art analysis
**Note:** take the NOA, CTFR and CTAV through `PFW_get_oa_text`; use the bag for 892 images and the applicant's REM/A... papers

#### Due Diligence
**Priority:** NOA → All CTFR → Fee worksheets → Interview summaries
**Focus:** Prosecution quality and timeline issues

#### Prior Art Research
**Priority:** 892 → CTFR with 103 rejections → Search reports
**Focus:** Examiner's search methodology and citation patterns

#### Patent Prosecution Strategy
**Priority:** Interview summaries → NOA → Recent CTFRs in art unit
**Focus:** Examiner preferences and successful arguments

## Document Direction Categories
- **FROM_USPTO**: CTNF, CTFR, NOA, CTRS, CTAV, 892, EXIN (examiner to applicant)
- **FROM_APPLICANT**: A..., REM, IDS, RCEX, 136A, N417 (EFS receipt) (applicant to USPTO)
- **SYSTEM_GENERATED**: BIB, IIFW, ISSUE.NTF, NTC.PUB, status updates

## Secure Downloads

### Proxy Server Features
- **Browser-accessible downloads** via secure proxy
- **API key security** - keys never exposed in URLs
- **Rate limiting compliance** (5 downloads per 10 seconds)
- **Enhanced filenames** with application metadata

### Download Workflow
1. **Automatic proxy startup** when download tools are called
2. **Working links** immediately available in browser
3. **7-day encrypted access** to downloaded documents
4. **Cross-MCP document store** for FPD and PTAB integration

## Extraction Method Selection

### Document Extraction Hierarchy
1. **XML Content**: Try first for patents/applications - fastest, structured
2. **PyPDF2**: Fast text extraction, works for 80%+ of patent documents
3. **OCR**: Only for scanned/poor quality documents - slower but handles true scans

### Smart Extraction Management
- Always try XML first for patents
- Use PyPDF2 before OCR
- Reserve OCR for critical scanned documents
- Batch document extraction when possible"""

def _get_document_codes_section() -> str:
    """Document code decoder for documentBag responses.

    PROVENANCE (2026-08-30). Every code in the VERIFIED table below is printed
    with the description USPTO itself returned, from one of two sources:
      * live `documentCodeDescriptionText` read out of the documentBag of
        applications 11752072, 13975827, 14257618 and reexam 90/016,468
        (361 documents, 70 distinct codes) — this is the only source for the
        OUTGOING examiner codes, which are absent from the CSV;
      * `reference/Document_Descriptions_List.csv` (USPTO Document Description
        List, updated 2022-04-27) for the INCOMING applicant-filed codes.

    This replaced a hand-written table that carried three wrong glosses
    (OPEN_ITEMS #7): N417 was described as "Applicant's Response/Amendment"
    when it is the EFS acknowledgment receipt, SRFW as "Restriction/Election
    Requirement" when that is CTRS and SRFW is search information, and WFEE as
    "Issue Fee Due"/"Issue Fee Payment" when it is a fee worksheet and the
    issue fee payment is IFEE. CTAV (advisory action) was missing entirely
    although package_manager.py and the downloads view both referenced it.
    """
    return """## Document Code Decoder (DocumentBag Reference)

### ⚠️ What this decoder is and is not

Every code below is printed with the description **USPTO itself returned**, either as
`documentCodeDescriptionText` in a live documentBag (2026-08-30, 361 documents across
four applications) or from `reference/Document_Descriptions_List.csv` (USPTO Document
Description List, 2022-04-27). Where the two disagree the live value wins.

**Absence from this table proves nothing.** USPTO uses roughly 3,100 document codes and
this is a working subset. If a code you hold is not here, read the
`documentCodeDescriptionText` that came back next to it in the documentBag — that field
is the authority, not this list.

**Quick tip:** Use these codes with `PFW_get_application_documents(app_number, document_code='CODE')`

---

### 🔴 Examiner Communications (FROM USPTO)

**Office actions — read these with `PFW_get_oa_text`, not the document bag:**
- **CTNF** - Non-Final Rejection
- **CTFR** - Final Rejection
- **NOA** - Notice of Allowance and Fees Due (PTOL-85)
- **CTRS** - Requirement for Restriction/Election (this is the restriction requirement code)
- **CTAV** - Advisory Action (PTOL-303) — the examiner's response to an after-final
  amendment. Served by the OA text dataset (47,327 records, probed 2026-08-30).
- **CTEQ** - Ex parte Quayle action (served by the OA text dataset, 106,588 records)
- **NRES** / **NTC.A.NONCPL** - Notice to the applicant regarding a non-compliant or
  non-responsive amendment
- **ABN** - Notice of abandonment (served by the OA text dataset, 457 records)

**Citations & search:**
- **892** - List of references cited by examiner
- **SRNT** - Examiner's search strategy and results
- **SRFW** - Search information including classification, databases and other search
  related notes. **NOT a restriction requirement** — that is CTRS.
- **REF.OTHER** - Other reference - Patent/Application/Search Documents
- **FOR** - Foreign Reference

**Interviews & other examiner papers:**
- **EXIN** - Examiner Interview Summary Record (PTOL-413)
- **INTV.SUM.EX** - Examiner initiated interview summary (PTOL-413B)
- **M327** - Miscellaneous Communication to Applicant - No Action Count
- **N570** - Communication Re: Power of Attorney (PTOL-308)
- **ANE.I** - Amendment After Final or under 37 CFR 1.312, initialed by the examiner

---

### 🔵 Applicant Responses (FROM APPLICANT)

**Amendments and responses:**
- **A...** - Amendment/Request for Reconsideration-After Non-Final Rejection
- **A.NE** - Response After Final Action
- **A.PE** - Preliminary Amendment
- **A.NA** - Amendment after Notice of Allowance (Rule 312)
- **AMSB** - Amendment Submitted/Entered with Filing of CPA/RCE
- **SA..** - Supplemental Response or Supplemental Amendment
- **REM** - Applicant Arguments/Remarks Made in an Amendment
- **ELC.** - Response to Election / Restriction Filed (the reply to a CTRS)
- **N572** - Response Re: Informal Power of Attorney (PTOL-308)

**Requests & filings:**
- **RCEX** - Request for Continued Examination (RCE)
- **IDS** - Information Disclosure Statement (IDS) Form (SB08)
- **1449** - List of References cited by applicant and considered by examiner
- **136A** - Authorization for Extension of Time all replies (this is the extension code)
- **AF/D** - Affidavit submitted prior to Mar 15, 2013
- **PA..** - Power of Attorney
- **C.AD** - Change of Address
- **TRAN.LET** - Transmittal Letter
- **TRNA** - Transmittal of New Application

**Filing-system receipts — NOT applicant argument:**
- **N417** - **Electronic Filing System Acknowledgment Receipt.** A receipt EFS issues on
  submission. It is not a response, not an amendment, and carries no applicant argument.
  Its presence says a paper was filed that day; the paper itself is a different document.
- **N417.PYMT** - Electronic Fee Payment

---

### 📄 Patent Components and Application Parts

- **ABST** - Abstract
- **CLM** - Claims
- **SPEC** - Specification
- **DRW** - Drawings - only black and white line drawings
- **DRW.NONBW** - Drawings - other than black and white line drawings
- **DRW.SUPP** - Drawings - black and white line and/or other drawings
- **FWCLM** - Index of Claims
- **ADS** - Application Data Sheet
- **OATH** - Oath or Declaration filed
- **BIB** - Bibliographic Data Sheet
- **SCORE** - Placeholder sheet for supplemental content held in SCORE

---

### 📊 Fees, Issue and Administrative

- **WFEE** - **Fee Worksheet (SB06)** — a worksheet, NOT the issue fee payment
- **IFEE** - **Issue Fee Payment (PTO-85B)** — this is the issue fee code
- **IIFW** - Issue Information including classification, examiner, name, claim renumbering
- **ISSUE.NTF** - Issue Notification
- **MFEE.C.AD** - Maintenance Fee Address Change
- **APP.FILE.REC** - Filing Receipt
- **NTC.MISS.PRT** - Notice to File Missing Parts
- **NTC.PUB** - Notice of Publication
- **PEFN** - Pre-Exam Formalities Notice
- **PET.OP** - Petition for review by the Office of Petitions
- **PETDEC** - Petition Decision (the FPD MCP is the searchable source for decisions)

---

### 📑 Ex Parte Reexamination (90/xxx,xxx series)

- **RXREXO** - Determination — Reexam Ordered
- **RXNREQFD** - Notice of reexamination request filing date
- **RXNREQAU** - Notice of Assignment of Reexamination Request
- **RXOSUB.R** - Receipt of Original Ex Parte Request by Third Party
- **RXPATENT** - Copy of patent for which reexamination is requested
- **RXIDS.R** - Reexam - Info Disclosure Statement Filed by 3rd Party
- **RXAF/DR** - Reexam - Affidavit/Declaration/Exhibit Filed by 3rd Party
- **RXC/SR** - Reexam Certificate of Service
- **RXLITSR** - Reexam Litigation Search Conducted
- **RXTTLRPT** - Title Report
- **RXFILJKT** - Paper Reexam File Jacket is scanned

---

### 📌 Usage Examples

**Reading an office action — use the OA tools, not the document bag:**
```python
PFW_get_oa_rejections(application_number=app_number)                     # which OAs carry what
PFW_get_oa_text(application_number=app_number, action_type='CTFR')       # latest final rejection text
PFW_get_oa_text(application_number=app_number, action_type='CTNF', latest_only=False)  # all non-finals
PFW_get_oa_text(application_number=app_number, action_type='NOA')        # allowance reasoning
PFW_get_oa_text(application_number=app_number, action_type='CTAV')       # advisory action
PFW_get_oa_text(application_number=app_number, section='103')            # just the 103 discussion
```
One call each, no PDF, no scanning step. The document-bag calls below are for documents these
cannot serve, or when an actual PDF is wanted.

**Get examiner's key documents (bag path):**
```python
# Examiner's citations — the form itself; for the citation LIST prefer
# Citations_search_oa_citations_minimal, which has broader coverage
PFW_get_application_documents(app_number, document_code='892')

# Office action PDFs (for download; for the TEXT use PFW_get_oa_text)
PFW_get_application_documents(app_number, document_code='CTFR|CTNF')

# Allowance document PDF (for the TEXT use PFW_get_oa_text(action_type='NOA'))
PFW_get_application_documents(app_number, document_code='NOA')
```

**Get applicant's responses:**
```python
# All amendments
PFW_get_application_documents(app_number, document_code='A...')  # Wildcard matches all A. codes

# The actual argument, not the filing receipt: REM, not N417
PFW_get_application_documents(app_number, document_code='REM')

# IDS submissions (for Citations MCP integration)
PFW_get_application_documents(app_number, document_code='IDS|1449')

# RCE filings
PFW_get_application_documents(app_number, document_code='RCEX')
```

**Get patent components:**
```python
# Core patent documents
PFW_get_application_documents(app_number, document_code='ABST|CLM|SPEC|DRW')

# Claims evolution
PFW_get_application_documents(app_number, document_code='CLM|FWCLM')
```

---

### 📚 Document Direction Quick Reference

**INCOMING (FROM APPLICANT):** A..., A.NE, A.PE, REM, ELC., IDS, 1449, RCEX, 136A, PA..,
N417, N417.PYMT, IFEE, TRAN.LET
**OUTGOING (FROM USPTO):** CTNF, CTFR, NOA, CTRS, CTAV, CTEQ, 892, SRNT, SRFW, EXIN,
INTV.SUM.EX, M327, NTC.A.NONCPL
**SYSTEM GENERATED / RECORD:** BIB, IIFW, ISSUE.NTF, APP.FILE.REC, NTC.PUB, SCORE

Direction is reported per document as `directionCategory`; use that rather than inferring
it from the code.

---

### 🔍 Finding Rare/Unlisted Codes

For the applicant-filed code list (278 codes), see
`reference/Document_Descriptions_List.csv` (USPTO Document Description List, updated
2022-04-27). It does NOT contain the outgoing examiner codes — those were read live from
documentBag responses.

**Note:** This decoder excludes:
- Petition codes (see FPD MCP for petition-specific documents)
- PTAB codes (see PTAB MCP for trial proceedings)
- PCT/International codes (focus on US prosecution)"""

def _get_workflows_pfw_section() -> str:
    """PFW-only workflows section"""
    return """## Patent Attorney Workflows (PFW Only)

### Litigation Research Workflow
**Scenario:** Responding to validity challenge or preparing patent enforcement

**Steps:**
1. **Find target patent**: `PFW_search_applications_balanced(query='applicationNumberText:16123456')`
2. **Triage the office actions**: `PFW_get_oa_rejections(application_number='16123456')` — which OAs carry 101/102/103/112, Alice flags, citation counts
3. **Read the examiner's reasoning directly**: `PFW_get_oa_text(application_number='16123456', action_type='NOA')` for the allowance rationale and `action_type='CTFR'` for the final rejection. One call each, no document bag and no scanning step. Use `section='103'` to isolate one rejection.
4. **Analyze prior art**: `Citations_search_oa_citations_minimal` for the raw 892/1449 cited-art lists (broadest coverage); pull the 892 document itself via `PFW_get_application_documents(document_code='892')` only if the form image is needed
5. **Get remaining prosecution docs**: `PFW_get_application_documents(app_number='16123456')` for amendments and applicant responses, which the OA tools do not serve
6. **Compare arguments**: Extract applicant responses to understand prosecution strategy

**Key Intelligence:** Examiner's allowance reasoning vs. challenger's arguments

### Due Diligence Workflow
**Scenario:** M&A patent portfolio assessment

**Steps:**
1. **Portfolio discovery**: `PFW_search_applications_minimal(applicant_name='Target Company', limit=100)`
2. **Quality assessment**: Use balanced search for high-value patents
3. **Red flag detection**: Look for multiple rejections, long prosecution, revival petitions. `PFW_get_oa_rejections` across the sampled applications is the cheapest way to score rejection mix at portfolio scale.
4. **Document analysis**: `PFW_get_oa_text(action_type='NOA')` and `action_type='CTFR'` for prosecution quality — direct text in one call, so this scales across a portfolio in a way the bag plus OCR path does not
5. **Risk scoring**: Combine prosecution timeline + examiner analysis + document quality

**Risk Indicators:** Multiple CTFRs, long timeline, examiner interview frequency"""

def _get_errors_section() -> str:
    """Common error patterns and troubleshooting"""
    return """## Common Error Patterns & Solutions

### Search Errors

#### "No results found"
**Causes:**
- Incorrect application number format
- Patent not yet published or granted
- Search scope too narrow

**Solutions:**
- Use `PFW_search_applications_minimal` with broader query
- Try inventor or applicant name search
- Check application status and publication dates

#### "Got data for the wrong patent or application"
**Cause:** The 8-digit number you passed was ambiguous. It is both a valid granted patent
number and a valid application serial, and resolution queries the patent lane first, so an
application serial can land on an unrelated granted patent.

**Solutions:**
- Re-call with the slash-comma serial format (`11/752,072`) or `content_type='application'`
- Check `identifier_resolved_as`, `identifier_note` and `identifier_lanes_tried` in the
  response before using the data; `identifier_ambiguous: true` means the input could have
  gone either way
- Full writeup: `PFW_get_guidance(section='documents')`, "Identifier formats"

#### "Field not recognized"
**Causes:**
- Incorrect field name syntax
- Custom field not in available set

**Solutions:**
- Use convenience parameters instead (applicant_name, examiner_name)
- Check field_configs.yaml for available custom fields
- Use preset field sets (minimal/balanced)

### Document Access Errors

#### "Document not available"
**Causes:**
- Document not yet digitized (pre-2001 applications)
- Access restrictions on certain document types

**Solutions:**
- Try XML content first for patents/applications
- Use document download for browser access
- Check document metadata for availability indicators

#### "Proxy links don't work"
**Cause:** Proxy server not started before generating links

**Solution:** Document download tools automatically start proxy server"""

def _get_family_section() -> str:
    """Family graph and patent term adjustment guidance"""
    return """## Patent Family & Term Adjustment

### PFW_get_family — continuity + foreign priority as ONE normalized graph

Returns a compact structure, not the raw USPTO bags:
- `nodes`: `{application_number, patent_number, filing_date, status, status_code, is_queried}`
- `edges`: `{parent_app, child_app, relation_type, claim_parentage_type_code, description}` —
  `relation_type` is the USPTO claimParentageTypeCode (CON, CIP, DIV, ...) and `description`
  its official wording ("is a Division of"). The raw code is preserved alongside it.
- `parents` / `children`: the direct relations of the queried application
- `roots`: earliest ancestors, found by walking the parent chain — NOT by taking the first
  entry of parentContinuityBag, which is neither the only parent nor date-ordered
- `foreign_priority`: `{country, application_number, filing_date}` per claim
- `notes`: the per-direction emptiness statements described below

### Per-direction emptiness — read this before concluding "no family"

The ODP /continuity response can carry ONLY childContinuityBag or ONLY parentContinuityBag:
an original application has no parents, a childless one has no children. Each direction is
reported separately and an empty list is an ANSWER, not missing data. `notes` says which
case applies ("USPTO returned no childContinuityBag ... it is an answer, not missing data").
Never read `parents: []` as "the family lookup failed", and never read it as "no family" —
check `children` too.

Foreign priority is likewise stated explicitly: not requested, unavailable (the call
failed), or none claimed. Absence with `include_foreign_priority=False` says nothing.

### Cost: one call vs depth 2

- `max_depth=1` (default) — ONE /continuity call, plus one /foreign-priority call unless
  you pass `include_foreign_priority=False`. Direct parents and children only.
- `max_depth=2` — one ADDITIONAL /continuity call per direct parent and child, so a family
  with five direct relations costs about six calls. It buys grandparents, siblings and
  grandchildren, and it back-fills the queried application's own filing date, patent number
  and status (depth 1 cannot know those: the queried app appears in its own bags only as a
  bare number). The fan-out is capped at 12 expansions per call; `expansion_note` says when
  the cap trimmed the walk. Depth is hard-capped at 2 — there is no unbounded family crawl.

Start at depth 1. Step up only when the direct relations are not enough.

### Balanced-tier family awareness

`PFW_search_applications_balanced` and `PFW_search_inventor_balanced` now return
`parentContinuityBag.parentApplicationNumberText`, `childContinuityBag.childApplicationNumberText`
and the top-level `foreignPriorityBag` — enough to SPOT that a hit has a family without the
bag bloat. Use PFW_get_family when the structure itself matters (relation types, ancestry,
generations). The minimal tiers are unchanged.

Field-name trap: `foreignPriorityBag` is TOP-LEVEL in the ODP response. An
`applicationMetaData.foreignPriorityBag` path silently returns nothing.

### Priority dates: use earliest_priority_date, not effectiveFilingDate

`PFW_get_family` computes `earliest_priority_date` and `priority_basis` from the chain it
returns. `applicationMetaData.effectiveFilingDate` is NOT that date — see
`PFW_get_guidance(section='fields')` for the live counter-example and the rule.

### PFW_get_term_adjustment — PTA from the ODP /adjustment endpoint

Source is the USPTO ODP `/adjustment` endpoint, the office's own PTA accounting. Returns:
- `adjustment`: total days plus the A / B / C delay components, applicant delay, overlapping
  and non-overlapping days, and the office adjustment delay
- `history`: most-recent-first PTA events, capped at `max_events` (default 20, max 200), with
  `history_returned`, `history_total` and `history_truncated` so the full size is always visible.
  A normal prosecution carries 60+ events, most of them docketing steps.

**No expiration date is computed, by design.** Expiration turns on the 20-year term from the
earliest US filing/priority date, terminal disclaimers, maintenance-fee status and any patent
term EXTENSION (PTE under 35 U.S.C. 156) — none of which this endpoint carries. Combine
`adjustment_total_days` with filing/priority dates (search tools, PFW_get_family) and check
the file wrapper for terminal disclaimers before stating a term.

PTA is computed at issuance: pending and abandoned applications normally return no
patentTermAdjustmentData, which comes back `success=True` with an explanatory note — not an error.

### Typical sequence

1. `PFW_search_applications_minimal` / `_balanced` → applicationNumberText (balanced also
   flags whether continuity and foreign priority exist)
2. `PFW_get_family(application_number)` → structure, relation types, ancestry
3. `PFW_get_term_adjustment(application_number)` → PTA days for the granted members
4. `PFW_get_oa_rejections` / `PFW_get_oa_text` on the family member whose prosecution matters"""

def _get_fields_section() -> str:
    """Field selection strategies and context reduction"""
    return """## Field Selection & Context Reduction

### What the search index actually covers (read before promising a keyword search)

The USPTO ODP search behind every `PFW_search_*` tool is **bibliographic**: title,
inventor and applicant/assignee names, examiner, art unit, classification (CPC and
USPC), application type, status, and filing / grant / publication dates.

It does **NOT** index abstracts, claims or specifications. A free-text `query=` string
matches the title and other bibliographic strings only — there is no full-text lane in
this server, and a term appearing only in the body of a patent will not be found here.
A loose free-text query also returns loose matches, so treat title keywords as a
supplement, never as the subject-matter strategy.

**For subject matter, search by classification.** CPC is the effective handle:
```python
# Subclass prefix wildcard
query="applicationMetaData.cpcClassificationBag:H04L*"

# A full group symbol must reproduce the API's internal space padding
query='applicationMetaData.cpcClassificationBag:"C08G  77/06"'
```
Take the CPC symbol from a known-good hit (the balanced tiers return
`cpcClassificationBag`) rather than guessing one, then narrow with art unit, applicant,
status and date filters.

The prosecution TEXT this server does serve is a different surface: office-action text
via `PFW_get_oa_text` (OAs mailed roughly 2008 forward) and granted/published claims and
abstract via `PFW_get_patent_or_application_xml`. Neither is reachable from a search query.

### Search limit ceiling: 100 per call, page with offset

Every `PFW_search_*` tool accepts `limit` **1-100**. That is not a policy
choice — it is what the USPTO search endpoint clamps `pagination.limit` to, so
a larger number was never going to return more rows. (Until 2026-08-21 the
tools accepted up to 500 and the response envelope then echoed the number you
asked for, so a `limit=200` search looked like it had returned 200 records when
it had returned 100.)

A `limit` **above** 100 is CLAMPED, not rejected: the search runs at 100 and
the response carries `limit_clamped` {`requested`, `applied`, `note`} alongside
the usual `paging` block. The key is absent when the clamp did not fire. A
`limit` below 1 is still a 400 — there is no honest value to clamp it to.

Every search response now carries a `paging` block with `limit_requested`,
`limit_applied`, `offset`, `returned`, `total`, `has_more` and `next_offset`.
To walk a result set larger than 100, feed `paging.next_offset` back as
`offset=`. See `PFW_get_guidance(section='limits')` for the full contract.

The inventor tools fan out over several name variants and de-duplicate, so they
also report `queries_generated` vs `queries_executed`, `sub_query_limit` and
`unique_applications_discovered` — a short result set there does not mean the
portfolio is exhausted.

### Date fields: effectiveFilingDate is NOT the priority date

`applicationMetaData.effectiveFilingDate` is the **371 national-stage ENTRY date** for a
national-stage case and the **child's own filing date** for a continuation. It is not the
earliest priority date, and any AIA or prior-art cutoff built on it inverts. Live example
(2026-08-30): application 13975827 / US 9,135,462 reports `effectiveFilingDate` 2013-08-26
while its `parentContinuityBag` carries provisional 61/694,492 filed 2012-08-29.

Use `earliest_priority_date` instead. The balanced search tiers and `PFW_get_family` both
compute it as the MINIMUM over the foreign priority bag, the domestic parent chain
(provisionals included, `claimParentageTypeCode` = PRO) and the application's own filing
date, and report `priority_basis` naming which of those produced the winning date. It is
computed only from the links present in that response — `PFW_get_family(max_depth=2)` when
the chain runs through a grandparent.

### AIA status: firstInventorToFileIndicator, and its namesake

`applicationMetaData.firstInventorToFileIndicator` is served as the STRING "Y"/"N" and is
enabled in both balanced tiers as of 2026-08-30 (no tier returned AIA status before that).

**Namesake warning:** `parentContinuityBag[]` and `childContinuityBag[]` entries carry
their OWN `firstInventorToFileIndicator`, a BOOLEAN describing THAT related application.
Do not read a continuity-bag boolean as the queried application's AIA status.

### Fields the API does not populate

- **`examinerData`** — never populated for these records. PFW's own examiner handle is
  `applicationMetaData.examinerNameText` (populated, and in every tier) plus
  `groupArtUnitNumber`. The same-named block requested by the PTAB MCP's appeals_balanced
  tier is also never returned, so examiner-level comparables cannot be built from a PTAB
  appeal search; take the primary examiner off the PTOL-90A cover sheet instead.
- **`assignmentBag`** — requested by both balanced tiers but frequently returned EMPTY for
  patents that ARE assigned of record (observed 2026-08-29 on US 11,333,007, Reel 048880 /
  Frame 0804, empty on two calls). **An empty assignmentBag is not evidence of no
  assignment.** The working ownership reads are `applicationMetaData.firstApplicantName`
  and `applicationMetaData.applicantBag`, plus the Rule 3.73(c) statement in the file
  wrapper. For a chain of title, go to USPTO Assignment Search, which this MCP does not
  wrap.

### Progressive Disclosure Strategy

#### Stage 1: Discovery (95-99% reduction)
**Minimal Search (15 preset fields ~500 chars/result):**
- `PFW_search_applications_minimal` with default fields
- Good for 20-50 results

**Ultra-Minimal (2-3 custom fields ~100 chars/result):**
- `fields=["applicationNumberText", "inventionTitle"]`
- Perfect for 50-100 results in one call (page with `offset=` past 100)
- 99% context reduction vs balanced

#### Stage 2: Analysis (85-95% reduction)
**Balanced Search (21 fields ~2KB/result):**
- Cross-MCP integration fields
- Detailed metadata for user-selected applications
- Limit to 10-20 results

### Essential Field Combinations

#### Cross-MCP Integration
```python
# For PTAB integration
fields=["applicationNumberText", "patentNumber", "examinerNameText", "groupArtUnitNumber"]

# For Citations integration
fields=["applicationNumberText", "examinerNameText", "groupArtUnitNumber", "filingDate"]

# For FPD integration
fields=["applicationNumberText", "applicationStatus", "examinerNameText"]
```

### Convenience Parameters vs Custom Fields

#### Use Convenience Parameters When:
- Simple searches without complex Boolean logic
- Standard filtering (applicant, inventor, examiner, date ranges)
- New user or quick exploration

#### Use Custom Fields When:
- Ultra-minimal context usage required
- Specific workflow requirements
- Processing 50+ results efficiently"""

def _get_cost_section() -> str:
    """Extraction and context efficiency strategies"""
    return """## Extraction & Context Efficiency Strategies

### Document Extraction Tiers

#### Fast Structured Methods (Always Try First)
1. **Office Action Text**: `PFW_get_oa_text`
   - Any CTNF, CTFR, NOA or CTRS mailed roughly 2008 onward
   - ONE call, already-digital text, no document bag and no scanning step at all
   - One call instead of the bag-plus-extraction pair, and no scanning step for the same document. Triage first with `PFW_get_oa_rejections`, whose response is smaller still.
   - `section='101'|'102'|'103'|'112'` narrows further when only one rejection matters, but note the section sub-documents are sparsely populated and an empty section falls back to the full body

2. **XML Content**: `PFW_get_patent_or_application_xml`
   - Patents and published applications
   - Structured data with claims, description, citations
   - Fastest access, highest fidelity

3. **PyPDF2 Extraction**: Automatic first tier in document tools
   - Works for 80%+ of patent documents
   - Fast text extraction from text-based PDFs
   - No OCR round-trip needed

#### OCR (Only When Necessary)
**OCR**
- The slow path. Never use it on an office action `PFW_get_oa_text` can serve.
- Used only for scanned/poor quality documents
- Automatic quality detection prevents unnecessary OCR passes
- Slower than the text tiers; reserve for true scans

#### Worked comparison (same non-final rejection)
- OA path: `PFW_get_oa_text(application_number=..., action_type='CTNF')` = 1 call, no OCR, examiner's text returned directly.
- Bag path: `PFW_get_application_documents(...)` to find the document identifier, then `PFW_get_document_content_with_ocr` on the resulting multi-page PDF = 2 calls plus an OCR pass whenever that PDF is a scan.

### API Call Optimization

#### Progressive Disclosure (95% context reduction)
```python
# Instead of expensive balanced search for discovery
results = PFW_search_applications_balanced(query="AI healthcare", limit=50)  # 100KB context

# Do efficient progressive disclosure
discovery = PFW_search_applications_minimal(query="AI healthcare", limit=50)  # 25KB context
# User selects 5 results
detailed = PFW_search_applications_balanced(selected_apps, limit=5)  # 10KB context
# Total: 35KB vs 100KB (65% reduction)
```

### Strategic Document Selection
1. **NOA** (Notice of Allowance): Examiner's final reasoning — read via `PFW_get_oa_text(action_type='NOA')`
2. **Final CTFR**: Last office action with complete analysis — read via `PFW_get_oa_text(action_type='CTFR')`
3. **892** (Examiner Citations): Prior art search methodology — the citation LIST is better served by `Citations_search_oa_citations_minimal`; pull the document only for the form image
4. **Key applicant responses**: amendments and remarks, which the OA tools do not cover — this is genuine document-bag work"""

def _get_workflows_ptab_section() -> str:
    """PTAB integration workflows"""
    return """## PTAB Integration Workflows

### PTAB Identifier Formats
**Trials** (IPR/PGR/CBM/DER): `IPR2025-00895`, `PGR2025-00456`, `CBM2025-00789`, `DER2025-00012`
**Appeals**: `2025000943` (10-digit numeric, NO hyphens)
**Interferences**: `106048` (6-digit numeric)

### PTAB to PFW Linking (Trials Focus)
**Scenario:** Starting from PTAB trial proceeding, need prosecution history

**Workflow:**
1. **Find PTAB trial**: `PTAB_search_trials_balanced(patent_number='11123456')`
2. **Extract application number** from trial metadata (`respondentData.applicationNumber`)
3. **Get prosecution history**: `PFW_search_applications_balanced(query='applicationNumberText:16123456')`
4. **Get the examiner's allowance reasoning**: `PFW_get_oa_text(application_number='16123456', action_type='NOA')` — this is the text you actually need to set against the PTAB record, and it comes back in one call with nothing in between. Add `PFW_get_oa_rejections` to see what the examiner had rejected before allowing.
5. **Other prosecution documents**: `PFW_get_application_documents(app_number='16123456')` for amendments and applicant responses
6. **Compare reasoning**: Examiner's NOA rationale vs PTAB Institution/FWD analysis — the classic question is whether the PTAB petition's art was before the examiner

**Key Linking Fields:**
- `respondentData.applicationNumber` (PTAB → PFW)
- `respondentData.patentNumber` (PTAB → PFW)
- `applicationNumberText` (PFW → PTAB)
- `patentNumber` (PFW → PTAB)

**Appeals/Interferences**: Use `PTAB_search_appeals_minimal()` or `PTAB_search_interferences_minimal()` for non-trial proceedings"""

def _get_workflows_fpd_section() -> str:
    """FPD integration workflows"""
    return """## FPD Integration Workflows

### FPD Red Flag Detection
**Scenario:** Identify prosecution quality issues via petition history

**Workflow:**
1. **Portfolio scan**: `PFW_search_applications_minimal(applicant_name='Target', limit=100)`
2. **FPD check**: For each application, `FPD_Search_petitions_by_application(app_number)`
3. **Red flag analysis**: Identify denied petitions, revival petitions, appeal petitions
4. **Prosecution correlation**: For applications with petition issues, `PFW_get_oa_rejections` then `PFW_get_oa_text(action_type='CTFR')` shows what the examiner was actually holding against the applicant when the petition was filed. Direct text, so this scales across the flagged set.
5. **Risk assessment**: Combine petition history + prosecution timeline analysis

**High-Risk Indicators:**
- Denied petitions (serious prosecution issues)
- Revival petitions (missed deadlines)
- Multiple appeal petitions (examiner relationship problems)"""

def _get_workflows_citations_section() -> str:
    """Citations integration workflows"""
    return """## Citations Integration Workflows

### Citation-Enhanced Prior Art Analysis
**Scenario:** Advanced prior art research using examiner citation intelligence

### The Citations MCP has TWO lanes — pick deliberately

**Lane 1: raw OA citations (`Citations_search_oa_citations_minimal` / `Citations_search_oa_citations_balanced`).**
The Form 892 (examiner-cited) and Form 1449/IDS (applicant-disclosed) citation lists as filed.
**BROADER coverage than the enriched index** — this is the default sweep when the question is
"what art was cited", the examiner-vs-applicant split, category distribution (US patents /
foreign / NPL), or citation density. `Citations_get_oa_citation_fields` lists the fields.

**Lane 2: enriched citations (`Citations_search_citations_minimal` / `_balanced`, `Citations_get_citation_details`).**
AI-extracted passage locations, claim mapping and quality scores. **Narrower coverage** — use it
only on the selected references that matter, after the sweep has told you which those are.
Its extractions are AI-derived: verify a passage against the source document before relying on it.
`Citations_get_citation_statistics` gives aggregate trends (art-unit level and similar).

Prefer Lane 1 first for completeness, then escalate selected records to Lane 2 for depth. If a
reference is missing from Lane 2, that is a coverage gap in the enriched index, not evidence the
reference was never cited — check Lane 1 before concluding anything.

Both Citations lanes carry the Oct 1, 2017 floor. `PFW_get_oa_text` does not, so for older
prosecution you can still read what the examiner said about the art even when neither citation
lane has structured records for it.

**Workflow:**
1. **Technology Discovery**: `PFW_search_applications_minimal(query='autonomous vehicle', art_unit='3661', limit=50)`
2. **Citation sweep (Lane 1)**: `Citations_search_oa_citations_minimal(application_number=...)` for the complete cited-art list
3. **Examiner Intelligence**: Focus on examiner-cited references; escalate the ones that matter to Lane 2 for passage-level detail
4. **Read how the art was applied**: `PFW_get_oa_text(application_number=..., section='102')` and `section='103'` — the examiner's own application of those references, no OCR round trip
5. **Art Unit Patterns**: Identify frequently cited references in specific art units
6. **Effectiveness Assessment**: Correlate citation patterns with prosecution outcomes

**Enhanced Insights:** Citation patterns reveal examiner search preferences and reference effectiveness"""

def _get_workflows_complete_section() -> str:
    """Complete four-MCP lifecycle workflows"""
    return """## Complete Four-MCP Lifecycle Analysis

### Complete M&A Due Diligence
**Scenario:** Comprehensive patent intelligence across all USPTO databases

**Four-MCP Integration Workflow:**
1. **Portfolio Discovery (PFW)**: `PFW_search_applications_minimal(applicant_name='Target Company', filing_date_start='2015-01-01', limit=100)`
2. **Citation Intelligence (Citations)**: Sweep with `Citations_search_oa_citations_minimal` (raw 892/1449, broadest coverage), then escalate selected references to the enriched lane. Both lanes cover OAs from Oct 1, 2017.
3. **FPD Risk Assessment (FPD)**: Check procedural irregularities and petition history
4. **PTAB Challenge Analysis (PTAB)**: Assess post-grant challenge exposure for granted patents
5. **Prosecution Intelligence (PFW)**: `PFW_get_oa_rejections` to score rejection mix across the portfolio, then `PFW_get_oa_text` on the applications that matter. Drop to `PFW_get_application_documents` + `PFW_get_document_content_with_ocr` only for non-OA documents and pre-2008 office actions.
6. **Comprehensive Reporting**: Integrate findings across all four data sources

**Enhanced Risk Scoring Matrix:**
- **Technical Strength**: Claim scope, prosecution quality, prior art landscape
- **Legal Enforceability**: Citation thoroughness, procedural cleanliness
- **Challenge Exposure**: PTAB proceedings history and outcomes
- **Procedural Issues**: FPD petition patterns and denial history"""

def _get_workflows_pinecone_section() -> str:
    """Pinecone RAG/Assistant domain-based strategic search integration"""
    return """## Pinecone RAG/Assistant Integration - Domain-Based Strategic Search

### Overview: Why Domain-Based Search?

**Problem with Generic Technology Searches:**
- RAG database contains MPEP, case law, examination procedures (legal framework)
- RAG does NOT contain technology-specific prior art
- Generic searches like "catalytic converter bend radius MPEP" return low-value generic guidance

**Solution: Domain-Based Legal Framework Searches:**
- Focus RAG on legal issue (§101, §103, §112) instead of technology
- Get targeted MPEP sections and case law for specific vulnerabilities
- Improved RAG value: 5-10% → 40-60% (estimated)

**Key Principle:**
- **Pinecone RAG/Assistant**: Legal framework (MPEP, case law, procedures) organized by domain
- **USPTO Citations MCP**: Technology-specific prior art

---

### 9 Patent Law Domains

#### Legal Issue Domains (Primary)

**1. section_101_eligibility** - Alice/Mayo Framework
- **When to Use**: Software patents, AI/ML inventions, business methods, abstract idea challenges
- **Search Focus**: Alice/Mayo two-step framework, technological improvement, inventive concept, judicial exceptions
- **Example Searches**: "Section 101 Alice Mayo two-step framework abstract idea", "practical application technological improvement"

**2. section_103_obviousness** - KSR/Graham Factors
- **When to Use**: Combination rejections, motivation to combine issues, mechanical/chemical patents
- **Search Focus**: KSR rationales (7 types), Graham factors, secondary considerations, teaching away
- **Example Searches**: "Section 103 KSR motivation to combine obviousness rationales", "Graham factors scope prior art differences POSITA"

**3. section_112_requirements** - Specification Requirements
- **When to Use**: Indefiniteness challenges ("substantially", "about"), enablement issues, written description
- **Search Focus**: Nautilus standard, written description possession, enablement Wands factors, means-plus-function
- **Example Searches**: "Section 112 indefiniteness Nautilus reasonable certainty", "written description possession requirement"

**4. section_102_novelty** - Anticipation
- **When to Use**: Single reference rejections, inherent disclosure arguments, anticipation challenges
- **Search Focus**: Anticipation standards, inherent disclosure, prior art effective dates (AIA vs pre-AIA)
- **Example Searches**: "Section 102 anticipation single reference prior art disclosure", "inherent disclosure anticipation"

**5. claim_construction** - Claim Interpretation
- **When to Use**: Phillips standard analysis, means-plus-function claims, functional claiming, prosecution history estoppel
- **Search Focus**: Phillips v. AWH standard, intrinsic/extrinsic evidence, prosecution history limits
- **Example Searches**: "claim construction Phillips intrinsic extrinsic evidence", "prosecution history estoppel argument-based"

**6. ptab_procedures** - PTAB Trial Standards
- **When to Use**: IPR/PGR proceedings, PTAB appeal standards, institution decisions
- **Search Focus**: IPR petition standards, BRI vs Phillips, PTAB estoppel rules
- **Example Searches**: "IPR petition institution decision preponderance evidence BRI", "PTAB claim construction broadest reasonable interpretation"

#### Technology-Specific Domains (Secondary)

**7. mechanical_patents** - Mechanical/Manufacturing
- **When to Use**: TC 3600/3700 patents, manufacturing processes, mechanical devices
- **Search Focus**: Mechanical obviousness, design-around strategies, manufacturing process examination
- **Example Searches**: "mechanical device patent obviousness design around", "manufacturing process method claims patent examination"

**8. software_patents** - Software/AI Technology
- **When to Use**: TC 2100/2400 patents, computer-implemented inventions, AI/ML systems
- **Search Focus**: Software abstract idea analysis, AI practical application, business method eligibility
- **Example Searches**: "software patent 101 abstract idea Alice framework computer-implemented", "AI machine learning patent practical application"

**9. general_patent_law** - Default/Fallback
- **When to Use**: Unknown issues, multiple vulnerabilities, comprehensive overview
- **Search Focus**: General examination procedures, broad legal framework
- **Example Searches**: "{technology} patent examination MPEP guidance", "{technology} patent law legal framework precedent"

---

### Automatic Vulnerability Detection (Patent Invalidity Prompt)

The patent invalidity analysis prompt automatically detects vulnerabilities from prosecution history and selects the appropriate domain:

**Detection Indicators:**
```python
# § 102 Anticipation: "anticipates", "anticipated by", "102", "single reference"
→ Domain: section_102_novelty

# § 103 Obviousness: "obvious", "103", "combination", "motivation to combine", "KSR"
→ Domain: section_103_obviousness

# § 101 Eligibility: "abstract idea", "software", "computer-implemented", TC 2100/2400
→ Domain: section_101_eligibility

# § 112 Indefiniteness: "substantially", "approximately", "about", "configured to"
→ Domain: section_112_requirements

# Claim Construction: "means for", "means plus function", "112(f)", "112(6)"
→ Domain: claim_construction
```

---

### Usage Examples: Before vs After Domains

#### Example 1: § 103 Obviousness (Catalytic Converter Patent)

**❌ Before (Generic Technology Search):**
```python
strategic_multi_search(
    technology='catalytic converter exhaust pipe bend radius manufacturing process patent eligibility obviousness'
)
# Returns: "catalytic converter bend radius patent examination MPEP" (not useful)
# Value: 5-10% (generic principles user already knows)
```

**✅ After (Domain-Based Legal Framework):**
```python
strategic_multi_search(
    technology='catalytic converter exhaust system',
    domain='section_103_obviousness',
    topK=5,
    rerankerTopN=2
)
# Returns:
# - "Section 103 KSR motivation to combine obviousness rationales"
# - "Graham factors scope prior art differences POSITA"
# - "Section 103 secondary considerations commercial success teaching away"
# - "Section 103 combination prior art references motivation"
# Value: 40-60% (focused legal framework for exact issue)
```

#### Example 2: § 101 Software Patent Eligibility

**✅ Domain-Based Search:**
```python
strategic_multi_search(
    technology='AI-based medical diagnosis method',
    domain='section_101_eligibility',
    topK=5
)
# Returns:
# - "Section 101 Alice Mayo two-step framework abstract idea"
# - "Section 101 practical application technological improvement"
# - "Section 101 inventive concept significantly more Alice step two"
# - "Section 101 judicial exceptions abstract idea natural phenomenon"
```

#### Example 3: § 112(b) Indefiniteness

**✅ Domain-Based Search:**
```python
strategic_multi_search(
    technology='wireless proximity zone authentication system',
    domain='section_112_requirements',
    topK=5
)
# Returns:
# - "Section 112 indefiniteness Nautilus reasonable certainty"
# - "Section 112 paragraph f means-plus-function corresponding structure"
# - "Section 112 written description possession requirement"
# - "Section 112 enablement undue experimentation Wands factors"
```

---

### Cross-Workflow Integration

**Patent Invalidity Analysis (Primary Workflow):**
1. **PFW MCP**: Get prosecution history → Detect vulnerability
2. **Pinecone RAG/Assistant**: Execute domain-specific strategic search → Get legal framework
3. **Citations MCP**: Get technology-specific prior art → Prior art landscape
4. **PTAB MCP**: Get PTAB decisions → Real-world precedents
5. **FPD MCP**: Get petition history → Procedural issues

**M&A Due Diligence with Legal Framework:**
1. **PFW**: Portfolio discovery → Identify patents
2. **Pinecone RAG**: Domain searches for each patent's primary vulnerability
3. **Citations**: Examiner search patterns
4. **PTAB**: Challenge exposure assessment

**Litigation Research with Domain Focus:**
1. **PFW**: Prosecution history → Identify legal weaknesses
2. **Pinecone RAG**: Domain-specific legal framework for vulnerability
3. **PTAB**: Find IPR decisions on similar legal issues
4. **Citations**: Examiner's prior art thoroughness

---

### Domain Selection Decision Tree

```
Start: Analyze prosecution history from PFW
│
├─ Examiner cited "abstract idea" or TC 2100/2400?
│  → Domain: section_101_eligibility
│
├─ Examiner said "obvious" or "combination" or "KSR"?
│  → Domain: section_103_obviousness
│
├─ Examiner said "anticipates" or "single reference"?
│  → Domain: section_102_novelty
│
├─ Claims use "substantially", "approximately", "about"?
│  → Domain: section_112_requirements
│
├─ Claims use "means for" or functional language?
│  → Domain: claim_construction
│
├─ Facing IPR/PGR or PTAB challenge?
│  → Domain: ptab_procedures
│
├─ Mechanical/manufacturing invention?
│  → Domain: mechanical_patents
│
├─ Software/AI invention?
│  → Domain: software_patents
│
└─ Unknown or multiple issues?
   → Domain: general_patent_law (fallback)
```

---

### Tool Integration

**Pinecone RAG MCP:**
```python
# Domain-specific strategic multi-search
strategic_multi_search(
    technology=invention_title,
    domain='section_103_obviousness',
    topK=5,
    rerankerTopN=2
)
```

**Pinecone Assistant MCP:**
```python
# Domain-specific context retrieval with strategic search
assistant_strategic_multi_search_context(
    query=invention_title,
    domain='section_103_obviousness',
    top_k=5,
    snippet_size=2048,
    max_searches=4,
    temperature=0.3
)

# Single domain-specific query
assistant_context(
    query='KSR motivation to combine predictable results',
    top_k=5,
    snippet_size=2048
)
```

---

### Benefits Summary

**Before Domain System:**
- 5-10% value from RAG
- Generic legal principles user already knows
- Technology terms don't match legal framework content
- RAG searches compete with technology prior art (Citations MCP)

**After Domain System:**
- 40-60% estimated value from RAG
- Specific MPEP sections and case law for exact legal issue
- Technology-agnostic legal framework matches RAG content
- Clear separation: RAG = legal framework, Citations = prior art

**Strategic Advantage:**
- Automatic vulnerability detection from prosecution history
- Focused legal research on primary issue
- Cross-MCP integration for complete analysis
- Scalable to new domains (appeals, litigation, etc.)"""

def _get_advanced_section() -> str:
    """Advanced workflows and optimization"""
    return """## Advanced Workflows & Optimization

### Patent Family Analysis
**Multi-application analysis for related inventions**

**Advanced Workflow:**
1. **Family Discovery**: Search by inventor, assignee, priority claims, or technology keywords
2. **Relationship Mapping**: Identify continuations, divisionals, continuations-in-part
3. **Prosecution Comparison**: Analyze different examiner approaches across family members
4. **Claim Evolution**: Track claim scope changes and strategic amendments
5. **Strategic Insights**: Identify strongest family member and optimal prosecution paths
6. **Cross-Reference Analysis**: Use PTAB/FPD data to assess family-wide vulnerabilities

**Strategic Value:** Comprehensive family strategy with prosecution pattern optimization"""



def _get_limits_section() -> str:
    """Active response budgets + the _bounds/_window marker contract.

    This is the server's configuration/status surface for response sizing: the
    numbers are read LIVE from the process environment via
    shared/response_bounds.py, so what the section prints is what the guard is
    actually enforcing right now.
    """
    import os

    from .api.enhanced_client import EnhancedPatentClient, pypdf_max_pages
    from .shared.response_bounds import bounds_config

    config = bounds_config()
    try:
        ocr_max_pages = int(os.getenv("MISTRAL_OCR_MAX_PAGES", "50"))
    except (TypeError, ValueError):
        ocr_max_pages = 50
    return f"""## Response Size Limits and Markers

### Active configuration (live, this process)

| Setting | Value | Environment variable |
| --- | --- | --- |
| Guard enabled | {config["enabled"]} | `{config["env"]["enabled"]}` |
| Structured response budget | {config["max_response_chars"]:,} chars | `{config["env"]["max_response_chars"]}` |
| Document content budget | {config["max_content_chars"]:,} chars | `{config["env"]["max_content_chars"]}` |
| Native text-layer (PyPDF2) page cap per document | {pypdf_max_pages()} pages | `PYPDF_MAX_PAGES` |
| OCR page cap per document | {ocr_max_pages} pages | `MISTRAL_OCR_MAX_PAGES` |
| Search limit ceiling | {EnhancedPatentClient.MAX_SEARCH_LIMIT} | (this server's own ceiling; an over-ceiling `limit` is clamped and reported in `limit_clamped`) |

Budgets are CHARACTER counts of the serialized response, not token estimates:
an oversized tool result is replaced by a client-side truncation error that
this server never sees, so the model would get no data and no way to recover.
The guard trades records or fields for a usable response plus a recovery note.

### `_bounds` - the response was reduced to fit

Present ONLY when the guard actually changed the response. Its absence means
nothing was dropped.

```json
"_bounds": {{
  "applied": true,
  "reason": "size",
  "size_chars": 39812,
  "size_limit": {config["max_response_chars"]},
  "stages": ["slimmed", "truncated"],
  "slimmed_fields": ["downloadOptionBag"],
  "items_returned": 20,
  "items_total": 137,
  "note": "<the exact tool + parameters that retrieve the rest>"
}}
```

- `reason`: `size` = the payload was too large; `window` = a PAGE cap fired
  (pages were never extracted at all, so `items_*` count PAGES, not records,
  and that text is NOT reachable by paging - re-run with a higher
  `PYPDF_MAX_PAGES` / `MISTRAL_OCR_MAX_PAGES`, or download the PDF).
- `stages`: `slimmed` = heavy per-record fields were dropped;
  `truncated` = whole records were dropped.
- `items_returned` / `items_total`: records (or pages, per `reason` above).
  `items_total` is `null` only when the true total is unknown - it is never
  guessed.
- Always read `note` - it names the call that recovers what was dropped.
- Legacy aliases kept for this release: `documents_returned`,
  `documents_total`, `documents_note`, `truncated`, `truncation_note`.

### `_window` - long text was paged, not dropped

Present on `PFW_get_document_content_with_ocr` and `PFW_get_oa_text` when the
text is longer than one window.

```json
"_window": {{
  "unit": "page",
  "offset": 0,
  "returned": 120000,
  "total": 310000,
  "has_more": true,
  "next_offset": 120000,
  "note": "<how to fetch the next window>"
}}
```

All four counters are CHARACTER offsets in both units, so `next_offset` feeds
straight back into `char_offset`. `unit` reports only whether the window edges
snapped to `=== PAGE N ===` markers (`page`) or are raw character slices
(`char`). Both extraction tiers (PyPDF2 and OCR) emit those
headers, so page-unit windows work on either.

**New parameters:**
- `PFW_get_document_content_with_ocr(char_offset=0, max_chars=None)` - defaults
  to the {config["max_content_chars"]:,}-char content budget. Also reports
  `content_total_chars` / `content_returned_chars`.
- `PFW_get_oa_text(char_offset=0, max_chars=None)` - same cursor. With
  `latest_only=False` the budget is SPLIT across the office actions returned
  (`per_document_char_budget`), and every entry carries
  `text_total_chars` / `text_returned_chars` plus its own `_window`.

### Paging searches

Every search response carries a `paging` block reporting the limit that was
ACTUALLY applied next to what was requested:

```json
"paging": {{
  "limit_requested": 500,
  "limit_applied": {EnhancedPatentClient.MAX_SEARCH_LIMIT},
  "offset": 0,
  "returned": {EnhancedPatentClient.MAX_SEARCH_LIMIT},
  "total": 1372,
  "has_more": true,
  "next_offset": {EnhancedPatentClient.MAX_SEARCH_LIMIT}
}}
```

The ceiling is **{EnhancedPatentClient.MAX_SEARCH_LIMIT}** on every search tool,
because that is what the USPTO search endpoint itself clamps
`pagination.limit` to. Asking for more is CLAMPED to the ceiling and stamped
with `limit_clamped` {{"requested", "applied", "note"}}, not rejected; only
`limit < 1` is a 400. Page past the ceiling with `offset=` (feed back
`paging.next_offset`). The inventor tools additionally report
`unique_applications_discovered`, `queries_generated` vs `queries_executed`
(name-variant fan-out) and `sub_query_limit`, so a short result set is never
mistaken for an exhausted portfolio.

### Other honest-count markers

| Response key | Meaning |
| --- | --- |
| `description_paragraphs_returned` / `_total` | `PFW_get_patent_or_application_xml` summarizes the specification to its first few paragraphs |
| `citations_returned` / `citations_total` | same tool, XML citation list cap |
| `section_requested` / `section_returned` + `section_note` | `PFW_get_oa_text` fell back to the FULL body because USPTO has no separately indexed sub-document for the requested section |
| `versions_considered` / `versions_available` | `PFW_get_granted_patent_documents_download` chose the earliest/latest component from a capped fetch |
| `page_count` + `page_count_source` | `downloadOptionBag`, `pdf`, or `unknown` - a missing page count is reported as `null`, never as 0 |
| `matched_count` | documents that passed the filters, before `limit` was applied |
| `rows_requested` / `rows_applied` | `PFW_get_oa_rejections` (1-100) |
| `limit_clamped` | a `PFW_search_*` `limit` above the ceiling was clamped to it |
"""
