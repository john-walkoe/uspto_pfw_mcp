"""Technology Landscape Mapping Ptab Prompt"""

from typing import Optional
from . import mcp

@mcp.prompt(
    name="technology_landscape_mapping_PTAB",
    description="Map competitive technology landscape with market intelligence and risk assessment. technology_keywords* (required). Optional: art_units (comma-separated). Analysis includes: market leaders, filing trends, technology evolution, new entrants, PTAB challenges, FPD prosecution quality. Requires PFW + PTAB + FPD MCPs."
)
async def technology_landscape_mapping_PTAB_prompt(
    technology_keywords: str,
    art_units: Optional[str] = None
) -> str:
    """Comprehensive technology landscape analysis with competitive intelligence and cross-MCP risk assessment."""
    art_unit_filter = f" in art units {art_units}" if art_units else " across all art units"

    return f"""# Technology Landscape Mapping: {technology_keywords}

**Scope:** {art_unit_filter}
**Objective:** Competitive intelligence, market share analysis, filing trends, and PTAB risk assessment

---

## PHASE 1: Technology Discovery

### Step 1: Broad Technology Search with Efficient Fields

```python
# Use minimal search for discovery with strategic fields
results = await pfw_search_applications_minimal(
    query='{technology_keywords}',
    status_code='150',  # Granted patents only
    {f"art_unit='{art_units}'," if art_units else ""}
    filing_date_start='2019-01-01',  # Last 5-6 years
    fields=['applicationNumberText', 'firstApplicantName', 'inventionTitle',
            'patentNumber', 'filingDate', 'groupArtUnitNumber'],
    limit=100
)

total_count = results['count']
applications = results['applications']

print(f"Found {{total_count}} granted patents for: {technology_keywords}")
print(f"Analyzing top {{len(applications)}} patents{art_unit_filter}")
```

**Strategy Notes:**
- `status_code='150'` focuses on granted patents (competitive landscape)
- Filing date filter captures recent innovation (last 5-6 years)
- Ultra-minimal fields for 99% token reduction
- Increase limit for comprehensive landscape (200-500 patents)

### Step 2: Present Top Patents Overview

```python
# Display sample patents for context
print("### Representative Patents")
for app in applications[:20]:
    title = app.get('applicationMetaData', {{}}).get('inventionTitle', 'N/A')
    patent_num = app.get('applicationMetaData', {{}}).get('patentNumber', 'N/A')
    company = app.get('applicationMetaData', {{}}).get('firstApplicantName', 'N/A')
    print(f"- Patent {{patent_num}}: {{title}}")
    print(f"  Assignee: {{company}}")
```

---

## PHASE 2: Competitive Analysis

### Step 3: Key Player Identification & Market Share

```python
from collections import Counter

# Extract company names
companies = [app.get('applicationMetaData', {{}}).get('firstApplicantName', 'Unknown')
             for app in applications]
company_counts = Counter(companies)

# Calculate market share
print("### Market Leaders (Top 10)")
print()
for rank, (company, count) in enumerate(company_counts.most_common(10), 1):
    market_share = (count / total_count) * 100
    print(f"{{rank}}. **{{company}}**: {{count}} patents ({{market_share:.1f}}% market share)")

# Identify market structure
top_5_share = sum([count for _, count in company_counts.most_common(5)]) / total_count * 100
if top_5_share > 60:
    print(f"\\n**Market Structure:** Concentrated (Top 5 = {{top_5_share:.0f}}%)")
elif top_5_share > 40:
    print(f"\\n**Market Structure:** Moderately Competitive (Top 5 = {{top_5_share:.0f}}%)")
else:
    print(f"\\n**Market Structure:** Highly Fragmented (Top 5 = {{top_5_share:.0f}}%)")
```

### Step 4: Timeline & Technology Evolution Analysis

```python
# Group by filing year
from collections import defaultdict
import datetime

by_year = defaultdict(list)
for app in applications:
    filing_date = app.get('filingDate', '')
    if filing_date:
        year = filing_date[:4]
        by_year[year].append(app)

# Show filing trends
print("### Filing Trends (Patents per Year)")
for year in sorted(by_year.keys()):
    count = len(by_year[year])
    print(f"- **{{year}}**: {{count}} patents")

# Identify growth trend
recent_years = [len(by_year[y]) for y in sorted(by_year.keys())[-3:]]
if len(recent_years) >= 2 and recent_years[-1] > recent_years[0] * 1.2:
    print("\\n**Trend:** Growing technology area (20%+ increase)")
elif len(recent_years) >= 2 and recent_years[-1] < recent_years[0] * 0.8:
    print("\\n**Trend:** Declining interest (20%+ decrease)")
else:
    print("\\n**Trend:** Stable filing rate")
```

### Step 5: Art Unit Distribution Analysis

```python
# Analyze art unit distribution
art_units_data = [app.get('groupArtUnitNumber', 'Unknown')
                  for app in applications]
art_unit_counts = Counter(art_units_data)

print("### Art Unit Distribution (Top 5)")
for art_unit, count in art_unit_counts.most_common(5):
    pct = (count / total_count) * 100
    print(f"- Art Unit {{art_unit}}: {{count}} patents ({{pct:.1f}}%)")

# Technology specialization
top_art_unit_pct = (art_unit_counts.most_common(1)[0][1] / total_count) * 100
if top_art_unit_pct > 50:
    print(f"\\n**Technology Focus:** Highly specialized ({{top_art_unit_pct:.0f}}% in one art unit)")
else:
    print(f"\\n**Technology Focus:** Diversified across {{len(art_unit_counts)}} art units")
```

---

## PHASE 3: Strategic Intelligence & Cross-MCP Integration

### Step 6: Technology Evolution - Early vs Recent Innovation

```python
# Compare early vs recent patents
early_patents = [app for y in ['2019', '2020', '2021']
                for app in by_year.get(y, [])]
recent_patents = [app for y in ['2022', '2023', '2024']
                 for app in by_year.get(y, [])]

print("### Technology Evolution Analysis")
print(f"- **Early Period (2019-2021):** {{len(early_patents)}} patents")
print(f"- **Recent Period (2022-2024):** {{len(recent_patents)}} patents")

# Identify emerging players
early_companies = Counter([app.get('applicationMetaData', {{}}).get('firstApplicantName')
                          for app in early_patents])
recent_companies = Counter([app.get('applicationMetaData', {{}}).get('firstApplicantName')
                           for app in recent_patents])

# Find new entrants
new_entrants = set(recent_companies.keys()) - set(early_companies.keys())
if new_entrants:
    print(f"\\n**New Entrants:** {{len(new_entrants)}} companies filed in recent period only")
    for company in list(new_entrants)[:5]:
        print(f"  - {{company}}")
```

### Step 7: PTAB Risk Assessment (Top Companies)

```python
# Check top 5 companies for PTAB challenges
print("### PTAB Challenge Assessment")
print()

top_companies = company_counts.most_common(5)
for company, patent_count in top_companies:
    company_patents = [app for app in applications
                      if app.get('applicationMetaData', {{}}).get('firstApplicantName') == company]

    ptab_count = 0
    for app in company_patents:
        patent_num = app.get('applicationMetaData', {{}}).get('patentNumber')
        if patent_num:
            try:
                ptab_results = await ptab_search_proceedings_minimal(  # Wrapper for search_trials_minimal
                    patent_number=patent_num,
                    limit=5
                )
                if ptab_results.get('count', 0) > 0:
                    ptab_count += ptab_results['count']
            except:
                pass

    if ptab_count > 0:
        challenge_rate = (ptab_count / patent_count) * 100
        print(f"- **{{company}}**: {{ptab_count}} PTAB challenges on {{patent_count}} patents ({{challenge_rate:.0f}}% challenge rate)")
    else:
        print(f"- **{{company}}**: No PTAB challenges found")

# Historical technology context (pre-AIA, rare but valuable for older tech)
interferences = await search_interferences_minimal(
    patent_number=patent_num,
    limit=5
)
```

### Step 8: FPD Prosecution Difficulty Analysis

```python
# Sample patents from top companies for prosecution quality
print("### Prosecution Quality Indicators (FPD)")
print()

sample_apps = applications[:20]  # Sample first 20 for efficiency
petition_count = 0

for app in sample_apps:
    app_number = app.get('applicationNumberText')
    if app_number:
        try:
            petitions = await fpd_search_petitions_by_application(
                application_number=app_number
            )
            if petitions.get('count', 0) > 0:
                petition_count += petitions['count']
        except:
            pass

if petition_count > 0:
    petition_rate = (petition_count / len(sample_apps)) * 100
    print(f"**Petition Rate:** {{petition_count}} petitions in {{len(sample_apps)}} sampled applications ({{petition_rate:.0f}}%)")
    print("_Indicates prosecution difficulties in this technology area_")
else:
    print("**Prosecution Quality:** Clean - no petitions found in sample")
```

---

## PHASE 4: Competitive Intelligence Report

### Step 9: Strategic Recommendations

```python
print("### Strategic Landscape Insights")
print()

# Market leader analysis
leader = company_counts.most_common(1)[0]
leader_share = (leader[1] / total_count) * 100

print(f"**Market Leader:** {{leader[0]}} with {{leader_share:.1f}}% market share")

# Filing strategy recommendations
if len(recent_patents) > len(early_patents):
    print("**Market Trend:** Growing - Consider defensive filing strategy")
elif len(recent_patents) < len(early_patents) * 0.7:
    print("**Market Trend:** Declining - Technology may be maturing")
else:
    print("**Market Trend:** Stable - Established technology area")

# White space opportunities
if len(art_unit_counts) > 3:
    print(f"**Technology Diversification:** {{len(art_unit_counts)}} art units - Multiple innovation vectors")
    print("**Opportunity:** Identify underserved art units for targeted filing")
else:
    print("**Technology Focus:** Concentrated in {{len(art_unit_counts)}} art units")
    print("**Opportunity:** Explore adjacent technologies in related art units")

# Risk assessment summary
if ptab_count > 0:
    print(f"**PTAB Risk:** Moderate - {{ptab_count}} total challenges observed")
    print("**Recommendation:** Review claim scope and prosecution strategies of challenged patents")
else:
    print("**PTAB Risk:** Low - No challenges observed in landscape")
```

---

## Presentation Format

**Executive Summary Table:**

| Metric | Value |
|--------|-------|
| Total Patents Analyzed | {{total_count}} |
| Time Period | 2019-Present |
| Market Leaders (Top 3) | {{', '.join([c[0] for c in company_counts.most_common(3)])}} |
| Top Leader Market Share | {{leader_share:.1f}}% |
| Filing Trend | Growing / Stable / Declining |
| PTAB Challenges | {{ptab_count}} total |
| Primary Art Units | {{', '.join([str(au[0]) for au in art_unit_counts.most_common(3)])}} |

**Visualizations:**
1. **Market Share Pie Chart** (Top 10 companies + "Others")
2. **Filing Timeline** (Patents per year, 2019-2024)
3. **Art Unit Distribution** (Bar chart)
4. **Competitive Matrix** (Market share vs filing velocity)

**Key Findings:**
- Market structure (concentrated vs fragmented)
- Technology evolution (early vs recent focus areas)
- New entrants and emerging threats
- PTAB challenge exposure by company
- White space opportunities

---

## Notes

- Focus on granted patents (`status_code='150'`) for competitive landscape
- Extend date range for historical analysis (e.g., 2015-present)
- Increase limit for comprehensive mapping (200-500 patents)
- PTAB and FPD checks require those MCPs to be available
- For very large technology areas, narrow with art_units parameter

**Related Workflows:**
- Inventor analysis: `inventor_portfolio_analysis`
- Art unit assessment: `art_unit_quality_assessment_FPD`
- Prior art analysis: `prior_art_analysis_CITATION`

---

**Deliverable:** Competitive landscape report with market share analysis, filing trends, technology evolution insights, PTAB risk assessment, and strategic filing recommendations."""
