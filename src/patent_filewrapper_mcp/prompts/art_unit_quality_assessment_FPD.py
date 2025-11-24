"""Art Unit Quality Assessment Fpd Prompt"""

from typing import Optional
from . import mcp

@mcp.prompt(
    name="art_unit_quality_assessment_FPD",
    description="Analyze art unit prosecution patterns and petition history for quality assessment. art_unit* (required). Optional: date_range_start, date_range_end (YYYY-MM-DD format). Requires PFW + FPD MCPs."
)
async def art_unit_quality_assessment_FPD_prompt(
    art_unit: str,
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None
) -> str:
    """Comprehensive art unit quality analysis using cross-MCP integration."""
    date_filter = ""
    if date_range_start or date_range_end:
        start = date_range_start or "2020-01-01"
        end = date_range_end or "2024-12-31"
        date_filter = f" filed between {start} and {end}"
    
    return f"""Analyze Art Unit {art_unit}{date_filter} for prosecution patterns and quality:

PHASE 1: PFW Analysis
```python
# Grant rate analysis
granted = await pfw_search_applications_minimal(
    art_unit='{art_unit}',
    status_code='150',
    fields=['applicationNumberText'],
    limit=100
)
all_apps = await pfw_search_applications_minimal(
    art_unit='{art_unit}',
    fields=['applicationNumberText', 'applicationMetaData.applicationStatusDescriptionText'],
    limit=100
)

# Examiner patterns - use fields parameter for efficiency
examiners = await pfw_search_applications_minimal(
    art_unit='{art_unit}',
    fields=['applicationNumberText', 'applicationMetaData.examinerNameText', 'groupArtUnitNumber'],
    limit=100
)
```

PHASE 2: FPD Analysis (Final Petition Decisions)
Search FPD MCP for petition history:
- Revival petitions (37 CFR 1.137) - abandonment issues
- Examiner disputes (37 CFR 1.181) - contentious prosecution
- Calculate petition-to-application ratio

PHASE 3: Assessment
Present quality indicators:
- Grant rate, Prosecution timeline patterns
- Petition frequency and types
- Risk assessment and recommendations

For complex workflows, use pfw_get_guidance (see quick reference chart for section selection)."""



