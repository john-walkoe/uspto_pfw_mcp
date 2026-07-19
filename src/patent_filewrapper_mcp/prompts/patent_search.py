"""Patent Search Prompt"""

from . import mcp

@mcp.prompt(
    name="patent_search",
    description="Fuzzy search to find patents using partial information (inventor names, technology keywords, company names, art unit, examiner, date ranges). search_description: free-text description of what you know. Requires PFW MCP."
)
async def patent_search_prompt(
    search_description: str = "Tell me what you know about the patent"
) -> str:
    """
    NEW TEMPLATE: Solves the "I know something about a patent" problem.

    Critical enhancement that addresses the gap where users don't have exact identifiers
    but know partial information like inventor names, technology keywords, or company names.
    """
    return f""" Patent Discovery by Partial Information

User Query: "{search_description}"

PHASE 1: Extract Search Criteria

Parse user description for:
- Inventor names, Company names, Technology keywords
- Art unit, Examiner name, Date ranges, Patent numbers

PHASE 2: Execute Search Strategy

**Person-Based Search** (inventor/company mentioned):
```python
# Example: "Patent by John Walkoe about digital rights management"
results = await pfw_search_inventor_minimal(
    name="John Walkoe",
    fields=["applicationNumberText", "inventionTitle", "patentNumber"],
    limit=50
)

# Example: "Apple patent from 2018 about facial recognition"
results = await pfw_search_applications_minimal(
    applicant_name="Apple Inc",
    filing_date_start="2018-01-01",
    filing_date_end="2018-12-31",
    query="facial recognition",
    fields=["applicationNumberText", "inventionTitle", "patentNumber"],
    limit=50
)
```

**Technology-Based Search** (keywords only):
```python
# For broad searches, use fields parameter for efficiency
results = await pfw_search_applications_minimal(
    query="wireless charging",
    status_code="150",
    fields=['applicationNumberText', 'inventionTitle', 'applicationMetaData.firstApplicantName'],
    limit=100
)
```

**Context-Based Search** (art unit/examiner):
```python
results = await pfw_search_applications_minimal(
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

For complex workflows, use pfw_get_guidance (see quick reference chart for section selection)."""
