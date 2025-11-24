"""Prior Art Analysis Citation Prompt"""

from . import mcp

@mcp.prompt(
    name="prior_art_analysis_CITATION",
    description="Analyze examiner citation patterns and prior art effectiveness using prosecution history + citation intelligence. At least ONE identifier required (application_number, patent_number, or title_keywords). Citations data available Oct 1, 2017+ only. Requires PFW + Citations MCPs."
)
async def prior_art_analysis_CITATION_prompt(
    application_number: str = "",
    patent_number: str = "",
    title_keywords: str = ""
) -> str:
    """
    Citation-enhanced prior art analysis using examiner decision intelligence.

    Identifiers (at least ONE required): application_number, patent_number, or title_keywords
    IMPORTANT: Citations data available for office actions from October 1, 2017+ only
    """

    return f"""# Citation-Enhanced Prior Art Analysis

**Inputs:** App "{application_number}", Patent "{patent_number}", Title "{title_keywords}"
**Data Availability:** Citations MCP covers office actions from **Oct 1, 2017 onward**

---

## STEP 1: Application Discovery & Eligibility Check

```python
# Resolve identifier with filing date check
if patent_number:
    results = await pfw_search_applications_minimal(
        query=patent_number,
        fields=['applicationNumberText', 'filingDate', 'examinerNameText',
                'groupArtUnitNumber', 'patentNumber'],
        limit=1
    )

# Extract metadata
app_number = results['applications'][0]['applicationNumberText']
filing_date = results['applications'][0].get('filingDate')
examiner = results['applications'][0].get('examinerNameText')
art_unit = results['applications'][0].get('groupArtUnitNumber')

# Check Citations MCP eligibility
filing_year = int(filing_date[:4]) if filing_date else 0
citations_available = filing_year >= 2015  # Account for 1-2 year lag to first OA

print(f"**Application:** {{app_number}}")
print(f"**Filing Date:** {{filing_date}}")
print(f"**Examiner:** {{examiner}}")
print(f"**Art Unit:** {{art_unit}}")
print(f"**Citations Data:** {{'Available' if citations_available else 'Not Available (pre-2017 OA data)'}}")
```

---

## STEP 2: Citation Intelligence (Oct 1, 2017+ Only)

```python
if citations_available:
    # Get citation data from Citations MCP
    citations = await citations_search_citations_minimal(
        application_number=app_number,
        limit=50
    )

    # Analyze citation patterns
    cited_refs = [c for c in citations['citations']
                  if c.get('examinerCitedReferenceIndicator')]
    discarded_refs = [c for c in citations['citations']
                      if not c.get('examinerCitedReferenceIndicator')]

    print("### Citation Intelligence Summary")
    print(f"- **Total Citations:** {{citations['count']}}")
    print(f"- **Examiner-Cited:** {{len(cited_refs)}} (used in rejections)")
    print(f"- **Applicant-Disclosed:** {{len(discarded_refs)}} (not used by examiner)")

    # Categorize by type
    from collections import Counter
    categories = Counter([c.get('category', 'Unknown') for c in cited_refs])
    print("\\n**Citation Categories:**")
    for cat, count in categories.most_common():
        pct = (count / len(cited_refs)) * 100 if cited_refs else 0
        print(f"- {{cat}}: {{count}} ({{pct:.1f}}%)")
        # X = US patents, Y = Foreign patents, NPL = Non-patent literature
```

---

## STEP 3: Traditional PFW Prosecution Analysis

```python
# Get examiner citation documents (892)
examiner_cites = await pfw_get_application_documents(
    app_number=app_number,
    document_code='892',
    limit=1
)

# Get allowance reasoning (NOA)
noa = await pfw_get_application_documents(
    app_number=app_number,
    document_code='NOA',
    limit=1
)

# Extract and cross-reference with Citations MCP
if examiner_cites.get('documentBag'):
    cite_doc = examiner_cites['documentBag'][0]
    cite_content = await pfw_get_document_content(
        app_number=app_number,
        document_identifier=cite_doc['documentIdentifier'],
        max_pages=10
    )
    # Cross-reference 892 content with Citations MCP structured data
```

---

## STEP 4: Citation Pattern Analysis

```python
print("### Examiner Citation Behavior")
print()

# Examiner vs applicant citation effectiveness
if citations_available:
    examiner_rate = len(cited_refs) / citations['count'] * 100
    applicant_rate = len(discarded_refs) / citations['count'] * 100

    print(f"**Examiner Citation Rate:** {{examiner_rate:.1f}}% of total citations used")
    print(f"**Applicant Disclosure Value:** {{applicant_rate:.1f}}% disclosed but not cited")

    # Category preferences
    top_category = categories.most_common(1)[0] if categories else ('Unknown', 0)
    print(f"\\n**Preferred Citation Type:** {{top_category[0]}} ({{top_category[1]}} references)")

    # Art unit citation density
    art_unit_avg = 15  # Typical average, could query Citations MCP for art unit stats
    print(f"\\n**Citation Density:** {{len(cited_refs)}} examiner citations")
    if len(cited_refs) > art_unit_avg:
        print(f"  - Above average for Art Unit {{art_unit}} (dense prior art)")
    else:
        print(f"  - Below average (less crowded art)")
```

---

## STEP 5: Results & Recommendations

### Application Overview

| Metric | Value |
|--------|-------|
| Application Number | {{app_number}} |
| Filing Date | {{filing_date}} |
| Examiner | {{examiner}} |
| Art Unit | {{art_unit}} |
| Citations Data | {{'Available' if citations_available else 'Not Available'}} |
| Examiner Citations | {{len(cited_refs) if citations_available else 'N/A'}} |
| Citation Categories | {{', '.join([f'{{k}}={{v}}' for k, v in categories.most_common(3)])}} |

### Citation Patterns (2017+ Only)

**Examiner-Cited References** (high-value prior art):
```python
for ref in cited_refs[:10]:  # Top 10
    ref_num = ref.get('citationNumber', 'Unknown')
    category = ref.get('category', '?')
    print(f"- {{category}}: {{ref_num}}")
```

**Category Distribution:**
- **X (US Patents):** Most common, directly applicable
- **Y (Foreign):** International precedent, may have translation issues
- **NPL (Non-Patent Lit):** Technical publications, standards

### Strategic Insights

**For This Examiner/Art Unit:**
```python
if categories.get('X', 0) > categories.get('Y', 0):
    print("- **Strategy:** Focus on US prior art - examiner prefers domestic references")
elif categories.get('NPL', 0) > 5:
    print("- **Strategy:** Technical literature important - cite standards and publications")
else:
    print("- **Strategy:** Diversified citation approach")

# Effectiveness scoring
if citations_available:
    effectiveness = (len(cited_refs) / citations['count']) * 100
    if effectiveness > 70:
        print(f"- **Examiner Selectivity:** High ({{effectiveness:.0f}}%) - focuses on strongest references")
    elif effectiveness > 40:
        print(f"- **Examiner Selectivity:** Moderate ({{effectiveness:.0f}}%) - balanced approach")
    else:
        print(f"- **Examiner Selectivity:** Low ({{effectiveness:.0f}}%) - discards many applicant citations")
```

### Prior Art Search Recommendations

1. **Priority Citation Categories:**
   - Focus on {{top_category[0]}} references (examiner's preferred type)
   - Secondary: {{categories.most_common(2)[1][0] if len(categories) > 1 else 'Diversify'}}

2. **Search Strategy:**
   - Review examiner's cited references for search term patterns
   - Check classification codes from cited references
   - Explore continuations/family members of cited patents

3. **Technical Argument Development:**
   - Analyze why examiner chose certain references over applicant citations
   - Identify claim elements not addressed by prior art
   - Prepare technical distinctions for prosecution responses

---

## Notes

- **Citations MCP Limitation:** Only covers office actions dated Oct 1, 2017 or later
- **Pre-2017 Applications:** Use traditional 892 analysis only (no structured citation data)
- **Fallback Strategy:** For pre-2017 apps, extract 892 document and manually analyze citations
- **Cost:** 892 document extraction is FREE (PyPDF2), OCR fallback if needed (~$0.001-0.003/page)

**Related Workflows:**
- Examiner behavior analysis: `examiner_behavior_intelligence_CITATION`
- Complete prosecution package: `complete_patent_package_retrieval_PTAB_FPD`

---

**Deliverable:** Citation pattern analysis with examiner preferences, prior art effectiveness scoring, and strategic search recommendations."""



