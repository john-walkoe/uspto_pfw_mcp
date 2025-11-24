"""Examiner Behavior Intelligence Citation Prompt"""

from . import mcp

@mcp.prompt(
    name="examiner_behavior_intelligence_CITATION",
    description="Analyze examiner citation patterns, prosecution strategies, and allowance reasoning for targeted prosecution approach. At least ONE parameter required (examiner_name, art_unit, or technology_keywords). Citations data available Oct 1, 2017+ only. Requires PFW + Citations MCPs."
)
async def examiner_behavior_intelligence_CITATION_prompt(
    examiner_name: str = "",
    art_unit: str = "",
    technology_keywords: str = ""
) -> str:
    """
    Examiner-specific citation behavior and prosecution strategy analysis.

    Parameters (at least ONE required): examiner_name, art_unit, or technology_keywords
    IMPORTANT: Citations data available for office actions from Oct 1, 2017+ only
    """

    return f"""# Examiner Behavior Intelligence (Citation-Enhanced)

**Inputs:** Examiner "{examiner_name}", Art Unit "{art_unit}", Technology "{technology_keywords}"
**Data Availability:** Citations MCP covers Oct 1, 2017+ office actions

---

## STEP 1: Examiner Discovery (PFW Portfolio Search)

### Wildcard Examiner Search

```python
# Extract last name for wildcard search
if examiner_name:
    last_name = examiner_name.split(',')[0].strip() if ',' in examiner_name else examiner_name.strip()

    # Build targeted query
    if art_unit:
        art_unit_prefix = art_unit[:3]  # "1759" → "175" prefix
        query = f'examinerNameText:{{last_name}}* AND groupArtUnitNumber:{{art_unit_prefix}}*'
    else:
        query = f'examinerNameText:{{last_name}}*'

    # Get examiner's application portfolio
    results = await pfw_search_applications_minimal(
        query=query,
        filing_date_start='2015-01-01',  # 2015+ accounts for 2017+ first OA data
        fields=['applicationNumberText', 'examinerNameText', 'groupArtUnitNumber',
                'filingDate', 'patentNumber', 'inventionTitle'],
        limit=50
    )

# Analyze art unit distribution
from collections import Counter
art_units = Counter([app.get('groupArtUnitNumber') for app in results['applications']])
primary_art_unit = art_units.most_common(1)[0]

print(f"**Examiner:** {{last_name}}")
print(f"**Applications Found:** {{results['count']}}")
print(f"**Primary Art Unit:** {{primary_art_unit[0]}} ({{primary_art_unit[1]}} apps)")
print(f"**Art Units Covered:** {{len(art_units)}}")
```

---

## STEP 2: Citation Pattern Analysis (20-30 Apps Sample)

```python
# Sample applications for citation analysis
sample_apps = results['applications'][:20]

# Aggregate citation data from Citations MCP
all_citations = []
examiner_cited_count = 0
applicant_cited_count = 0

for app in sample_apps:
    app_number = app.get('applicationNumberText')

    try:
        citations = await citations_search_citations_minimal(
            application_number=app_number,
            limit=50
        )

        if citations.get('count', 0) > 0:
            all_citations.extend(citations['citations'])

            # Count examiner vs applicant citations
            for cite in citations['citations']:
                if cite.get('examinerCitedReferenceIndicator'):
                    examiner_cited_count += 1
                else:
                    applicant_cited_count += 1
    except:
        pass  # Citations not available (pre-2017 OA or no data)

# Calculate examiner citation behavior
total_cites = examiner_cited_count + applicant_cited_count
if total_cites > 0:
    examiner_rate = (examiner_cited_count / total_cites) * 100
    print("### Citation Behavior")
    print(f"- **Examiner Citation Rate:** {{examiner_rate:.1f}}%")
    print(f"- **Total Citations Analyzed:** {{total_cites}}")

    # Category preferences
    categories = Counter([c.get('category', 'Unknown')
                         for c in all_citations
                         if c.get('examinerCitedReferenceIndicator')])

    print("\\n**Examiner Citation Preferences:**")
    for cat, count in categories.most_common():
        pct = (count / examiner_cited_count) * 100
        print(f"- {{cat}}: {{count}} ({{pct:.1f}}%)")
```

---

## STEP 3: Allowance Reasoning Analysis (NOA Deep Dive)

```python
# Find granted patents for NOA analysis
granted_apps = await pfw_search_applications_minimal(
    query=f'examinerNameText:{{last_name}}* AND status_code:150',
    filing_date_start='2015-01-01',
    fields=['applicationNumberText', 'inventionTitle', 'patentNumber', 'filingDate'],
    limit=30
)

# Select representative patents (recent, with citation data)
representative_patents = granted_apps['applications'][:3]  # Top 3

print("### Allowance Analysis (Sample NOAs)")
print()

for patent in representative_patents:
    app_number = patent.get('applicationNumberText')
    title = patent.get('applicationMetaData', {{}}).get('inventionTitle', 'Unknown')

    # Get NOA document
    noa_docs = await pfw_get_application_documents(
        app_number=app_number,
        document_code='NOA',
        limit=1
    )

    if noa_docs.get('documentBag'):
        noa_doc = noa_docs['documentBag'][0]

        # Extract NOA content
        noa_content = await pfw_get_document_content(
            app_number=app_number,
            document_identifier=noa_doc['documentIdentifier'],
            max_pages=10
        )

        print(f"**Patent:** {{patent.get('applicationMetaData', {{}}).get('patentNumber')}}")
        print(f"**Title:** {{title}}")
        print(f"**NOA Analysis:** {{len(noa_content['text'])}} characters extracted")
        # Analyze for:
        # - Technical distinction patterns
        # - Specification reliance
        # - Claim interpretation style
        print()
```

---

## STEP 4: Prosecution Pattern Integration

```python
print("### Prosecution Patterns")
print()

# Calculate prosecution efficiency metrics
rce_count = 0
amendment_count = 0

for app in sample_apps:
    app_number = app.get('applicationNumberText')

    # Check for RCE filings
    rce_docs = await pfw_get_application_documents(
        app_number=app_number,
        document_code='RCEX',
        limit=5
    )
    if rce_docs.get('documentBag'):
        rce_count += len(rce_docs['documentBag'])

    # Check for amendments
    amend_docs = await pfw_get_application_documents(
        app_number=app_number,
        document_code='A...',  # All amendment types
        limit=10
    )
    if amend_docs.get('documentBag'):
        amendment_count += len(amend_docs['documentBag'])

# Calculate averages
avg_rce = rce_count / len(sample_apps)
avg_amendments = amendment_count / len(sample_apps)

print(f"**Average RCE per Application:** {{avg_rce:.1f}}")
print(f"**Average Amendments:** {{avg_amendments:.1f}}")

if avg_rce > 0.5:
    print("- **Prosecution Difficulty:** High - frequent RCE filings")
elif avg_rce > 0.2:
    print("- **Prosecution Difficulty:** Moderate")
else:
    print("- **Prosecution Difficulty:** Low - most applications allow without RCE")
```

---

## STEP 5: Strategic Intelligence Report

### Examiner Profile Summary

| Metric | Value |
|--------|-------|
| Examiner | {{last_name}} |
| Primary Art Unit | {{primary_art_unit[0]}} |
| Applications Analyzed | {{len(sample_apps)}} |
| Analysis Period | 2015+ (Citations: 2017+) |
| Examiner Citation Rate | {{examiner_rate:.1f}}% |
| Average RCE Rate | {{avg_rce:.1f}} per app |
| Citation Preference | {{categories.most_common(1)[0][0] if categories else 'Unknown'}} |

### Citation Intelligence

**Examiner Citation Behavior:**
- **Selectivity:** {{examiner_rate:.0f}}% of total citations used in rejections
- **Preferred Citation Type:** {{categories.most_common(1)[0][0]}} ({{categories.most_common(1)[0][1]}} references)
- **Citation Density:** {{examiner_cited_count / len(sample_apps):.1f}} examiner citations per application

**Strategic Implications:**
```python
if examiner_rate > 70:
    print("- **High Selectivity:** Examiner focuses on strongest prior art only")
    print("- **Strategy:** Comprehensive IDS filing may not help - focus on technical distinctions")
elif examiner_rate > 40:
    print("- **Moderate Selectivity:** Balanced approach to applicant-cited references")
    print("- **Strategy:** Strategic IDS filing of key references recommended")
else:
    print("- **Low Selectivity:** Examiner often finds own prior art")
    print("- **Strategy:** Emphasize technical distinctions over IDS breadth")
```

### Prosecution Strategy Recommendations

**Citation-Informed Prior Art Strategy:**
1. **Focus on {{categories.most_common(1)[0][0]}} references** (examiner's preferred type)
2. **Citation Density:** {{examiner_cited_count / len(sample_apps):.0f}} citations/app - prepare for {{'heavy' if examiner_cited_count / len(sample_apps) > 15 else 'moderate'}} prior art

**Claim Drafting Guidance:**
- Review NOA patterns for preferred claim language and structure
- Analyze allowance reasoning for specification reliance patterns
- Note technical distinction strategies that succeeded

**Prosecution Timeline:**
- **RCE Likelihood:** {{(avg_rce * 100):.0f}}% of applications
- **Amendment Strategy:** {{avg_amendments:.1f}} amendments average - plan for iterative prosecution

**Success Factors:**
- Technical arguments that convinced this examiner (from NOA analysis)
- Specification detail requirements for claim support
- Office action response timing and strategy patterns

---

## Notes

- **Citations MCP Limitation:** Only covers OAs from Oct 1, 2017 onward
- **Sample Size:** Analysis based on {{len(sample_apps)}} applications (increase for statistical significance)
- **Art Unit Context:** Results specific to Art Unit {{primary_art_unit[0]}} - may vary in other units
- **Technology Focus:** {{'Filtered by: ' + technology_keywords if technology_keywords else 'All technologies'}}

**Related Workflows:**
- Prior art analysis: `prior_art_analysis_CITATION`
- Art unit quality: `art_unit_quality_assessment_FPD`

---

**Deliverable:** Examiner-specific citation behavior profile, prosecution pattern analysis, and targeted prosecution strategy recommendations."""


# Global proxy server state
_proxy_server_running = False
_proxy_server_task = None

async def _ensure_proxy_server_running(port: int = 8080):
    """Ensure the proxy server is running"""
    global _proxy_server_running, _proxy_server_task
    
    if not _proxy_server_running:
        logger.info(f"Starting HTTP proxy server on port {port}")
        _proxy_server_task = asyncio.create_task(_run_proxy_server(port))
        _proxy_server_running = True
        # Give the server a moment to start
        await asyncio.sleep(0.5)

async def _run_proxy_server(port: int = 8080):
    """Run the FastAPI proxy server"""
    try:
        import uvicorn
        from .proxy.server import create_proxy_app
        
        app = create_proxy_app()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False  # Reduce noise in logs
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTP proxy server starting on http://127.0.0.1:{port}")
        await server.serve()
        
    except Exception as e:
        global _proxy_server_running
        _proxy_server_running = False
        logger.error(f"Proxy server failed: {e}")
        raise
