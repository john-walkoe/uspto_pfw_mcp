"""Document Filtering Assistant Prompt"""

from . import mcp

@mcp.prompt(
    name="document_filtering_assistant",
    description="Purpose-driven document filtering with intelligent prioritization and download workflow. At least ONE identifier required (patent_number, application_number, or title_keywords). research_purpose: litigation/due_diligence/prior_art/portfolio_review (default: litigation). Requires PFW MCP."
)
async def document_filtering_assistant_prompt(
    patent_number: str = "",
    application_number: str = "",
    title_keywords: str = "",
    research_purpose: str = "litigation"
) -> str:
    """
    Smart document filtering with flexible identifier input and purpose-driven strategies.

    Identifiers (at least ONE required): patent_number, application_number, or title_keywords

    Research purposes:
    - litigation: NOA, rejections, citations, claims (full package) [DEFAULT]
    - due_diligence: Comprehensive prosecution history (prosecution package)
    - prior_art: Technical content, examiner citations (basic + citations)
    - portfolio_review: Abstract, claims, NOA (prosecution package)
    """

    purpose_strategies = {
        "litigation": {
            "priority": "NOA → Office Actions → Examiner Citations → Claims",
            "focus": "Examiner reasoning, prior art analysis, claim interpretation",
            "recommended_package": "full",
            "complexity": "high",
            "doc_codes": ["NOA", "CTFR", "CTNF", "892", "CLM", "A..."]
        },
        "due_diligence": {
            "priority": "Abstract → Claims → Citations → NOA",
            "focus": "Patent scope, prior art density, prosecution difficulty",
            "recommended_package": "prosecution",
            "complexity": "medium",
            "doc_codes": ["ABST", "CLM", "NOA", "892", "1449"]
        },
        "prior_art": {
            "priority": "XML → Examiner Citations → Claims → Specification",
            "focus": "Technical content, cited references, claim scope",
            "recommended_package": "basic",
            "complexity": "low",
            "doc_codes": ["892", "1449", "CLM", "SPEC"]
        },
        "portfolio_review": {
            "priority": "Abstract → Claims → NOA → Filing Details",
            "focus": "Patent value, prosecution quality, strategic importance",
            "recommended_package": "prosecution",
            "complexity": "medium",
            "doc_codes": ["ABST", "CLM", "NOA"]
        }
    }

    strategy = purpose_strategies.get(research_purpose, purpose_strategies["litigation"])

    return f"""# Smart Document Filtering Assistant

**Research Purpose:** {research_purpose.title()}
**Strategy:** {strategy.get("priority")}
**Recommended Package:** {strategy.get("recommended_package")}
**Focus:** {strategy.get("focus")}

**Inputs Provided:**
- Patent Number: "{patent_number}"
- Application Number: "{application_number}"
- Title Keywords: "{title_keywords}"

---

## PHASE 1: Identifier Resolution

### Step 1: Process and Validate Inputs

```python
# Try patent number first (if provided)
if patent_number:
    results = await pfw_search_applications_minimal(
        query=patent_number,
        fields=['applicationNumberText', 'patentNumber', 'inventionTitle',
                'applicationStatusDescription'],
        limit=1
    )
    if results['count'] > 0:
        app_number = results['applications'][0]['applicationNumberText']
        patent_num = results['applications'][0]['applicationMetaData']['patentNumber']
        title = results['applications'][0]['applicationMetaData']['inventionTitle']

# Fallback to application number
elif application_number:
    results = await pfw_search_applications_minimal(
        query=application_number,
        fields=['applicationNumberText', 'patentNumber', 'inventionTitle'],
        limit=1
    )

# Fallback to fuzzy title search
elif title_keywords:
    results = await pfw_search_applications_minimal(
        query=title_keywords,
        fields=['applicationNumberText', 'patentNumber', 'inventionTitle'],
        limit=10
    )
    # May require user selection if multiple matches
```

---

## PHASE 2: Purpose-Driven Document Retrieval

### RECOMMENDED APPROACH: Use Existing Package Prompt

**For comprehensive workflow with download links:**
```python
# Use the complete package retrieval prompt
await complete_patent_package_retrieval_PTAB_FPD(
    patent_number=patent_number if patent_number else "",
    application_number=app_number,
    package_type='{strategy.get("recommended_package")}'
)
```

This handles identifier resolution, download link generation, and presentation automatically.

---

### ALTERNATIVE: Manual Document Filtering

**For customized document selection:**

{"#### Litigation Research - Priority Documents" if research_purpose == "litigation" else ""}
{'''
```python
# Priority 1: Notice of Allowance (examiner reasoning)
noa_docs = await pfw_get_application_documents(
    app_number=app_number,
    document_code='NOA',
    limit=1
)

# Priority 2: Office Actions (rejection analysis)
office_actions = await pfw_get_application_documents(
    app_number=app_number,
    document_code='CTFR|CTNF',  # Final and Non-Final rejections
    limit=5
)

# Priority 3: Examiner Citations (prior art)
examiner_cites = await pfw_get_application_documents(
    app_number=app_number,
    document_code='892',
    limit=1
)

# Priority 4: Claims (claim interpretation)
claims = await pfw_get_application_documents(
    app_number=app_number,
    document_code='CLM',
    limit=10  # Includes as-filed and amended claims
)

# Priority 5: Amendments (prosecution strategy)
amendments = await pfw_get_application_documents(
    app_number=app_number,
    document_code='A...',  # All amendment types
    limit=5
)

# Generate download links for each document
litigation_package = []
for doc_response in [noa_docs, office_actions, examiner_cites, claims, amendments]:
    if doc_response.get('documentBag'):
        for doc in doc_response['documentBag']:
            doc_id = doc['documentIdentifier']
            download_link = await pfw_get_document_download(
                app_number=app_number,
                document_identifier=doc_id,
                generate_persistent_link=True
            )
            litigation_package.append({
                'type': doc['documentDescription'],
                'url': download_link['proxy_download_url'],
                'pages': doc['downloadOptionBag'][0]['pageTotalQuantity']
            })
```

**Typical Litigation Package:** 15-25 documents, 150-300 pages
''' if research_purpose == "litigation" else ""}

{"#### Due Diligence - Core Documents" if research_purpose == "due_diligence" else ""}
{'''
```python
# Priority 1: Abstract and Claims (patent scope)
basic_docs = await pfw_get_application_documents(
    app_number=app_number,
    document_code='ABST|CLM',
    limit=10
)

# Priority 2: Citations (prior art landscape)
citations = await pfw_get_application_documents(
    app_number=app_number,
    document_code='892|1449',  # Examiner and applicant citations
    limit=3
)

# Priority 3: Notice of Allowance (prosecution outcome)
noa = await pfw_get_application_documents(
    app_number=app_number,
    document_code='NOA',
    limit=1
)

# Generate download links (same pattern as above)
```

**Typical Due Diligence Package:** 10-15 documents, 40-80 pages
''' if research_purpose == "due_diligence" else ""}

{"#### Prior Art Research - Technical Content" if research_purpose == "prior_art" else ""}
{'''
```python
# Priority 1: XML (FREE technical content - no OCR costs)
xml_content = await pfw_get_patent_or_application_xml(
    app_number=app_number
)
# Extract: abstract, claims, description from structured XML

# Priority 2: Examiner Citations (prior art cited by examiner)
examiner_cites = await pfw_get_application_documents(
    app_number=app_number,
    document_code='892',
    limit=1
)

# Priority 3: Applicant Citations (IDS, 1449)
applicant_cites = await pfw_get_application_documents(
    app_number=app_number,
    document_code='1449|IDS',
    limit=2
)

# Priority 4: Claims (for claim scope analysis)
claims = await pfw_get_application_documents(
    app_number=app_number,
    document_code='CLM',
    limit=5
)
```

**Typical Prior Art Package:** 4-8 documents + XML, 20-40 pages
''' if research_purpose == "prior_art" else ""}

{"#### Portfolio Review - Strategic Documents" if research_purpose == "portfolio_review" else ""}
{'''
```python
# Priority 1: Abstract (quick overview)
abstract = await pfw_get_application_documents(
    app_number=app_number,
    document_code='ABST',
    limit=1
)

# Priority 2: Claims (patent scope)
claims = await pfw_get_application_documents(
    app_number=app_number,
    document_code='CLM',
    limit=3  # As-filed and final claims
)

# Priority 3: NOA (prosecution quality indicator)
noa = await pfw_get_application_documents(
    app_number=app_number,
    document_code='NOA',
    limit=1
)
```

**Typical Portfolio Review Package:** 5-8 documents, 15-30 pages
''' if research_purpose == "portfolio_review" else ""}

---

## PHASE 3: Presentation & Organization

### Format Results by Priority

```python
# Organize documents by priority
print(f"# {{research_purpose.title()}} Document Package")
print(f"**Application:** {{app_number}}")
print(f"**Patent:** {{patent_num if patent_num else 'Pending'}}")
print()

# Group by document type
by_type = {{}}
for doc in litigation_package:  # or other package variable
    if doc['type'] not in by_type:
        by_type[doc['type']] = []
    by_type[doc['type']].append(doc)

# Present in priority order
priority_order = {strategy.get("doc_codes")}
for doc_code in priority_order:
    if doc_code in by_type:
        docs = by_type[doc_code]
        print(f"### {{doc_code}} Documents ({{len(docs)}})")
        for doc in docs:
            print(f"**📁 [Download ({{doc['pages']}} pages)]({{doc['url']}})**")
        print()
```

---

## PHASE 4: Content Extraction (Optional)

### Text Extraction for Analysis

```python
# For documents requiring text analysis
for doc in litigation_package:
    # Extract text content with auto PyPDF2/OCR fallback
    content = await pfw_get_document_content(
        app_number=app_number,
        document_identifier=doc['document_id'],
        max_pages=50  # Limit for large documents
    )

    # Content includes: text, quality_score, method_used (pypdf2 or ocr)
    print(f"Extracted {{len(content['text'])}} characters from {{doc['type']}}")
```

**Cost Note:** PyPDF2 is free (80%+ success rate), Mistral OCR is $0.001-0.003/page (fallback)

---

## Strategy Summary

| Purpose | Package | Complexity | Key Documents | Typical Pages |
|---------|---------|------------|---------------|---------------|
| Litigation | Full | High | NOA, OA, Citations, Claims, Amendments | 150-300 |
| Due Diligence | Prosecution | Medium | Abstract, Claims, Citations, NOA | 40-80 |
| Prior Art | Basic + XML | Low | XML, Citations (892/1449), Claims | 20-40 |
| Portfolio Review | Prosecution | Medium | Abstract, Claims, NOA | 15-30 |

---

## Related Workflows

**Litigation Preparation:**
- Use `litigation_research_setup_PTAB_FPD` for complete litigation package with cross-MCP intelligence

**Due Diligence:**
- Use `complete_patent_package_retrieval_PTAB_FPD` with `package_type='prosecution'`
- Add PTAB/FPD checks for risk assessment

**Prior Art Research:**
- Use `prior_art_analysis_CITATION` for enhanced examiner citation analysis (2017+)
- Use `pfw_get_patent_or_application_xml` for FREE technical content

**Portfolio Review:**
- Use `inventor_portfolio_analysis` for inventor-level insights
- Use `technology_landscape_mapping_PTAB` for competitive context

---

**Result:** Purpose-optimized document package with intelligent prioritization, complete download workflow, and efficient token usage."""



