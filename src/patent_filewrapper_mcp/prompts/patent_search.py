"""Patent Search Prompt"""

from . import mcp

@mcp.prompt(
    name="patent_search",
    description="Fuzzy search to find patents using partial information (inventor names, company names, title words, art unit, examiner, classification, date ranges). ODP search is bibliographic — it does not search abstracts, claims or specifications. search_description: free-text description of what you know. Requires PFW MCP."
)
async def patent_search_prompt(
    search_description: str = "Tell me what you know about the patent"
) -> str:
    """
    NEW TEMPLATE: Solves the "I know something about a patent" problem.

    Critical enhancement that addresses the gap where users don't have exact identifiers
    but know partial information like inventor names, company names, or title wording.
    """
    return f""" Patent Discovery by Partial Information

User Query: "{search_description}"

SEARCH SCOPE (state this before promising a subject-matter search)

The USPTO ODP index behind these tools is BIBLIOGRAPHIC: title, inventor and
applicant names, examiner, art unit, classification (CPC/USPC), status, and dates.
A free-text `query=` matches the title and other bibliographic strings ONLY. It does
NOT search abstracts, claims or specifications - there is no full-text lane here. A
keyword that appears only in the body of a patent will not be found by this server.

For subject matter, search by CLASSIFICATION and narrow with the bibliographic
filters; treat title keywords as a supplement, not the primary strategy.

PHASE 1: Extract Search Criteria

Parse user description for:
- Inventor names, Company names, words likely to appear in the TITLE
- Technology area -> map to a CPC class/subclass
- Art unit, Examiner name, Date ranges, Patent numbers

PHASE 2: Execute Search Strategy

**Person-Based Search** (inventor/company mentioned):
```python
# Example: "Patent by John Walkoe about digital rights management"
results = await PFW_search_inventor_minimal(
    name="John Walkoe",
    fields=["applicationNumberText", "inventionTitle", "patentNumber"],
    limit=50
)

# Example: "Apple patent from 2018 about facial recognition"
results = await PFW_search_applications_minimal(
    applicant_name="Apple Inc",
    filing_date_start="2018-01-01",
    filing_date_end="2018-12-31",
    query="facial recognition",
    fields=["applicationNumberText", "inventionTitle", "patentNumber"],
    limit=50
)
```

**Subject-Matter Search** (no inventor/company - use classification, NOT keywords):
```python
# CPC is the effective subject-matter handle. Subclass prefix wildcard:
results = await PFW_search_applications_minimal(
    query="applicationMetaData.cpcClassificationBag:H04L*",
    status_code="150",
    filing_date_start="2018-01-01",
    fields=['applicationNumberText', 'inventionTitle', 'applicationMetaData.firstApplicantName'],
    limit=100
)

# A full CPC group symbol must reproduce the API's internal space padding:
#   query='applicationMetaData.cpcClassificationBag:"C08G  77/06"'
```

**Title keywords** (supplement only, never the whole strategy):
```python
# Matches the TITLE and bibliographic strings - NOT abstracts, claims or specs.
# Expect loose matches, and expect to miss patents whose title uses other wording.
results = await PFW_search_applications_minimal(
    query="wireless charging",
    status_code="150",
    fields=['applicationNumberText', 'inventionTitle', 'applicationMetaData.firstApplicantName'],
    limit=100
)
```

**Context-Based Search** (art unit/examiner):
```python
results = await PFW_search_applications_minimal(
    art_unit="2128",
    examiner_name="LANIER",
    grant_date_start="2010-01-01",
    grant_date_end="2011-12-31",
    limit=50
)
```

PHASE 3: Present Results

Rank results by relevance and present top matches with:
- Patent number, Application number, Title
- Inventors, Applicant, Filing/Grant dates
- Art unit, Examiner
- Match confidence score

PHASE 4: Next Steps

Offer workflow handoffs:
- /complete_patent_package for full document package
- /inventor_portfolio_analysis for inventor research
- /document_filtering_assistant for targeted document analysis

For complex workflows, use PFW_get_guidance (see quick reference chart for section selection)."""
