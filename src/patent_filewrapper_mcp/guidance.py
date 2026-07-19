"""Sectioned guidance content for pfw_get_guidance (audit: metrics 6/10 —
~950 lines of pure string literals carved out of main.py).

Every function returns a static markdown string; get_guidance_sections()
exposes the section->content mapping the tool dispatches on.
"""


def get_guidance_sections() -> dict:
    """Section name -> guidance content, as served by pfw_get_guidance."""
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
        "tools": _get_tools_section(),
        "errors": _get_errors_section(),
        "advanced": _get_advanced_section(),
        "cost": _get_cost_section(),
    }

# =============================================================================

def _get_overview_section() -> str:
    """Overview section with available sections and quick reference"""
    return """## Available Sections and Quick Reference

### 🎯 Quick Reference Chart - What section for your question?

- 🔍 **"Find patents by inventor/company/art unit"** → `fields`
- 📄 **"Get complete patent package/documents"** → `documents`
- 🔖 **"Decode document codes (NOA, CTFR, 892, etc.)"** → `document_codes`
- 🤝 **"Research IPR vs prosecution patterns"** → `workflows_ptab`
- 🚩 **"Analyze petition red flags + prosecution"** → `workflows_fpd`
- 📊 **"Citation analysis for examiner behavior"** → `workflows_citations`
- 🧠 **"Domain-based RAG for legal framework (§101, §103, §112)"** → `workflows_pinecone`
- 🏢 **"Complete company due diligence"** → `workflows_complete`
- ⚙️ **"Tool guidance and parameters"** → `tools`
- ❌ **"Search errors or download issues"** → `errors`
- 💰 **"Reduce API costs and optimize usage"** → `cost`

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
- **fields**: Field selection strategies and context reduction
- **tools**: Tool-specific guidance and parameters
- **errors**: Common error patterns and troubleshooting
- **advanced**: Advanced workflows and optimization
- **cost**: Cost optimization strategies

### Context Efficiency Benefits:
- **95% token reduction** (1-12KB per section vs 62KB total)
- **Targeted guidance** for specific workflows
- **Same comprehensive content** organized for efficiency
- **Backwards compatible** with MCP Resources"""

def _get_tools_section() -> str:
    """Tools section with tool-specific guidance"""
    return """## All 14 PFW MCP Tools

### Always-Loaded Tools (3) — Available immediately, no tool search required
- **search_applications_minimal** — Primary entry point: high-volume discovery (15 preset fields or custom ultra-minimal). Use first.
- **get_application_documents** — Get prosecution document metadata, filter by document code (CTNF, NOA, 892, etc.)
- **PFW_get_guidance** — Context-efficient sectioned guidance (this tool). Use section parameter for targeted help.

### Search Tools (5) — Deferred, loaded on demand
- **search_applications** — Full search with custom field selection
- **search_applications_balanced** — Detailed analysis with 18 fields including cross-MCP integration fields
- **search_inventor** — Inventor search with custom fields
- **search_inventor_minimal** — Efficient inventor portfolio discovery
- **search_inventor_balanced** — Comprehensive inventor analysis

### Document & Content Tools (4) — Deferred, loaded on demand
- **PFW_get_document_content_with_ocr** — 3-tier text extraction: PyPDF2 → Mistral OCR → Docling (free). Use for prosecution docs.
- **PFW_get_document_download** — Secure proxy download URL for browser access. Pass to attorney for formatted PDF.
- **get_patent_or_application_xml** — Structured XML content (claims, abstract, etc.) with 91-99% token reduction via include_raw_xml=False
- **get_granted_patent_documents_download** — All granted patent components (abstract, claims, drawings, spec) as download links

### Office Action Tools (2) — Deferred, loaded on demand. Coverage: Oct 1, 2017 forward.
- **get_oa_rejections** — Rejection indicators: hasRej101/102/103/112, Alice/Bilski/Mayo/Myriad flags, citation counts. Structured data, small context.
- **get_oa_text** — Full office action body text or section-filtered (101/102/103/112). Use section= for targeted rejection text. No PDF/OCR needed.

### Admin Tool (optional, not counted above)
- **pfw_manage_users** — Registered-user management. Only registered when PFW_ENABLE_USER_MANAGEMENT=true (OAuth deployments); requires the pfw:admin scope. Absent in STDIO.

## Progressive Disclosure Strategy

### Stage 1: Discovery (Minimal Search)
- Use `search_applications_minimal` for broad exploration
- 15 preset fields (~500 chars/result) OR custom fields (~100 chars/result)
- Present top results to user for selection on vague queries

### Stage 2: Analysis (Balanced Search)
- Use `search_applications_balanced` for detailed metadata
- 18+ fields including cross-MCP integration fields (~2KB/result)
- Limit to 10-20 user-selected results

### Stage 3: Documents
- Use `get_application_documents` to see document metadata
- Strategic selection of most valuable documents

### Stage 4: Content
- Try `get_patent_or_application_xml` first (free)
- Use document extraction tools for prosecution documents
- Use proxy downloads for browser access

## XML Field Selection (get_patent_or_application_xml)

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
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['claims'],
    include_raw_xml=False
)
```
Use for: Claim construction, infringement analysis, claim scope assessment

**Claims + Citations without raw XML (~2.5K tokens):**
```python
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['claims', 'citations'],
    include_raw_xml=False
)
```
Use for: Prior art analysis, claim differentiation
Note: Consider uspto_enriched_citation_mcp for deeper citation trees

**Inventors + Applicants without raw XML (~500 tokens - 99% reduction!):**
```python
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['inventors', 'applicants'],
    include_raw_xml=False
)
```
Use for: Portfolio reports, entity analysis, assignment tracking

**Default fields without raw XML (~5K tokens):**
```python
pfw_get_patent_or_application_xml(
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
- Check if metadata already available from pfw_search_applications_balanced
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

### Most Important Document Types
- **CTFR**: Office Action (rejection/objection)
- **NOA**: Notice of Allowance (examiner's final reasoning)
- **892**: Examiner's Prior Art Citations
- **N417**: Applicant Amendment/Response
- **INTERVIEW**: Examiner Interview Summary

### Document Selection by Use Case

#### Litigation Research
**Priority:** NOA → Final CTFR → 892 → N417
**Focus:** Examiner's reasoning and prior art analysis

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
- **FROM_USPTO**: CTFR, NOA, 892, INTERVIEW (examiner to applicant)
- **FROM_APPLICANT**: N417, FEE, PETITION (applicant to USPTO)
- **SYSTEM_GENERATED**: PUB, PTX, status updates

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

## Cost Optimization

### Document Extraction Hierarchy
1. **XML Content (Free)**: Try first for patents/applications
2. **PyPDF2 (Free)**: Works for 80%+ of patent documents
3. **Mistral OCR ($0.001-0.003)**: Only for scanned/poor quality

### Typical OCR Costs
- Standard office action: $0.001-0.002 (2-4 pages)
- Complex office action: $0.002-0.003 (5-8 pages)
- Notice of allowance: $0.001 (1-2 pages)
- Patent specification: $0.005-0.015 (20-50 pages)

### Smart Cost Management
- Always try XML first for patents
- Use PyPDF2 before OCR
- Reserve OCR for critical documents
- Batch document extraction when possible"""

def _get_document_codes_section() -> str:
    """Comprehensive document code decoder for documentBag responses"""
    return """## Document Code Decoder (DocumentBag Reference)

### 📋 Most Common Prosecution Document Codes

**Quick tip:** Use these codes with `pfw_get_application_documents(app_number, document_code='CODE')`

---

### 🔴 Examiner Communications (FROM USPTO)

**Office Actions:**
- **CTNF** - Office Action (Non-Final Rejection) - Main examination document
- **CTFR** - Office Action (Final Rejection) - Closes prosecution
- **NOA** - Notice of Allowance - Examiner's final approval reasoning
- **SRFW** - Restriction/Election Requirement - Examiner requires applicant to elect claims

**Citations & Search:**
- **892** - Notice of References Cited (Examiner Citations) - Prior art cited by examiner
- **SRNT** - Examiner's Search Strategy and Results - Search methodology details
- **WFEE** - Issue Fee Due - Notice to pay issue fee after allowance

**Interviews & Communications:**
- **INTERVIEW** - Examiner Interview Summary - Official record of interview discussion
- **CTFREF** - Examiner's Answer (After Appeal Brief) - Examiner's response to appeal

---

### 🔵 Applicant Responses (FROM APPLICANT)

**Amendments:**
- **A.PE** - Preliminary Amendment - Filed before first office action
- **A...** - Amendment/Response After Non-Final - Response to non-final rejection
- **A.NE** - Response After Final Action - Amendment after final rejection
- **A.NA** - Amendment After Notice of Allowance (Rule 312) - Post-allowance amendment

**Requests & Filings:**
- **RCEX** - Request for Continued Examination (RCE) - Reopens closed prosecution
- **IDS** - Information Disclosure Statement - Applicant cites prior art
- **EXT** - Extension of Time Request - Request more time to respond
- **N417** - Applicant's Response/Amendment - Generic response document

**Citations:**
- **1449** - Information Disclosure Statement (PTO-1449) - Applicant citations with PTO form

---

### 📄 Patent Components (GRANTED PATENTS)

**Core Patent Documents:**
- **ABST** - Abstract - Brief invention summary
- **CLM** - Claims - Patent claims (as-filed or amended)
- **SPEC** - Specification - Detailed invention description
- **DRW** - Drawings - Patent drawings/figures
- **FWCLM** - File Wrapper Claims - Claims index/history

**Grant Documents:**
- **ISSUE** - Issue Notification - Patent has issued
- **PTX** - Patent Grant Full Text - Complete granted patent
- **BIB** - Bibliographic Data - Patent bibliographic info

---

### 📊 Administrative & Filing Documents

**Fees & Payments:**
- **FEE** - Fee Transmittal - Fee payment documentation
- **M844** - Entity Status Form (Small/Micro) - Entity status declaration
- **WFEE** - Issue Fee Payment - Issue fee transmittal

**Priority & Continuity:**
- **CONTIN** - Continuation Data Sheet - Priority/continuity claims
- **FORP** - Foreign Priority Certificate - Foreign priority documents
- **PRIORIT** - Certified Priority Document - Priority claim certification

**Status & Administrative:**
- **APPLICAT** - Application Data Sheet (ADS) - Formal application info
- **OATH** - Declaration/Oath - Inventor declaration
- **POA** - Power of Attorney - Attorney authorization
- **SB15** - Application Size Fee Determination - Size fee calculations

---

### 📑 Prosecution History Documents

**Appeal Documents:**
- **ABRF** - Appeal Brief - Applicant's appeal arguments
- **RPLY** - Reply Brief - Reply to examiner's answer
- **FDEC** - Appeal Decision - PTAB appeal decision

**Correspondence:**
- **WDRL** - Abandonment/Withdrawal - Application abandoned
- **PAS** - Pre-Appeal Brief Conference Request - Pre-appeal review
- **EXPARTE** - Ex Parte Reexamination - Reexamination request

---

### 📌 Usage Examples

**Get examiner's key documents:**
```python
# Examiner's citations
pfw_get_application_documents(app_number, document_code='892')

# Final office actions
pfw_get_application_documents(app_number, document_code='CTFR|CTNF')

# Allowance reasoning
pfw_get_application_documents(app_number, document_code='NOA')
```

**Get applicant's responses:**
```python
# All amendments
pfw_get_application_documents(app_number, document_code='A...')  # Wildcard matches all A. codes

# IDS submissions (for Citations MCP integration)
pfw_get_application_documents(app_number, document_code='IDS|1449')

# RCE filings
pfw_get_application_documents(app_number, document_code='RCEX')
```

**Get patent components:**
```python
# Core patent documents
pfw_get_application_documents(app_number, document_code='ABST|CLM|SPEC|DRW')

# Claims evolution
pfw_get_application_documents(app_number, document_code='CLM|FWCLM')
```

---

### 📚 Document Direction Quick Reference

**INCOMING (FROM APPLICANT):** A..., IDS, RCEX, EXT, N417, 1449, FEE, POA
**OUTGOING (FROM USPTO):** CTFR, CTNF, NOA, 892, INTERVIEW, WFEE, SRFW
**SYSTEM GENERATED:** ISSUE, PTX, BIB, PUB

---

### 🔍 Finding Rare/Unlisted Codes

For comprehensive code list (3,100+ codes), see `reference/Document_Descriptions_List.csv`.

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
1. **Find target patent**: `search_applications_balanced(query='applicationNumberText:16123456')`
2. **Get prosecution docs**: `get_application_documents(app_number='16123456')`
3. **Extract examiner reasoning**: Focus on NOA and final CTFR documents
4. **Analyze prior art**: Get 892 documents for examiner's search strategy
5. **Compare arguments**: Extract N417 responses to understand prosecution strategy

**Key Intelligence:** Examiner's allowance reasoning vs. challenger's arguments

### Due Diligence Workflow
**Scenario:** M&A patent portfolio assessment

**Steps:**
1. **Portfolio discovery**: `search_applications_minimal(applicant_name='Target Company', limit=100)`
2. **Quality assessment**: Use balanced search for high-value patents
3. **Red flag detection**: Look for multiple rejections, long prosecution, revival petitions
4. **Document analysis**: Extract NOAs and office actions for prosecution quality
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
- Use `search_applications_minimal` with broader query
- Try inventor or applicant name search
- Check application status and publication dates

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

def _get_fields_section() -> str:
    """Field selection strategies and context reduction"""
    return """## Field Selection & Context Reduction

### Progressive Disclosure Strategy

#### Stage 1: Discovery (95-99% reduction)
**Minimal Search (15 preset fields ~500 chars/result):**
- `search_applications_minimal` with default fields
- Good for 20-50 results

**Ultra-Minimal (2-3 custom fields ~100 chars/result):**
- `fields=["applicationNumberText", "inventionTitle"]`
- Perfect for 50-200 results
- 99% context reduction vs balanced

#### Stage 2: Analysis (85-95% reduction)
**Balanced Search (18+ fields ~2KB/result):**
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
    """Cost optimization strategies"""
    return """## Cost Optimization Strategies

### Document Extraction Costs

#### Free Methods (Always Try First)
1. **XML Content**: `get_patent_or_application_xml`
   - Patents and published applications
   - Structured data with claims, description, citations
   - No cost, fastest access

2. **PyPDF2 Extraction**: Automatic fallback in document tools
   - Works for 80%+ of patent documents
   - Free text extraction from PDFs
   - No OCR costs

#### Paid OCR (Only When Necessary)
**Mistral OCR**: ~$0.001-0.003 per document
- Used only for scanned/poor quality documents
- Automatic quality detection prevents unnecessary costs
- Cost transparency before extraction

### API Call Optimization

#### Progressive Disclosure (95% cost reduction)
```python
# Instead of expensive balanced search for discovery
results = search_applications_balanced(query="AI healthcare", limit=50)  # 100KB context

# Do efficient progressive disclosure
discovery = search_applications_minimal(query="AI healthcare", limit=50)  # 25KB context
# User selects 5 results
detailed = search_applications_balanced(selected_apps, limit=5)  # 10KB context
# Total: 35KB vs 100KB (65% reduction)
```

### Strategic Document Selection
1. **NOA** (Notice of Allowance): Examiner's final reasoning
2. **Final CTFR**: Last office action with complete analysis
3. **892** (Examiner Citations): Prior art search methodology
4. **Key N417**: Critical applicant responses"""

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
1. **Find PTAB trial**: `search_trials_balanced(patent_number='11123456')`
2. **Extract application number** from trial metadata (`respondentData.applicationNumber`)
3. **Get prosecution history**: `pfw_search_applications_balanced(query='applicationNumberText:16123456')`
4. **Document analysis**: `pfw_get_application_documents(app_number='16123456')`
5. **Compare reasoning**: Extract NOA vs PTAB Institution/FWD analysis

**Key Linking Fields:**
- `respondentData.applicationNumber` (PTAB → PFW)
- `respondentData.patentNumber` (PTAB → PFW)
- `applicationNumberText` (PFW → PTAB)
- `patentNumber` (PFW → PTAB)

**Appeals/Interferences**: Use `search_appeals_minimal()` or `search_interferences_minimal()` for non-trial proceedings"""

def _get_workflows_fpd_section() -> str:
    """FPD integration workflows"""
    return """## FPD Integration Workflows

### FPD Red Flag Detection
**Scenario:** Identify prosecution quality issues via petition history

**Workflow:**
1. **Portfolio scan**: `search_applications_minimal(applicant_name='Target', limit=100)`
2. **FPD check**: For each application, `fpd_search_petitions_by_application(app_number)`
3. **Red flag analysis**: Identify denied petitions, revival petitions, appeal petitions
4. **Prosecution correlation**: Get PFW data for applications with petition issues
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

**Workflow:**
1. **Technology Discovery**: `search_applications_minimal(query='autonomous vehicle', art_unit='3661', limit=50)`
2. **Citation Analysis**: For applications with office actions (2017+), get citation data
3. **Examiner Intelligence**: Focus on `examinerCitedReferenceIndicator=true` references
4. **Art Unit Patterns**: Identify frequently cited references in specific art units
5. **Effectiveness Assessment**: Correlate citation patterns with prosecution outcomes

**Enhanced Insights:** Citation patterns reveal examiner search preferences and reference effectiveness"""

def _get_workflows_complete_section() -> str:
    """Complete four-MCP lifecycle workflows"""
    return """## Complete Four-MCP Lifecycle Analysis

### Complete M&A Due Diligence
**Scenario:** Comprehensive patent intelligence across all USPTO databases

**Four-MCP Integration Workflow:**
1. **Portfolio Discovery (PFW)**: `search_applications_minimal(applicant_name='Target Company', filing_date_start='2015-01-01', limit=100)`
2. **Citation Intelligence (Citations)**: Analyze examiner citation patterns for prosecution quality (2017+ applications)
3. **FPD Risk Assessment (FPD)**: Check procedural irregularities and petition history
4. **PTAB Challenge Analysis (PTAB)**: Assess post-grant challenge exposure for granted patents
5. **Document Intelligence (PFW)**: Extract key prosecution documents for detailed analysis
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

