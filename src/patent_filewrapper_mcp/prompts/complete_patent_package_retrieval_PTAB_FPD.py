"""Complete Patent Package Retrieval Ptab Fpd Prompt"""

from . import mcp

@mcp.prompt(
    name="complete_patent_package_retrieval_PTAB_FPD",
    description="Retrieve organized patent document package with cross-MCP intelligence. At least ONE identifier required (patent_number, application_number, or title_keywords). package_type: basic/prosecution/full (default: prosecution). Basic: 4 docs | Prosecution: 10-15 docs + PTAB/FPD | Full: 20-40 docs. Requires PFW + PTAB + FPD MCPs."
)
async def complete_patent_package_retrieval_PTAB_FPD_prompt(
    patent_number: str = "",
    application_number: str = "",
    title_keywords: str = "",
    package_type: str = "prosecution"
) -> str:
    """
    Complete patent package retrieval with cross-MCP intelligence integration.

    Identifier fields (at least ONE required):
    - patent_number: US patent number (e.g., "7971071", "7,971,071")
    - application_number: Application number (e.g., "11752072", "11/752,072")
    - title_keywords: Keywords from patent title (e.g., "integrated delivery device")

    Package type options:
    - basic: Abstract, Drawings, Specification, Claims (4 docs, ~10-20 pages)
    - prosecution: Basic + NOA + Office Actions + Citations + PTAB/FPD intelligence (10-15 docs, ~40-80 pages) [DEFAULT]
    - full: Complete prosecution history + RCE + Interviews (20-40 docs, ~100-300 pages)

    Returns organized package with status tracking, cross-MCP red flag analysis, and browser-ready download links.
    """
    return f"""# Complete Patent Package Retrieval (PTAB/FPD Integrated)

Inputs:
- Patent Number: "{patent_number}"
- Application Number: "{application_number}"
- Title Keywords: "{title_keywords}"
- Package Type: {package_type}

---

## PHASE 1: Identifier Resolution & Status Validation

### Step 1: Smart Input Processing

Try patent number first (if provided):
```python
if patent_number:
    results = await pfw_search_applications_minimal(
        query=patent_number,  # Tool handles normalization
        fields=["applicationNumberText", "patentNumber", "inventionTitle",
                "applicationStatusDescription", "patentIssueDate"],
        limit=1
    )
    if results['count'] > 0:
        app_number = results['applications'][0]['applicationNumberText']
        patent_num = results['applications'][0]['applicationMetaData']['patentNumber']
        title = results['applications'][0]['applicationMetaData']['inventionTitle']
        status = results['applications'][0]['applicationMetaData']['applicationStatusDescription']
        confidence = 1.0
        source = "patent_number"
```

Fallback to application number:
```python
elif application_number:
    results = await pfw_search_applications_minimal(
        query=application_number,
        fields=["applicationNumberText", "patentNumber", "inventionTitle",
                "applicationStatusDescription"],
        limit=1
    )
    # Same processing as above
    confidence = 1.0
    source = "application_number"
```

Fallback to fuzzy title search:
```python
elif title_keywords:
    results = await pfw_search_applications_minimal(
        query=title_keywords,
        fields=["applicationNumberText", "patentNumber", "inventionTitle",
                "applicationStatusDescription"],
        limit=10
    )
    # Present options to user for selection
    # Note: May require user confirmation if multiple matches
    confidence = 0.7
    source = "fuzzy_search"
```

### Step 2: Display Resolution Summary

```python
print("# Patent Package Request")
print(f"**Application:** {{app_number}}")
print(f"**Patent:** {{patent_num if patent_num else 'Pending'}}")
print(f"**Status:** {{status}}")  # NEW: Shows Patented/Abandoned/Expired/etc.
print(f"**Title:** {{title}}")
print(f"**Resolution Source:** {{source}} (Confidence: {{confidence}})")
print()
```

**Status Examples:**
- "Patented Case" - Active granted patent
- "Abandoned  --  Failure to Respond to an Office Action" - Prosecution failure
- "Expired - Fee Related" - Maintenance fees not paid

---

## PHASE 2: Package Retrieval Strategy

### BASIC PACKAGE (package_type="basic")
**Use Case:** Quick review, portfolio cataloging
**Documents:** 4 core (ABST, DRW, SPEC, CLM)
**Pages:** 10-20 typical
**API Calls:** 1

```python
# Single tool call - returns all 4 components with download links
basic_package = await pfw_get_granted_patent_documents_download(
    app_number=app_number,
    include_drawings=True,
    generate_persistent_links=True  # 7-day encrypted access
)

# Extract download links (already formatted in response)
for component in ['abstract', 'drawings', 'specification', 'claims']:
    doc = basic_package['granted_patent_components'][component]
    print(f"**📁 [Download {{doc['document_description']}} "
          f"({{doc['page_count']}} pages)]({{doc['proxy_download_url']}})**")
```

**Status:** Complete implementation shown - no additional guidance needed

---

### PROSECUTION PACKAGE (package_type="prosecution") [DEFAULT]
**Use Case:** Due diligence, licensing, litigation prep
**Documents:** 10-15 key documents (Basic + NOA + Office Actions + Citations)
**Pages:** 40-80 typical
**API Calls:** 5-6 filtered

```python
# Step 1: Get basic package
basic_package = await pfw_get_granted_patent_documents_download(
    app_number=app_number,
    include_drawings=True,
    generate_persistent_links=True
)

# Step 2: Get prosecution documents with strategic filtering
prosecution_docs = []

doc_configs = [
    ('NOA', 'Notice of Allowance', 1),      # Examiner's approval reasoning
    ('CTFR', 'Final Rejections', 3),        # Final office actions
    ('CTNF', 'Non-Final Rejections', 5),    # Non-final office actions
    ('892', 'Examiner Citations', 1),        # Prior art cited by examiner
    ('1449', 'Applicant Citations', 2)       # Prior art disclosed by applicant
]

for doc_code, doc_name, max_limit in doc_configs:
    # Get document metadata
    docs_response = await pfw_get_application_documents(
        app_number=app_number,
        document_code=doc_code,
        limit=max_limit
    )

    # Extract and generate download links
    if docs_response.get('documentBag'):
        for doc in docs_response['documentBag'][:max_limit]:
            doc_id = doc['documentIdentifier']

            # Generate persistent download link (7-day access)
            download_link = await pfw_get_document_download(
                app_number=app_number,
                document_identifier=doc_id,
                generate_persistent_link=True
            )

            # Store for presentation
            prosecution_docs.append({{
                'type': doc_name,
                'code': doc_code,
                'url': download_link['proxy_download_url'],
                'pages': doc['downloadOptionBag'][0]['pageTotalQuantity'],
                'date': doc['officialDate']
            }})
```

**Guidance Reference:** For complete document code reference, see `pfw_get_guidance(section='documents')`

---

### FULL PACKAGE (package_type="full")
**Use Case:** Deep litigation research, IPR proceedings, expert witness prep
**Documents:** 20-40 documents (Prosecution + RCE + Interviews + Affidavits)
**Pages:** 100-300 typical
**API Calls:** 10-15 filtered

```python
# Start with prosecution package
full_package = prosecution_docs.copy()

# Add comprehensive document retrieval with smart filtering
additional_codes = [
    ('RCEX', 'RCE Requests', 5),           # Continued Examination Requests
    ('A...', 'Amendments', 10),             # Amendment/Response documents
    ('INTERVIEW', 'Interview Summaries', 5), # Examiner interviews
    ('OATH', 'Declarations/Affidavits', 3)   # Supporting declarations
]

# Use same loop structure as prosecution package above
for doc_code, doc_name, max_limit in additional_codes:
    # ... (repeat download link generation for each document type)
    pass

# WARNING: For heavily-prosecuted applications (200+ docs), this can cause
# token explosion. Always use document_code filtering, never request all documents.
# DO NOT USE direction_category='INCOMING'/'OUTGOING' without document_code filters!
```

**Critical Guidance:** For heavily-prosecuted applications and cost optimization, see `pfw_get_guidance(section='documents')`

---

## PHASE 3: Cross-MCP Intelligence Integration

### Check for Red Flags Across USPTO Systems

```python
# Initialize intelligence summary
cross_mcp_intel = {{
    'petitions': {{'count': 0, 'red_flag': False, 'message': 'No petitions found'}},
    'ptab': {{'count': 0, 'red_flag': False, 'message': 'No PTAB challenges'}},
    'citations': {{'available': False, 'message': 'Check citation data (2017+)'}}
}}

# FPD: Check for petition history (procedural red flags)
try:
    petitions = await fpd_search_petitions_by_application(
        application_number=app_number
    )
    if petitions.get('count', 0) > 0:
        cross_mcp_intel['petitions'] = {{
            'count': petitions['count'],
            'red_flag': True,
            'message': f"WARNING: Found {{petitions['count']}} petition(s) - indicates prosecution issues",
            'details': 'Missed deadlines, examiner disputes, or procedural problems'
        }}
except:
    pass  # No petitions found or FPD MCP unavailable

# PTAB: Check for post-grant challenges (if patented)
if patent_num:
    try:
        ptab = await ptab_search_proceedings_minimal(
            patent_number=patent_num,
            limit=10
        )
        if ptab.get('count', 0) > 0:
            cross_mcp_intel['ptab'] = {{
                'count': ptab['count'],
                'red_flag': True,
                'message': f"PTAB ALERT: {{ptab['count']}} challenge(s) found",
                'details': 'Patent validity challenged in post-grant proceedings (IPR/PGR/CBM)'
            }}
    except:
        pass  # No PTAB challenges or PTAB MCP unavailable

# Enhanced Citations: Check for examiner behavior patterns (2017+ only)
# Note: Citations API only covers office actions from 2017-10-01 forward
try:
    filing_date = results['applications'][0].get('filingDate')  # Check eligibility
    # Only query if application filed 2015+ (accounts for 1-2 year lag to first OA)
    if filing_date and int(filing_date[:4]) >= 2015:
        citations = await citations_search_citations_minimal(
            application_number=app_number,
            limit=5
        )
        if citations.get('count', 0) > 0:
            cross_mcp_intel['citations'] = {{
                'available': True,
                'count': citations['count'],
                'message': f"Citation data available ({{citations['count']}} citations)"
            }}
except:
    pass  # Citations not available (pre-2017 OA data)
```

**PTAB MCP Integration:**
- Tool: `ptab_search_proceedings_minimal(patent_number='...')`
- Detects: IPR (Inter Partes Review), PGR (Post-Grant Review), CBM (Covered Business Method)
- Red Flags: Any active or instituted challenges to patent validity

**FPD MCP Integration:**
- Tool: `fpd_search_petitions_by_application(application_number='...')`
- Detects: Revival petitions, examiner disputes, denied petitions, appeal petitions
- Red Flags: Denied petitions (serious issues), multiple petitions (systemic problems)

**Citations MCP Integration:**
- Tool: `citations_search_citations_minimal(application_number='...')`
- Available: Office actions dated 2017-10-01 or later only
- Insights: Examiner citation patterns, art unit trends

**Guidance Reference:** For complete four-MCP lifecycle analysis workflows, see `pfw_get_guidance(section='workflows_complete')`

---

## PHASE 4: Enhanced Presentation

### Format Complete Package with Intelligence Summary

```python
print("# Complete Patent Package")
print(f"**Application:** {{app_number}}")
print(f"**Patent:** {{patent_num if patent_num else 'Pending'}}")
print(f"**Status:** {{status}}")  # Shows active/abandoned/lapsed status
print(f"**Title:** {{title}}")
print()

# Intelligence Summary
has_red_flags = any(intel.get('red_flag', False) for intel in cross_mcp_intel.values())

if has_red_flags:
    print("## RED FLAGS DETECTED")
    for system, intel in cross_mcp_intel.items():
        if intel.get('red_flag'):
            print(f"- {{intel['message']}}")
            if 'details' in intel:
                print(f"  _{{intel['details']}}_")
    print()
else:
    print("## Clean Prosecution History")
    for system, intel in cross_mcp_intel.items():
        print(f"- {{intel['message']}}")
    print()

# Basic Package Section
print("## Granted Patent Components (4 documents)")
for component in ['abstract', 'drawings', 'specification', 'claims']:
    doc = basic_package['granted_patent_components'][component]
    print(f"**📁 [Download {{doc['document_description']}} "
          f"({{doc['page_count']}} pages)]({{doc['proxy_download_url']}})**")
print()

# Prosecution Documents Section (if requested)
if package_type in ['prosecution', 'full'] and prosecution_docs:
    print(f"## Prosecution History ({{len(prosecution_docs)}} documents)")

    # Group by document type
    by_type = {{}}
    for doc in prosecution_docs:
        if doc['type'] not in by_type:
            by_type[doc['type']] = []
        by_type[doc['type']].append(doc)

    # Present organized by category
    for doc_type, docs in by_type.items():
        print(f"### {{doc_type}}")
        for doc in docs:
            date_str = doc['date'][:10] if doc['date'] else 'Unknown'
            print(f"**📁 [Download ({{doc['pages']}} pages)]({{doc['url']}})** - {{date_str}}")
    print()

# Summary Footer
total_docs = 4 + len(prosecution_docs)
total_pages = basic_package.get('total_pages', 0) + sum(d['pages'] for d in prosecution_docs)
print(f"**Total Package:** {{total_pages}} pages across {{total_docs}} documents")
```

---

## PHASE 5: Error Handling & Edge Cases

### Common Issues & Solutions

**Issue: Patent not yet granted**
```python
try:
    basic_package = await pfw_get_granted_patent_documents_download(
        app_number=app_number,
        include_drawings=True
    )
except:
    # Fall back to application documents
    print("Note: Patent not yet granted, retrieving available prosecution documents")
    # Use get_application_documents with SPEC/CLM/DRW codes
    basic_package = await pfw_get_application_documents(
        app_number=app_number,
        document_code='SPEC|CLM|DRW|ABST',
        limit=10
    )
```

**Issue: Application filed before 2001**
```python
filing_date = results['applications'][0].get('filingDate')
if filing_date and int(filing_date[:4]) < 2001:
    print("Note: Pre-2001 application - XML not available, using document downloads only")
    # Skip XML extraction, use document downloads
```

**Issue: Fuzzy search returns multiple matches**
```python
if search_strategy == "fuzzy_search" and results['count'] > 1:
    print(f"Found {{results['count']}} matches. Please select:")
    for i, app in enumerate(results['applications'][:10]):
        title = app['applicationMetaData']['inventionTitle']
        app_number = app['applicationNumberText']
        print(f"{{i+1}}. {{title}} - {{app_number}}")
    # User must select which application to retrieve
```

**Issue: Cross-MCP services unavailable**
```python
# All cross-MCP calls are wrapped in try/except blocks
# Services gracefully degrade if PTAB/FPD/Citations MCPs unavailable
# Package still retrieves PFW documents, just without cross-MCP intelligence
```

**Guidance Reference:** For comprehensive error handling patterns, see `pfw_get_guidance(section='errors')`

---

## Package Selection Guide

**Quick Review / Portfolio Cataloging:**
- Use `basic` package - 4 core documents, 10-20 pages
- Fast execution, minimal API calls

**Due Diligence / Licensing / General Analysis:**
- Use `prosecution` package (default) - 10-15 key documents, 40-80 pages
- Includes cross-MCP intelligence for red flag detection

**Deep Litigation / IPR / Expert Witness Prep:**
- Use `full` package - 20-40 documents, 100-300 pages
- WARNING: Can be large for heavily-prosecuted patents (200+ docs in file)

---

## Cross-Reference Opportunities

**Inventor Research:**
- Run `inventor_portfolio_analysis` for inventor track record

**Petition Analysis (if red flags detected):**
- Deep dive: `fpd_get_petition_details` for full petition reasoning
- Tool: FPD MCP

**PTAB Challenge Analysis (if red flags detected):**
- Deep dive: `ptab_search_proceedings_balanced` for detailed PTAB analysis
- Tool: PTAB MCP

**Art Unit Quality Assessment:**
- Assess prosecution quality patterns: `fpd_search_petitions_by_art_unit`
- Identify systemic examiner/art unit issues

---

## Cost & Token Optimization

**API Call Efficiency:**
- Basic Package: 1 call (minimal context)
- Prosecution Package: 6 calls (optimized with document_code filters)
- Full Package: 15 calls (still filtered, but comprehensive)

**Context Reduction:**
- Ultra-minimal fields for discovery: 99% reduction vs full response
- Document code filtering: 95-99% reduction (10-15 docs vs 150+ total)
- Persistent links: No repeated document metadata in context

**Cost Optimization Hierarchy:**
1. XML extraction (free) - try first for patents/applications
2. PyPDF2 extraction (free) - works for 80%+ of documents
3. Mistral OCR ($0.001-0.003/page) - only for scanned/poor quality docs

---

## COMPLETE WORKFLOW SUMMARY

### What This Template Provides:

**Flexible Input Handling:**
- Accepts patent number, application number, OR title keywords
- Smart priority resolution with confidence scoring
- Fuzzy search fallback for partial information

**Status Tracking:**
- Displays patent status prominently in header
- Identifies abandoned/expired/lapsed patents
- Includes status in intelligence summary

**Progressive Disclosure:**
- Basic (4 docs) → Prosecution (10-15) → Full (20-40)
- Token-optimized with 95-99% context reduction
- Strategic document filtering to avoid bloat

**Complete Implementation:**
- Shows actual tool calls with parameters
- Includes download link generation workflow
- Demonstrates persistent link handling (7-day access)
- Proper result aggregation shown

**Cross-MCP Intelligence:**
- FPD petition red flags (procedural issues)
- PTAB challenge vulnerability (validity threats)
- Enhanced Citations examiner patterns (2017+)

**Attorney-Ready Presentation:**
- Clickable markdown download links
- Organized by document category
- Intelligence summary with red flags highlighted
- Use case recommendations and next steps

**Error Handling:**
- Graceful degradation for unavailable services
- Clear user guidance for ambiguous cases
- Fallbacks for pre-2001 applications

---

**Ready to retrieve complete patent package? The system handles identifier resolution, package assembly, cross-MCP intelligence, and presentation automatically.**"""



