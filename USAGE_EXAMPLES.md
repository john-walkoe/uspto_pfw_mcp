# Usage Examples & Integration Workflows

This document provides a comprehensive set of examples for using the Patent File Wrapper (PFW) MCP, including basic searches, advanced filtering, cross-MCP integration workflows, and convenience parameter usage.

## Notes on Patent File Wrapper MCP Usage

For the most part the LLMs will perform these searches and workflows on their own with minimal guidance from the user. These examples are illustrative to give insight on what the LLMs are doing in the background.

**💡 Best Practice Recommendation:** For complex workflows or when you're unsure about the best approach, start by asking the LLM to use the `PFW_get_guidance` tool first. This tool provides context-efficient workflow recommendations and helps the LLM choose the most appropriate tools and strategies for your specific use case.

**⚠ Identifier format.** Application serials in these examples are written in
the slash-comma form (`11/752,072`) because that form is unambiguous: a slash
marks a serial and resolution short-circuits to the application lane. A bare
8-digit number is simultaneously a valid application serial AND a valid granted
patent number, and resolution tries the patent lane first, so a bare
`11752072` resolves to PATENT 11,752,072 (application 16816197), not to
application 11/752,072. If you cannot use the slashed form, pass
`content_type='application'`. Bare digits inside a Solr `query` /
`applicationNumberText:` string are correct and deliberate: that is the raw API
field, not an identifier the resolver sees.

Sample requests that the user can give to the LLM to trigger the Examples are as follows:

### Sample User Requests by Example

**Example 1 - Convenience Parameter Searches:**
- *"Find granted patents in Art Unit 2128"*
- *"Show me The Target Company Inc.'s patent applications filed in 2024"*
- *"Find patents examined by examiner Smith in the last year"*
- *"Get all AI patents from The Target Company Inc. in Art Unit 3600"*

**Example 2 - Inventor and Topic Searches:**

- *"Find all patents by inventor John Smith"*
- *"Search for machine learning patents and show me the top 5"*
- *"Look up Wilbur Walkoe's patent portfolio"*

**Example 3 - Complete Patent Package:**
- *"Get me the complete patent package for application 11/752,072"*
- *"Download all documents for US Patent 7971071"*
- *"I need the full patent with drawings and claims for this application 11/752,072"*

**Example 4 - Structured XML Content:**

- *"Get the structured data for patent 7971071"*
- *"Analyze the claims and abstract for this patent 7971071"*
- *"I need you to look at the patent details of 7971071 and summarize it for me"*

**Example 5 - Advanced Document Filtering:**
- *"Get only the Notice of Allowance for application 11/752,072"*
- *"Show me the examiner's rejections for this heavily litigated patent 9049188"*
- *"For application 11/752,072 find all the prior art citations the examiner considered"*
- *"This application 11/752,072 has 150+ documents - help me find just the key ones"*

**Example 6 - Document Extraction and Downloads:**
- *"For US Patent 7971071 extract the text from the Notice of Allowance document"*
- *"For US Patent 7971071 download the office action PDFs for this application"*
- *"For US Patent 7971071 get me clickable download links for these patent documents Notice of Allowance, final allowed claims and Initial claims (as filed)"*

**Example 7 - Cross-MCP Integration Workflows:**

- *"Analyze this art unit's, 2128, prosecution patterns and petition history"*
- *"Research this IPR case IPR2025-00562 and compare it to the original prosecution"*
- *"Do a complete due diligence check on this company's patent portfolio, The Target Company Inc."*
- *"Profile examiner Smith's citation behavior and prosecution patterns"*

**Example 8 - Office Action API Analysis:**

- *"What types of rejections did examiner Smith issue most often?"*
- *"Search for §101 rejections in art unit 2128 filed after 2022"*
- *"Get the full text of the office action for application 11/752,072"*
- *"What does the office action say about the §103 rejection for this application?"*



## Table of Contents
1. [Convenience Parameter Searches](#-example-1-convenience-parameter-searches)
2. [Inventor and Topic Searches](#-example-2-inventor-and-topic-searches)
3. [Complete Patent Package Retrieval](#-example-3-get-complete-patent-package)
4. [Structured XML Content Analysis](#-example-4-get-structured-xml-content)
5. [Advanced Document Filtering](#-example-5-advanced-document-filtering-litigation-research)
6. [Intelligent Document Processing](#-example-6-document-extraction-and-downloads)
7. [Cross-MCP Integration Workflows](#-example-7-cross-mcp-integration-workflows)
8. [Office Action API Analysis](#-example-8-office-action-api-analysis)
9. [Known Patents for Testing](#known-patents-for-testing)
10. [Full Tool Reference](#full-tool-reference)

---

### ⭐ Example 1: Convenience Parameter Searches

The search tools now include attorney-friendly convenience parameters, allowing for powerful searches without needing to know complex query syntax. **It is highly recommended to use the `_minimal` search tier for discovery to save tokens.**

#### Available Convenience Parameters

All application search tools (`PFW_search_applications`, `PFW_search_applications_minimal`, `PFW_search_applications_balanced`) and the inventor tools (`PFW_search_inventor`, `PFW_search_inventor_minimal`, `PFW_search_inventor_balanced`) support these parameters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `art_unit` | Art unit number | `'2128'`, `'3600'` |
| `examiner_name` | Examiner name | `'SMITH, JOHN'`, `'SMITH'` |
| `applicant_name` | Company/applicant name | `'Apple Inc.'`, `'TechCorp'` |
| `customer_number` | Customer number | `'26285'`, `'12345'` |
| `status_code` | Status code | `'150'` (granted), `'30'` (pending) |
| `filing_date_start` | Filing date range start | `'2024-01-01'` |
| `filing_date_end` | Filing date range end | `'2024-12-31'` |
| `grant_date_start` | Grant date range start | `'2023-01-01'` |
| `grant_date_end` | Grant date range end | `'2023-12-31'` |

#### Search by Art Unit and Status
```python
# Find all granted patents in Art Unit 2128
PFW_search_applications_minimal(
    art_unit='2128',
    status_code='150',  # '150' means granted
    limit=50
)

# Find pending applications in Art Unit 3600
PFW_search_applications_minimal(
    art_unit='3600',
    status_code='30',  # '30' means pending
    limit=100
)
```

#### Search by Applicant (Assignee)
```python
# Find all patent applications filed by "Apple Inc." in 2024
PFW_search_applications_minimal(
    applicant_name='The Target Company Inc.',
    filing_date_start='2024-01-01',
    filing_date_end='2024-12-31',
    limit=100
)

# Find all granted patents for a company
PFW_search_applications_minimal(
    applicant_name='The Target Company Inc.',
    status_code='150',
    limit=50
)
```

#### Search by Examiner
```python
# Find all patents examined by a specific examiner
PFW_search_applications_minimal(
    examiner_name='SMITH',
    limit=50
)

# Find granted patents by specific examiner in date range
PFW_search_applications_minimal(
    examiner_name='SMITH, JOHN',
    status_code='150',
    grant_date_start='2023-01-01',
    grant_date_end='2023-12-31',
    limit=50
)
```

#### Hybrid Search (Keywords + Convenience Parameters)
```python
# Find granted patents related to 'artificial intelligence' in Art Unit 2128
PFW_search_applications_minimal(
    query='artificial intelligence',
    art_unit='2128',
    status_code='150',
    limit=25
)

# Find machine learning patents from specific company in date range
PFW_search_applications_minimal(
    query='machine learning neural network',
    applicant_name='The Target Company Inc.',
    filing_date_start='2023-01-01',
    filing_date_end='2024-12-31',
    limit=50
)
```

#### Inventor Search with Filters
```python
# Find patents by inventor 'Smith' in Art Unit 3600
PFW_search_inventor_minimal(
    name='Smith',
    art_unit='3600',
    limit=50
)

# Find granted patents by inventor in specific date range
PFW_search_inventor_minimal(
    name='John Smith',
    status_code='150',
    grant_date_start='2020-01-01',
    grant_date_end='2024-12-31',
    limit=50
)
```

#### Art Unit + Examiner Combination
```python
# Analyze specific examiner's work in their art unit
PFW_search_applications_minimal(
    art_unit='2128',
    examiner_name='SMITH',
    status_code='150',
    limit=50
)

# Compare examiner behavior in different time periods
PFW_search_applications_minimal(
    art_unit='2128',
    examiner_name='SMITH',
    grant_date_start='2023-01-01',
    grant_date_end='2023-12-31',
    limit=50
)
```

#### Ultra-Minimal Mode: Custom Fields Parameter (99% Token Reduction)

**NEW**: All minimal and balanced search tools now support an optional `fields` parameter for maximum token efficiency. Use this for workflows that only need specific fields (e.g., citation analysis, application number extraction).

```python
# Standard minimal search (15 fields, 95% reduction)
PFW_search_applications_minimal(
    art_unit='2128',
    examiner_name='SMITH',
    limit=50
)
# Returns: applicationNumberText, inventionTitle, inventorBag, firstApplicantName,
#          uspcSymbolText, cpcClassificationBag, patentNumber, parentPatentNumber,
#          associatedDocuments, examinerNameText, groupArtUnitNumber, filingDate,
#          grantDate, customerNumber, applicationStatusCode

# Ultra-minimal search (2 fields, 99% reduction)
PFW_search_applications_minimal(
    art_unit='2128',
    examiner_name='SMITH',
    fields=['applicationNumberText', 'examinerNameText'],
    limit=50
)
# Returns: ONLY applicationNumberText, examinerNameText
# Use case: Extract app numbers for citation workflow (PFW → Citations integration)

# Citation workflow optimization (3 fields only)
PFW_search_applications_minimal(
    examiner_name='SMITH, JANE',
    filing_date_start='2015-01-01',
    fields=['applicationNumberText', 'examinerNameText', 'filingDate'],
    limit=30
)
# Returns: ONLY 3 fields needed for citation API integration
# Token savings: 99% reduction vs 15-field preset (5KB vs 25KB for 30 results)

# Single-record lookup (5 fields)
PFW_search_applications_minimal(
    query='patentNumber:7971071',
    fields=['applicationNumberText', 'inventionTitle', 'patentNumber', 'filingDate', 'grantDate'],
    limit=1
)
# Returns: ONLY 5 essential fields for quick lookup
# Perfect for: Finding app number from patent number, date validation, title checks

# Inventor discovery (balanced with custom fields)
PFW_search_inventor_balanced(
    name='John Smith',
    art_unit='2128',
    fields=['applicationNumberText', 'inventionTitle', 'patentNumber', 'inventorBag'],
    limit=20
)
# Returns: ONLY 4 fields for inventor portfolio mapping
```

**Token Efficiency Comparison:**
```
Scenario: Search 50 applications by examiner for citation analysis

Ultra-minimal (2 fields):
  ~100 chars/result × 50 = ~5KB total (99% reduction)

Preset minimal (15 fields):
  ~500 chars/result × 50 = ~25KB total (95% reduction)

Preset balanced (24 fields as shipped):
  ~2,000 chars/result × 50 = ~100KB total (85% reduction)

Full with documentBag (NEVER):
  ~10,000 chars/result × 50 = ~500KB total (unusable)
```

**When to Use Custom Fields:**
- **Citation workflows**: PFW → Citations integration (extract app numbers only)
- **Single-record lookups**: Patent number → app number conversion
- **High-volume extraction**: a full page of 100 results where only 2-3 fields are needed
- **Cross-MCP integration**: Extract minimal fields for PTAB/FPD cross-reference
- **Date validation**: Quick filing/grant date checks before citation analysis

**When to Use Preset Fields:**
- **User selection workflows**: Need title, inventor, classification for user to choose
- **Analysis workflows**: Need metadata for pattern analysis
- **First-time exploration**: Don't know which fields you'll need yet

---

### Example 2: Inventor and Topic Searches

#### Ultra-Fast Discovery Search
```python
# High-volume discovery search for AI patents
result = await PFW_search_applications_minimal(
    query="artificial intelligence machine learning",
    limit=50
)

# Present top 5 results to user for selection
print("Top 5 AI patents found:")
for i, app in enumerate(result['applications'][:5]):
    print(f"{i+1}. {app['inventionTitle']} (App: {app['applicationNumberText']})")
```

#### Find Patents by Inventor
```python
# Search for all patents by Wilbur Walkoe using the comprehensive strategy
result = await PFW_search_inventor_balanced(
    name="Wilbur Walkoe",
    strategy="comprehensive",
    limit=25
)

# This will search using multiple strategies:
# - applicationMetaData.inventorBag.inventorNameText:"Wilbur Walkoe"
# - applicationMetaData.inventorBag.inventorNameText:Wilbur*
# - applicationMetaData.firstInventorName:"Wilbur Walkoe"
# - applicationMetaData.firstInventorName:Wilbur*

print(f"Found {result['count']} applications")
for app in result['applications']:
    print(f"Patent {app.get('patentNumber', 'Pending')}: {app['inventionTitle']}")
```

---

### Example 3: Get Complete Patent Package
```python
# Get all components of a granted patent in one call
patent_package = await PFW_get_granted_patent_documents_download(app_number="11/752,072")

print(f"Complete patent package: {patent_package['total_pages']} total pages")
print(f"Abstract: {patent_package['abstract']['pageCount']} pages")
print(f"Drawings: {patent_package['drawings']['pageCount']} pages")
print(f"Specification: {patent_package['specification']['pageCount']} pages")
print(f"Claims: {patent_package['claims']['pageCount']} pages")
```

---

### Example 4: Get Structured XML Content

#### Recommended: Optimized XML Retrieval (91% Token Reduction)
```python
# RECOMMENDED: Get structured patent data with include_raw_xml=False
# Removes ~50K token raw XML overhead (91% reduction: ~55K → ~5K tokens!)
xml_content = await PFW_get_patent_or_application_xml(
    identifier="7971071",
    include_raw_xml=False  # RECOMMENDED - removes raw XML overhead
)

print(f"Patent: {xml_content['application_number']}")
print(f"Title: {xml_content['structured_content'].get('title', 'N/A')}")
print(f"Abstract: {xml_content['structured_content']['abstract'][:200]}...")
print(f"Claims: {len(xml_content['structured_content']['claims'])} total claims")
```

**Token Savings:**
- **Legacy (with raw_xml)**: ~55,000 tokens
- **Recommended (include_raw_xml=False)**: ~5,000 tokens
- **Reduction**: 91% (50K tokens saved!)

#### Ultra-Efficient: Selective Field Extraction (95-99% Token Reduction)
```python
# Get ONLY claims for claim analysis (95% reduction: ~55K → ~1.5K tokens)
claims_only = await PFW_get_patent_or_application_xml(
    identifier="7971071",
    include_fields=['claims'],
    include_raw_xml=False
)
print(f"Claims: {len(claims_only['structured_content']['claims'])} total")

# Get ONLY citations for prior art analysis (98% reduction: ~55K → 569 tokens)
citations_only = await PFW_get_patent_or_application_xml(
    identifier="7971071",
    include_fields=['citations'],
    include_raw_xml=False
)

# Get ONLY inventors for portfolio analysis (99% reduction: ~55K → 428 tokens)
inventors_only = await PFW_get_patent_or_application_xml(
    identifier="7971071",
    include_fields=['inventors'],
    include_raw_xml=False
)

# Get abstract + claims + description for attorney report (~5K tokens with include_raw_xml=False)
attorney_package = await PFW_get_patent_or_application_xml(
    identifier="7971071",
    include_fields=['abstract', 'claims', 'description'],
    include_raw_xml=False  # Default fields, shown for clarity
)

# Get inventors + applicants for entity analysis (~1K tokens)
# NOTE: More efficient to get this from PFW_search_applications_balanced if already in context!
entity_info = await PFW_get_patent_or_application_xml(
    identifier="7971071",
    include_fields=['inventors', 'applicants'],
    include_raw_xml=False
)
```

**Available Fields for `include_fields`:**
- **Core content**: `abstract`, `claims`, `description`
- **Metadata**: `inventors`, `applicants`, `classifications`, `publication_info`
- **References**: `citations`

**Token Efficiency Comparison:**
| Configuration | Fields Returned | Token Count | Reduction | Use Case |
|--------------|----------------|-------------|-----------|----------|
| Legacy (default) | All + raw_xml | ~55,000 | 0% | Debugging only |
| **Recommended default** | abstract, claims, description | **~5,000** | **91%** | **General patent analysis** |
| Claims only | claims | ~1,500 | 95% | Claim construction, infringement analysis |
| Citations only | citations | 569 | 98% | Prior art research |
| Inventors only | inventors | 428 | 99% | Portfolio mapping, inventor analysis |

**Best Practices:**
1. **ALWAYS use `include_raw_xml=False`** unless debugging XML parsing issues
2. **Use `include_fields` for specialized workflows** (claims-only, citations-only)
3. **Get metadata from search tools when possible** - If you already ran `PFW_search_applications_balanced`, you likely have inventor/applicant data in context. Don't re-fetch via XML!
4. **Default is optimized** - Without parameters, you get abstract + claims + description (~5K tokens with `include_raw_xml=False`)

---

### 🎯 Example 5: Advanced Document Filtering (Litigation Research)

The `PFW_get_application_documents` function supports powerful filtering to handle applications with 200+ documents (common in litigation cases). Achieve up to **98.6% context reduction** for heavily-litigated applications.

#### Filter by Document Type

**Common Document Codes:**
- `NOA` - Notice of Allowance (examiner's reasoning for allowance)
- `CTFR` / `CTNF` - Office Actions (examiner's rejections)
- `CLM` - Claims (final allowed claims)
- `FWCLM` - Index of Claims (includes amendments)
- `ABST` - Abstract (1-page summary)
- `SPEC` - Specification (full technical description)
- `DRW` - Drawings (technical diagrams)
- `892` - Examiner Citations (prior art references)
- `1449` - Applicant Citations (disclosed prior art)

```python
# Get only Notice of Allowance documents (examiner's reasoning)
PFW_get_application_documents(
    app_number="11/752,072",
    document_code="NOA",
    limit=20
)

# Get the examiner's office action rejections
PFW_get_application_documents(
    app_number="11/752,072",
    document_code="CTFR",
    limit=10
)

# Get the prior art citations considered by the examiner
PFW_get_application_documents(
    app_number="11/752,072",
    document_code="892",
    limit=10
)

# Get the Index of Claims (claim amendments tracking)
PFW_get_application_documents(
    app_number="11/752,072",
    document_code="FWCLM",
    limit=20
)
```

#### Filter by Document Direction

**Direction Categories:**
- `INCOMING` - Documents from applicant to USPTO
- `OUTGOING` - Documents from USPTO to applicant
- `INTERNAL` - Internal USPTO documents

```python
# Get all documents submitted BY THE APPLICANT to the USPTO
PFW_get_application_documents(
    app_number="11/752,072",
    direction_category="INCOMING",
    limit=50
)

# Get all documents sent FROM THE USPTO to the applicant
PFW_get_application_documents(
    app_number="11/752,072",
    direction_category="OUTGOING",
    limit=50
)
```

#### Combined Filtering for Precision
```python
# Get examiner's internal claim analysis only
PFW_get_application_documents(
    app_number='11/752,072',
    document_code='FWCLM',
    direction_category='INTERNAL',
    limit=10
)

# Get only applicant-filed claims
PFW_get_application_documents(
    app_number='11/752,072',
    document_code='CLM',
    direction_category='INCOMING',
    limit=20
)

# Get all examiner rejections
PFW_get_application_documents(
    app_number='11/752,072',
    document_code='CTFR',  # or 'CTNF' for non-final
    direction_category='OUTGOING',
    limit=10
)
```

#### Validated Context Reduction Results (re-verified live 2026-09-03)

**Tested Applications:**

- **Application 11/752,072**: 151 total documents (John and Wilbur Walkoe US-7971071-B2 Patent - heavily prosecuted)
- **Application 14/171,705**: 73 total documents (IPR litigation example; the count grows as new papers are filed)

| Application | Total Docs | Filter Applied | Result | Reduction | Use Case |
|-------------|------------|----------------|---------|-----------|----------|
| **11/752,072 - Walkoe** | **151 docs** | `document_code='NOA'` | **1 doc** | **99.3%** | Get Notice of Allowance reasoning |
| **11/752,072 - Walkoe** | **151 docs** | `document_code='FWCLM'` | **6 docs** | **96.0%** | Track Index of Claims across prosecution |
| **11/752,072 - Walkoe** | **151 docs** | `direction_category='INCOMING'` | **59 docs** | **60.9%** | Analyze all applicant submissions |
| **11/752,072 - Walkoe** | **151 docs** | `document_code='FWCLM'` + `direction_category='INTERNAL'` | **6 docs** | **96.0%** | Get examiner's internal claim analysis |
| **14/171,705 - IPR litigation example** | **73 docs** | `document_code='NOA'` | **1 doc** | **98.6%** | Get Notice of Allowance reasoning |
| **14/171,705 - IPR litigation example** | **73 docs** | `document_code='FWCLM'` | **2 docs** | **97.3%** | Track Index of Claims across prosecution |
| **14/171,705 - IPR litigation example** | **73 docs** | `direction_category='INCOMING'` | **32 docs** | **56.2%** | Analyze all applicant submissions |
| **14/171,705 - IPR litigation example** | **73 docs** | `document_code='FWCLM'` + `direction_category='INTERNAL'` | **2 docs** | **97.3%** | Get examiner's internal claim analysis |

> Document counts are a live figure: a filed paper adds to the bag. Treat these
> as the shape of the reduction, not a fixed baseline.

#### Key Filtering Strategies

**1. Document Code Filtering (`document_code`)**
Target specific document types to focus analysis:

| Code | Description | Typical Count | Reduction |
|------|-------------|---------------|------------|
| `NOA` | Notice of Allowance | 1-2 | 98-99% |
| `FWCLM` | Index of Claims | 2-6 | 96-97% |
| `CTFR` | Final Rejection | 1-3 | 97-99% |
| `CTNF` | Non-Final Rejection | 2-5 | 96-98% |
| `CLM` | Claims (applicant filed) | 5-15 | 90-95% |
| `892` | Examiner Citations | 1-5 | 97-99% |
| `1449` | Applicant Citations | 2-10 | 93-97% |

**2. Direction Category Filtering (`direction_category`)**
Filter by document origin:

| Direction | Description | Typical % of Total | Use Case |
|-----------|-------------|--------------------|-----------|
| `INCOMING` | Applicant submissions | 35-45% | Analyze prosecution strategy |
| `OUTGOING` | USPTO communications | 40-50% | Review examiner positions |
| `INTERNAL` | Examiner work products | 15-25% | Deep dive on examination logic |

**3. Context Efficiency Analysis**

**Without Filtering:**
- **151 documents** = ~3MB raw response
- **Context window impact**: Severe token overhead
- **Analysis difficulty**: Information buried in noise

**With Smart Filtering:**
- **1-6 documents** = ~10-50KB focused response
- **Context window impact**: 95-99% reduction
- **Analysis clarity**: Laser-focused on relevant documents

#### Litigation Research Workflow

For heavily-prosecuted applications (150+ documents):

```python
# 1. Initial Discovery (Minimal tier)
PFW_search_applications_minimal(
    query='applicationNumberText:11752072',
    limit=10
)

# 2. Target Key Events (Document filtering)
# Get allowance reasoning
PFW_get_application_documents(
    app_number='11/752,072',
    document_code='NOA',
    limit=5
)

# 3. Extract Critical Content (Document access)
# Tiered extraction: free-text variants → PyPDF2 native text layer → OCR
PFW_get_document_content_with_ocr(
    app_number='11/752,072',
    document_identifier='GN23NLY2PPOPPY5',
    auto_optimize=True  # Default
)

# 4. Cross-Reference with PTAB (Multi-MCP workflow)
# PTAB indexes proceedings by GRANTED PATENT number, not application serial
PTAB_search_trials_minimal(
    patent_number='7971071',
    limit=10
)
```

#### Document Selection by Use Case

**For Litigation Research:**
```python
# Priority: NOA → Office Actions → Examiner Citations → Claims
# 1. Get Notice of Allowance
PFW_get_application_documents(app_number="11/752,072", document_code="NOA")

# 2. Get Office Actions (examiner's rejections)
PFW_get_application_documents(app_number="11/752,072", document_code="CTFR", direction_category="OUTGOING")

# 3. Get Examiner Citations (prior art)
PFW_get_application_documents(app_number="11/752,072", document_code="892")

# 4. Get Final Claims
PFW_get_application_documents(app_number="11/752,072", document_code="CLM")
```

**For Due Diligence:**
```python
# Priority: Abstract → Claims → Citations → NOA
# 1. Get Abstract (quick overview)
PFW_get_application_documents(app_number="11/752,072", document_code="ABST")

# 2. Get Claims (scope assessment)
PFW_get_application_documents(app_number="11/752,072", document_code="CLM")

# 3. Get Citations (prior art density)
PFW_get_application_documents(app_number="11/752,072", document_code="892")

# 4. Get NOA (prosecution difficulty)
PFW_get_application_documents(app_number="11/752,072", document_code="NOA")
```

**For Prior Art Research:**
```python
# Priority: XML → Examiner Citations → Claims → Specification
# 1. Use XML first - structured, already-digital, no scanning step
PFW_get_patent_or_application_xml("11/752,072")

# 2. Get Examiner Citations
PFW_get_application_documents(app_number="11/752,072", document_code="892")

# 3. Get Applicant Citations
PFW_get_application_documents(app_number="11/752,072", document_code="1449")

# 4. Get Specification only if needed
PFW_get_application_documents(app_number="11/752,072", document_code="SPEC")
```

---

### Example 6: Document Extraction and Downloads

#### Intelligent Extraction with Tier Optimization

The tool walks four capability tiers, stopping at the first that yields usable text:
0. **USPTO free-text variants** (instant, no scanning) - the `.docx`, `xmlarchive`, or as-uploaded PDF the USPTO API serves alongside the PDF render
1. **PyPDF2 native text layer** (instant) - text-based PDFs; an all-empty text layer is reported as a failure, not a success
2. **Mistral OCR** - scanned USPTO documents; requires `MISTRAL_API_KEY` (optional)
3. **Docling OCR** - the same scanned documents, self-hosted; requires `DOCLING_SERVE_URL` (optional)

Tiers 2 and 3 are the OCR step, reached only when a page has no usable native
text layer. Configure either backend, both, or neither; with neither, the tool
reports what it could not extract instead of failing silently.

```python
# Get the document ID for the Notice of Allowance first
docs = await PFW_get_application_documents(app_number="11/752,072", document_code="NOA")
noa_doc_id = docs['documentBag'][0]['documentIdentifier']

# Extract text — auto-selects best available method
noa_content = await PFW_get_document_content_with_ocr(
    app_number="11/752,072",
    document_identifier=noa_doc_id,
    auto_optimize=True  # Walks the tiers automatically
)

print(f"Extraction method: {noa_content['extraction_method']}")
# Possible values: "PyPDF2", "Mistral OCR", "Docling OCR", "failed"
print(f"Content length: {len(noa_content['extracted_content'])} characters")
```

#### Secure Document Downloads

**⚠️ CRITICAL: Proxy Server Startup Requirement**

Before providing download links to users, you **MUST** call `PFW_get_document_download` or `PFW_get_granted_patent_documents_download` for at least one document to start the proxy server (~0.5 second startup time). Otherwise, users will get `ERR_CONNECTION_REFUSED` when clicking links.

```python
# CORRECT WORKFLOW: Start proxy first
# 1. Get document metadata
docs = await PFW_get_application_documents(app_number="11/752,072", document_code="NOA")
noa_doc_id = docs['documents'][0]['documentIdentifier']

# 2. Call PFW_get_document_download to START the proxy server
download_link = await PFW_get_document_download(
    app_number="11/752,072",
    document_identifier=noa_doc_id
)

# 3. Now proxy is running - provide clickable markdown link to user
print(f"**📁 [Download Notice of Allowance ({download_link['pageCount']} pages)]({download_link['proxy_url']})**")

# 4. Additional documents can be provided immediately (proxy already running)
# ... get more doc IDs and create more download links
```

---

### 🔗 Example 7: Cross-MCP Integration Workflows

This MCP is designed to integrate with three other USPTO MCPs for comprehensive patent lifecycle analysis:

#### Related USPTO MCP Servers

| MCP Server | Purpose | GitHub Repository |
|------------|---------|-------------------|
| **USPTO Patent File Wrapper (PFW)** | Prosecution history & documents | [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp.git) |
| **USPTO Patent Trial and Appeal Board (PTAB)** | Patent Trial and Appeal Board proceedings | [uspto_ptab_mcp](https://github.com/john-walkoe/uspto_ptab_mcp.git) |
| **USPTO Final Petition Decisions (FPD)** | Final Petition Decisions | [uspto_fpd_mcp](https://github.com/john-walkoe/uspto_fpd_mcp.git) |
| **USPTO Enriched Citations** | AI-powered examiner citation analysis (Post-2017 applications) | [uspto_enriched_citation_mcp](https://github.com/john-walkoe/uspto_enriched_citation_mcp.git) |
| **Pinecone Assistant MCP** | Patent law knowledge base (MPEP, examination guidance) - context retrieval with assistant_chat for AI synthesis | [pinecone_assistant_mcp](https://github.com/john-walkoe/pinecone_assistant_mcp.git) |
| **Pinecone RAG MCP** | Patent law knowledge base with custom embeddings (MPEP, examination guidance) | [pinecone_rag_mcp](https://github.com/john-walkoe/pinecone_rag_mcp.git) |

---

#### Workflow 1: Art Unit Quality Assessment (PFW + FPD)

**Goal:** Analyze an art unit's prosecution and petition history to identify patterns.

```python
# 1. PFW Discovery: Find applications in art unit 2128
PFW_search_applications_minimal(
    art_unit="2128",
    limit=100
)

# 2. Present top 10 results to user for selection

# 3. FPD Search: Find petition decisions for the same art unit
FPD_Search_petitions_by_art_unit(
    art_unit="2128",
    limit=50
)

# 4. Analysis: Correlate petition patterns with prosecution difficulty
# - High revival petition rate (37 CFR 1.137) → abandonment issues
# - High examiner dispute rate (37 CFR 1.181) → difficult examiners
# - Multiple petitions per application → procedural problems
```

**Red Flags to Identify:**
- **Revival Petitions (37 CFR 1.137)**: Application was abandoned - indicates missed deadlines or docketing issues
- **Examiner Disputes (37 CFR 1.181)**: Petitions for supervisory review - indicates contentious prosecution
- **Denied Petitions**: Documented unsuccessful legal arguments

---

#### Workflow 2: Complete IPR Litigation Research (PTAB + PFW)

**Goal:** Analyze an *inter partes* review (IPR) by comparing the PTAB challenge with the patent's original prosecution history.

```python
# 1. PTAB Search: Find the IPR proceeding
PTAB_search_trials_balanced(
    patent_number='9049188'
)
# → IPR2025-00562, Apple Inc. v. Proxense, LLC (status: Trial Instituted)
# PTAB trial metadata does NOT carry applicationNumberText. Map the patent
# number to its application serial with PFW instead:
PFW_search_applications_minimal(
    query='patentNumber:9049188',
    fields=['applicationNumberText', 'inventionTitle'],
    limit=1,
)
# → applicationNumberText "14171705" (application 14/171,705)

# 2. PFW Cross-Reference: Get detailed prosecution history
PFW_search_applications_balanced(
    query='applicationNumberText:14171705',
    limit=1
)

# 3. PTAB Document Analysis: Get IPR documents
PTAB_get_documents(
    identifier='IPR2025-00562'
)
# Focus on: IPR Petition, Institution Decision, Final Written Decision

# 4. PFW Document Analysis: Get prosecution documents for the challenged patent
PFW_get_application_documents(app_number='14/171,705', document_code='NOA')
PFW_get_application_documents(app_number='14/171,705', document_code='CTFR', direction_category='OUTGOING')
PFW_get_application_documents(app_number='14/171,705', document_code='892')

# 5. Comparative Analysis:
# - Compare IPR prior art with examiner's 892 citations
# - Contrast PTAB reasoning with examiner's NOA reasoning
# - Identify differences in claim interpretation
```

**Cross-Reference Fields:**
- `patentNumber` - Primary key linking PTAB to PFW (PTAB trial metadata indexes by granted patent, not application serial; map it with `PFW_search_applications_minimal(query='patentNumber:<n>')`)
- `groupArtUnitNumber` - Art unit context
- `examinerNameText` - Examiner quality correlation
- `firstApplicantName` → PTAB respondentPatentOwnerName
- `inventorBag` → PTAB respondentInventorName

---

#### Workflow 3: Full Lifecycle Due Diligence (PFW → FPD → PTAB)

**Goal:** Assess a company's entire patent portfolio for quality, procedural issues, and litigation risk.

```python
# 1. Portfolio Discovery (PFW): Get all company applications
PFW_search_applications_minimal(
    applicant_name='The Target Company Inc.',
    limit=100,   # 100 is MAX_SEARCH_LIMIT; a higher value is CLAMPED and reported in limit_clamped
)

# 2. Present portfolio overview to user, get high-value selections

# 3. Petition History Check (FPD): For key applications
FPD_Search_petitions_by_application(
    application_number='17/896,175'
)

# 4. Detailed Prosecution Analysis (PFW): For selected applications
PFW_search_applications_balanced(
    query='applicationNumberText:17896175',
    limit=1
)

# 5. Post-Grant Challenge Check (PTAB): For all granted patents
PTAB_search_trials_minimal(
    patent_number='11788453'
)

# 6. Holistic Assessment:
# - Clean prosecution + no petitions + no PTAB = strong asset
# - Multiple petitions + PTAB challenges = high-risk asset
# - Examiner disputes + denied petitions = prosecution quality issues
```

**Risk Scoring Framework:**
```python
# High Risk:
# - Multiple revival petitions (abandonment history)
# - Examiner disputes (contentious prosecution)
# - PTAB challenges filed (validity questioned)
# - Multiple office action rounds (weak prosecution)

# Medium Risk:
# - Normal prosecution (1-2 office actions)
# - No petitions or successful petitions
# - No PTAB challenges OR survived PTAB

# Low Risk:
# - Quick allowance (minimal office actions)
# - No petition history
# - No PTAB challenges
# - Strong claim scope
```

---

#### Workflow 4: Examiner Profiling with Convenience Parameters (PFW + PTAB + FPD)

**Goal:** Profile examiner behavior using convenience parameters and cross-MCP data.

```python
# 1. Find examiner's granted patents in specific art unit
PFW_search_applications_minimal(
    art_unit='2128',
    examiner_name='SMITH',
    status_code='150',  # granted
    limit=50
)

# 2. Present results to user, get selections

# 3. Check petition history for examiner's applications
# For each application: FPD_Search_petitions_by_application(app_number)

# 4. Check PTAB challenge rate for examiner's patents
# For each patent: PTAB_search_trials_minimal(patent_number)

# 5. Analyze:
# - Allowance rate vs art unit average
# - Petition frequency (examiner disputes?)
# - PTAB challenge vulnerability
# - Successful prosecution strategies
```

---

#### Workflow 5: Technology Landscape Mapping with Convenience Parameters

**Goal:** Map competitive landscape using technology keywords + convenience parameters.

```python
# 1. Discovery: Find AI patents in specific art units
PFW_search_applications_minimal(
    query='artificial intelligence neural network',
    art_unit='2128',
    status_code='150',
    filing_date_start='2020-01-01',
    limit=100
)

# 2. Extract key players: Analyze firstApplicantName frequency

# 3. Timeline analysis: Group by filingDate trends

# 4. For key patents, check PTAB vulnerability
PTAB_search_trials_minimal(patent_number='...')

# 5. Get successful prosecution examples
# Filter to: granted + minimal rejections + no PTAB challenges

# 6. Pinecone Research (if available):
# Research current examination standards
# Option A - Pinecone Assistant MCP (AI-powered with citations):
assistant_context(query='AI-assisted inventions', top_k=3, snippet_size=1024, temperature=0.3)
# Option B - Pinecone RAG MCP (custom embeddings):
semantic_search(query='AI-assisted inventions', top_k=3)

# 7. Download exemplar claims for drafting guidance
PFW_get_patent_or_application_xml(identifier='...')
```

---

#### Workflow 6: Portfolio Filing Trends Analysis

**Goal:** Track company's filing velocity and strategic shifts over time.

```python
# Q1 2024 filings
q1_apps = PFW_search_applications_minimal(
    applicant_name='The Target Company Inc.',
    filing_date_start='2024-01-01',
    filing_date_end='2024-03-31',
    limit=100
)

# Q2 2024 filings
q2_apps = PFW_search_applications_minimal(
    applicant_name='The Target Company Inc.',
    filing_date_start='2024-04-01',
    filing_date_end='2024-06-30',
    limit=100
)

# Analysis:
# - Compare filing volumes by quarter
# - Identify technology shifts (CPC classification changes)
# - Track art unit distribution (strategic focus areas)
# - Monitor examiner assignments
```

---

#### Workflow 7: Pinecone-Enhanced Prior Art Research (Optional)

**Goal:** Use Pinecone Assistant MCP or Pinecone RAG MCP (if available) to research MPEP guidance before pulling full prosecution documents into context. Choose Assistant for AI-powered synthesis with citations, or RAG for custom embeddings with semantic search.

```python
# 1. Discovery: Find similar granted patents
PFW_search_applications_minimal(
    query='quantum computing error correction',
    status_code='150',
    limit=50
)

# 2. Pinecone Research: Check current examination standards (if Pinecone available)
# Option A - Pinecone Assistant MCP (strategic multi-search with AI synthesis):
assistant_strategic_multi_search_context(
    query='quantum computing patentability',
    domain='software_ai_technology',
    top_k=3,
    snippet_size=1024,
    max_searches=2,
    temperature=0.3
)
# Option B - Pinecone RAG MCP (strategic semantic search with custom embeddings):
strategic_semantic_search(
    query='quantum computing patentability',
    domain='software_ai_technology',
    top_k=3
)
# Returns: MPEP sections, 101 eligibility guidance, 103 obviousness standards

# 3. Filter candidates based on Pinecone research guidance

# 4. Get structured XML content for detailed claim analysis
PFW_get_patent_or_application_xml(identifier='...')

# 5. Extract examiner citations for prior art landscape
PFW_get_application_documents(app_number='...', document_code='892')

# 6. Extract content only for the most relevant citations
PFW_get_document_content_with_ocr(app_number='...', document_identifier='...')

# Why this order:
# - Steps 1-2 narrow the question before any document is pulled
# - XML and office-action text are already-digital: no scanning step at all
# - Only step 6 can reach an OCR tier, and only for a scanned page with no
#   usable native text layer
```

---

### 📋 Example 8: Office Action API Analysis

PFW MCP provides two tools that tap directly into USPTO's Office Action APIs — separate from the prosecution document download chain.

Both tools are scoped to ONE application. They take `application_number`, not a
Solr `criteria` string: there is no cross-application search on this surface. To
study an examiner's or art unit's rejection patterns, discover the applications
first with `PFW_search_applications_minimal(art_unit=..., examiner_name=...)`,
then call the OA tools per application.

#### `PFW_get_oa_rejections` — Rejection Type Indicators (OA Rejections API v2)

Use this to quickly identify what kinds of rejections an application received.
It is the cheap triage step: small, structured, no document text.

```python
# Rejection triage for one application
PFW_get_oa_rejections(
    application_number='18/823,722',
    rows=5,        # 1-100; the response reports rows_requested / rows_applied
)
# → summary: has_102=True, has_103=True, has_112=True, office_actions_count=14
# → rejections[]: one row PER REJECTION GROUP (submission_date, doc_code,
#   art_unit, has_101/102/103/112, alice/mayo/bilski/myriad, cite_103_max,
#   allowed_claims, claims). Several rows can share one office action.

# Force the application-serial lane for a bare 8-digit number
PFW_get_oa_rejections(
    application_number='18823722',
    content_type='application',
)
```

**Key summary and row fields:**
- `has_101` / `has_102` / `has_103` / `has_112` - statutory basis of the rejection
- `alice` / `mayo` / `bilski` / `myriad` - eligibility-framework indicators
- `office_actions_count` - the true office-action count (rows are per rejection group)

**Coverage:** office actions mailed Oct 1, 2017 through roughly 30 days before
today. An empty result on an older application is a coverage gap, not an
application without rejections - `PFW_get_oa_text` reaches considerably
further back.

#### `PFW_get_oa_text` — Full Office Action Text (OA Actions API v1)

Use this to retrieve the actual body text of an office action, or just a specific rejection section.

```python
# Most recent office action of any type
PFW_get_oa_text(application_number='11/752,072')

# Every non-final rejection in the file wrapper (up to 10)
PFW_get_oa_text(
    application_number='11/752,072',
    action_type='CTNF',
    latest_only=False,
)
# → num_found=3 (CTNFs mailed 2010-10-13, 2009-01-29 and 2008-09-08)

# Just the §103 portion of the latest final rejection
PFW_get_oa_text(
    application_number='11/752,072',
    action_type='CTFR',
    section='103',
)

# Page through a long office action
PFW_get_oa_text(
    application_number='11/752,072',
    action_type='CTNF',
    char_offset=2000,      # feed _window.next_offset back here
    max_chars=20000,
)
```

**`action_type` values the dataset actually serves:** `CTNF`, `CTFR`, `NOA`,
`CTRS`, `CTEQ`, `CTAV`, `NRES`, `CTMS`, `EXIN`, `ABN`. Anything else is
rejected with the served set in the error, rather than returning an empty
result that reads as "no such action".

**Available `section` values:** `'101'`, `'102'`, `'103'`, `'112'`, or `'all'`
(the default) for full body text. USPTO populates the section sub-documents
sparsely; when the requested section is empty the tool falls back to the full
body and says so via `section_requested` / `section_returned` / `section_note`.

#### Combined OA + Document Workflow

```python
# 1. Triage: which office actions carry which rejections (small, structured)
PFW_get_oa_rejections(application_number='18/823,722', rows=5)
# → reveals: has_103=True, has_112=True

# 2. Read the §103 argument directly - one call, no PDF, no OCR
PFW_get_oa_text(
    application_number='18/823,722',
    action_type='CTFR',
    section='103',
)

# 3. If you need the original formatted PDF for the client:
PFW_get_application_documents(app_number='11/752,072', document_code='CTNF')
# → get documentIdentifier, then:
PFW_get_document_download(app_number='11/752,072', document_identifier='...')
```

**When to use OA APIs vs document extraction:**
| Use Case | Tool |
|----------|------|
| Rejection type summary (§101/§102/§103/§112?) | `PFW_get_oa_rejections` |
| Reading rejection argument text | `PFW_get_oa_text` |
| Getting original formatted PDF | `PFW_get_document_download` |
| Full prosecution document in LLM context | `PFW_get_document_content_with_ocr` |

---

## Known Patents for Testing

These patents can be used for testing inventor searches for "Wilbur Walkoe":
- US-7971071-B2 (inventors: Wilbur J. Walkoe, John Walkoe)  - (Application 11/752,072)
- US-20080141381-A1
- US-7187686-B1
- US20070036169-A1

For testing cross-MCP integration:
- Patent 9049188 (Application 14/171,705) - Has IPR proceeding IPR2025-00562
- Application 18/823,722 - For citation analysis testing (examiner: MEKHLIN, ELI S, Art Unit 1759)

---

## Full Tool Reference

### Search Tools
*   `PFW_search_applications` - applications search
*   `PFW_search_applications_minimal` - Ultra-fast discovery (recommended)
*   `PFW_search_applications_balanced` - Detailed analysis with additional cross-reference fields
*   `PFW_search_inventor` - inventor search
*   `PFW_search_inventor_minimal` - Ultra-fast inventor discovery (recommended)
*   `PFW_search_inventor_balanced` - Detailed inventor analysis

### Data Retrieval & Document Processing Tools
*   `PFW_get_patent_or_application_xml` - Structured XML content (claims, abstract, description, citations)
*   `PFW_get_granted_patent_documents_download` - Complete patent package in one call
*   `PFW_get_application_documents` - Prosecution document metadata with filtering
*   `PFW_get_document_content_with_ocr` - 4-tier text extraction: USPTO free-text variants → PyPDF2 native text layer → Mistral OCR → Docling OCR
*   `PFW_get_document_download` - Secure browser downloads
*   `PFW_get_oa_rejections` - USPTO OA Rejections API v2 (rejection type indicators)
*   `PFW_get_oa_text` - USPTO OA Actions API v1 (full OA body text + section excerpts)
*   `PFW_get_family` - Normalized continuity graph (parents, children, CON/CIP/DIV) plus foreign priority
*   `PFW_get_term_adjustment` - Patent Term Adjustment days and event history
*   `PFW_get_guidance` - Context-efficient selective guidance (see quick reference chart)

### Admin Tool (OAuth deployments only)
*   `pfw_manage_users` - Registered-user management; registered only when `PFW_ENABLE_USER_MANAGEMENT=true` and gated on the `pfw:admin` scope

### Performance Notes

**Document counts re-verified live 2026-09-03:**
- **Filter application**: Server-side (instant)
- **Typical response time**: 200-500ms per filtered request
- **Token efficiency**: 95-99% reduction vs. unfiltered
- **Extraction tiers**: USPTO free-text variants → PyPDF2 native text layer → Mistral OCR → Docling OCR (self-hosted)
- **Applications tested**: 11/752,072 (151 docs), 14/171,705 (73 docs)
- **Filter accuracy**: 100% (server-side validation)

### Key Features
- **Progressive Disclosure**: Minimal → Balanced → Documents → Content
- **Convenience Parameters**: No query syntax needed
- **Context Reduction**: 95-99% token savings in discovery
- **Cross-MCP Integration**: Seamless linking with PTAB, FPD, Citations, and Pinecone (Assistant or RAG)
- **Capability-Ordered Extraction**: Native text layer first; OCR only for a scanned page that has none
- **Professional Workflows**: Litigation, due diligence, prior art, prosecution
