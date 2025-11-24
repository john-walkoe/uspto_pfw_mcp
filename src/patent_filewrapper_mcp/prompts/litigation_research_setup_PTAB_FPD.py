"""Litigation Research Setup Ptab Fpd Prompt"""

from . import mcp

@mcp.prompt(
    name="litigation_research_setup_PTAB_FPD",
    description="Comprehensive litigation research with prosecution history and cross-MCP intelligence. At least ONE identifier required (patent_number, application_number, or title_keywords). Retrieves critical docs (NOA, office actions, claims, citations) + PTAB proceedings + FPD petition history. Requires PFW + PTAB + FPD MCPs."
)
async def litigation_research_setup_PTAB_FPD_prompt(
    patent_number: str = "",
    application_number: str = "",
    title_keywords: str = ""
) -> str:
    """
    Enhanced litigation research with flexible identifier input.
    
    Identifier fields (at least ONE required):
    - patent_number: US patent number (e.g., "7971071", "7,971,071")
    - application_number: Application number (e.g., "11752072", "11/752,072")
    - title_keywords: Keywords from patent title (e.g., "digital rights management")
    
    The workflow will:
    1. Resolve the identifier to the correct application
    2. Retrieve complete litigation package (full tier with all documents)
    3. Provide organized document hierarchy for litigation analysis
    4. Generate strategic litigation insights with cross-MCP integration
    5. Include PTAB and FPD cross-references when available
    
    Returns comprehensive litigation-ready package with strategic recommendations.
    """
    return f"""️ Litigation Research Setup

Inputs:
- Patent Number: "{patent_number}"
- Application Number: "{application_number}"
- Title Keywords: "{title_keywords}"

PHASE 1: Identifier Resolution

```python
from .util.input_processing import process_identifier_inputs
processed_input = process_identifier_inputs(
    patent_number=patent_number,
    application_number=application_number,
    title_keywords=title_keywords
)

# Resolve to application number
if search_strategy == "direct_lookup":
    app_number, status = await resolve_identifier_to_application_number(
        identifier_info, pfw_search_applications_minimal
    )
elif search_strategy == "fuzzy_search":
    results = await pfw_search_applications_minimal(
        query=title_keywords,
        fields=["applicationNumberText", "inventionTitle", "patentNumber"],
        limit=10
    )
```

PHASE 2: Get Litigation Package

```python
# Get application metadata
app_details = await pfw_search_applications_balanced(
    query=f"applicationNumberText:{app_number}",
    limit=1
)

# Get critical prosecution documents using document_code filters
noa = await pfw_get_application_documents(app_number=app_number, document_code='NOA')
office_actions = await pfw_get_application_documents(app_number=app_number, document_code='CTFR', limit=10)
final_rejections = await pfw_get_application_documents(app_number=app_number, document_code='CTNF')
examiner_cites = await pfw_get_application_documents(app_number=app_number, document_code='892')
applicant_cites = await pfw_get_application_documents(app_number=app_number, document_code='1449')
claims = await pfw_get_application_documents(app_number=app_number, document_code='CLM')

# Get granted patent package
basic_package = await pfw_get_granted_patent_documents_download(app_number=app_number)
```

PHASE 3: Cross-MCP Integration

**PTAB Integration**: Search for post-grant challenges
```python
ptab_proceedings = await ptab_search_proceedings_balanced(patent_number=patent_number)
```

**FPD Integration**: Check petition history
```python
petition_history = await fpd_search_petitions(application_number=app_number)
```

PHASE 4: Content Extraction

```python
# Extract critical document text
noa_content = await pfw_get_document_content(
    app_number=app_number,
    document_identifier=noa_documents[0].document_identifier
)

final_oa_content = await pfw_get_document_content(
    app_number=app_number,
    document_identifier=final_rejection[0].document_identifier
)
```

PHASE 5: Present Litigation Package

Organize and present:
- Critical Documents: NOA, Final OA, Claims
- Prosecution History: All office actions, examiner citations
- Cross-MCP Analysis: PTAB proceedings, FPD petitions
- Strategic Insights: Strengths, vulnerabilities, recommendations

For complex workflows, use pfw_get_guidance (see quick reference chart for section selection)."""



