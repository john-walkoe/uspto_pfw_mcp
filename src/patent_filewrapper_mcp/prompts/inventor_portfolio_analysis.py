"""Inventor Portfolio Analysis Prompt"""

from . import mcp

@mcp.prompt(
    name="inventor_portfolio_analysis",
    description="Comprehensive inventor portfolio analysis with technology mapping and prosecution patterns. inventor_name* (required). analysis_scope: basic/comprehensive (default: basic). Basic: patent counts, tech areas, activity. Comprehensive: + art units, examiner patterns, PTAB/FPD risk. Requires PFW + PTAB + FPD MCPs."
)
async def inventor_portfolio_analysis_prompt(
    inventor_name: str,
    analysis_scope: str = "basic"
) -> str:
    """Analyze inventor's complete patent portfolio with strategic insights and cross-MCP intelligence."""
    scope_instructions = {
        "basic": "Focus on patent counts, technology areas, and recent activity",
        "comprehensive": "Include art unit distribution, examiner patterns, prosecution analysis, and PTAB/FPD vulnerability assessment"
    }

    instructions = scope_instructions.get(analysis_scope, scope_instructions["basic"])

    return f"""# Inventor Portfolio Analysis: {inventor_name}

**Analysis Scope:** {analysis_scope}
**Objective:** {instructions}

---

## PHASE 1: Portfolio Discovery

### Step 1: Inventor Search with Efficient Field Selection

```python
# Use balanced search for portfolio discovery
results = await pfw_search_inventor_balanced(
    name='{inventor_name}',
    strategy='comprehensive',  # Matches surname, forename, and variations
    limit=50
)

# Display basic portfolio metrics
total_count = results['count']
applications = results['applications']

print(f"Found {{total_count}} applications for inventor: {inventor_name}")
```

**Strategy Notes:**
- `strategy='comprehensive'` searches surname + forename variations
- Returns 18+ fields including art units, examiners, classifications
- Limit 50 for portfolio overview (increase if prolific inventor)

### Step 2: Portfolio Overview Statistics

```python
# Calculate portfolio metrics
granted = [app for app in applications
           if app.get('applicationMetaData', {{}}).get('patentNumber')]
pending = [app for app in applications if app not in granted]

# Date range analysis
filing_dates = [app.get('filingDate') for app in applications if app.get('filingDate')]
career_span = f"{{min(filing_dates)[:4]}} - {{max(filing_dates)[:4]}}"

print(f"**Total Applications:** {{total_count}}")
print(f"**Granted Patents:** {{len(granted)}} ({{len(granted)/total_count*100:.1f}}%)")
print(f"**Pending Applications:** {{len(pending)}} ({{len(pending)/total_count*100:.1f}}%)")
print(f"**Career Span:** {{career_span}}")
```

---

## PHASE 2: Technology Analysis

### Step 3: Innovation Mapping by Art Units

```python
# Group by art unit (technology area)
from collections import Counter

art_units = [app.get('groupArtUnitNumber') for app in applications
             if app.get('groupArtUnitNumber')]
art_unit_dist = Counter(art_units)

print("### Technology Focus (Top 5 Art Units)")
for art_unit, count in art_unit_dist.most_common(5):
    pct = count/total_count*100
    print(f"- Art Unit {{art_unit}}: {{count}} applications ({{pct:.1f}}%)")
```

### Step 4: Technology Evolution Timeline

```python
# Track technology focus over time
# Group applications by filing year and art unit
import datetime

by_year_tech = {{}}
for app in applications:
    filing_date = app.get('filingDate', '')
    if filing_date:
        year = filing_date[:4]
        art_unit = app.get('groupArtUnitNumber', 'Unknown')
        if year not in by_year_tech:
            by_year_tech[year] = []
        by_year_tech[year].append(art_unit)

# Present evolution
print("### Technology Evolution")
for year in sorted(by_year_tech.keys()):
    top_tech = Counter(by_year_tech[year]).most_common(1)[0]
    print(f"- **{{year}}**: Primary focus Art Unit {{top_tech[0]}} ({{top_tech[1]}} apps)")
```

---

{"## PHASE 3: Advanced Analysis (Comprehensive Mode)" if analysis_scope == "comprehensive" else "## PHASE 3: Basic Insights"}

{'''### Step 5: Prosecution Quality Assessment

```python
# Analyze examiner distribution
examiners = [app.get('examinerNameText') for app in applications
             if app.get('examinerNameText')]
examiner_dist = Counter(examiners)

print("### Examiner Relationships (Top 5)")
for examiner, count in examiner_dist.most_common(5):
    pct = count/total_count*100
    print(f"- {{examiner}}: {{count}} applications ({{pct:.1f}}%)")

# Prosecution timeline analysis
prosecution_times = []
for app in granted:
    filing_date = app.get('filingDate')
    issue_date = app.get('applicationMetaData', {{}}).get('patentIssueDate')
    if filing_date and issue_date:
        days = (datetime.datetime.strptime(issue_date[:10], '%Y-%m-%d') -
                datetime.datetime.strptime(filing_date[:10], '%Y-%m-%d')).days
        prosecution_times.append(days/365)  # Convert to years

if prosecution_times:
    avg_time = sum(prosecution_times) / len(prosecution_times)
    print(f"**Average Time to Grant:** {{avg_time:.1f}} years")
```

### Step 6: Cross-MCP Vulnerability Assessment

**PTAB Challenge Analysis:**
```python
# Check granted patents for PTAB challenges
ptab_challenges = []
for patent in granted:
    patent_num = patent.get('applicationMetaData', {{}}).get('patentNumber')
    if patent_num:
        try:
            ptab_results = await ptab_search_proceedings_minimal(
                patent_number=patent_num,
                limit=5
            )
            if ptab_results.get('count', 0) > 0:
                ptab_challenges.append({{
                    'patent': patent_num,
                    'challenges': ptab_results['count']
                }})
        except:
            pass

if ptab_challenges:
    print("### PTAB CHALLENGE ALERT")
    print(f"**Challenged Patents:** {{len(ptab_challenges)}} of {{len(granted)}} granted")
    for item in ptab_challenges:
        print(f"- Patent {{item['patent']}}: {{item['challenges']}} PTAB proceeding(s)")
else:
    print("### PTAB Status: No challenges found")
```

**FPD Petition History:**
```python
# Check for petition issues in prosecution
petition_issues = []
for app in applications:
    app_number = app.get('applicationNumberText')
    if app_number:
        try:
            petitions = await fpd_search_petitions_by_application(
                application_number=app_number
            )
            if petitions.get('count', 0) > 0:
                petition_issues.append({{
                    'app': app_number,
                    'petitions': petitions['count']
                }})
        except:
            pass

if petition_issues:
    print("### FPD PETITION WARNING")
    print(f"**Applications with Petitions:** {{len(petition_issues)}} of {{total_count}}")
    print("_Indicates prosecution difficulties or procedural issues_")
else:
    print("### FPD Status: Clean prosecution history")
```
''' if analysis_scope == "comprehensive" else ""}

---

## FINAL PHASE: Strategic Portfolio Assessment

### {"Step 7" if analysis_scope == "comprehensive" else "Step 5"}: Key Innovation Areas

```python
# Identify strongest technology areas
print("### Portfolio Strengths")
print()

# Technology concentration
top_art_unit = art_unit_dist.most_common(1)[0]
specialization = (top_art_unit[1] / total_count) * 100

if specialization > 50:
    print(f"**Specialist Inventor:** {{specialization:.0f}}% of portfolio in Art Unit {{top_art_unit[0]}}")
else:
    print(f"**Diversified Inventor:** Portfolio spans {{len(art_unit_dist)}} different art units")

# Recent activity
recent_apps = [app for app in applications
               if app.get('filingDate', '') >= str(datetime.datetime.now().year - 3)]
if recent_apps:
    print(f"**Recent Activity:** {{len(recent_apps)}} applications in last 3 years")
else:
    print("**Recent Activity:** No applications in last 3 years")
```

### {"Step 8" if analysis_scope == "comprehensive" else "Step 6"}: Portfolio Recommendations

```python
print("### Strategic Recommendations")
print()

# Filing frequency
years_active = len(set([app.get('filingDate', '')[:4] for app in applications]))
apps_per_year = total_count / years_active if years_active > 0 else 0

if apps_per_year > 5:
    print("- **Prolific Inventor:** High innovation output ({{apps_per_year:.1f}} apps/year)")
    print("- Consider portfolio pruning and strategic focus")
elif apps_per_year > 2:
    print("- **Active Inventor:** Consistent innovation output ({{apps_per_year:.1f}} apps/year)")
    print("- Maintain current filing pace in core technology areas")
else:
    print("- **Selective Inventor:** Focused innovation approach ({{apps_per_year:.1f}} apps/year)")
    print("- Each application likely represents significant innovation")

# Grant rate analysis
if granted:
    grant_rate = len(granted) / total_count * 100
    if grant_rate > 70:
        print(f"- **High Grant Rate:** {{grant_rate:.1f}}% - Strong prosecution capability")
    elif grant_rate > 50:
        print(f"- **Moderate Grant Rate:** {{grant_rate:.1f}}% - Review abandoned applications for improvement")
    else:
        print(f"- **Low Grant Rate:** {{grant_rate:.1f}}% - Consider prosecution strategy review")

{'''# Risk assessment (comprehensive mode only)
if ptab_challenges:
    risk_pct = len(ptab_challenges) / len(granted) * 100
    print(f"- **PTAB Risk:** {{risk_pct:.1f}}% of granted patents challenged - Review claim scope")

if petition_issues:
    issue_pct = len(petition_issues) / total_count * 100
    print(f"- **Prosecution Issues:** {{issue_pct:.1f}}% of applications had petitions - Training opportunity")
''' if analysis_scope == "comprehensive" else ""}
```

---

## Presentation Format

**Portfolio Summary Table:**

| Metric | Value |
|--------|-------|
| Total Applications | {{total_count}} |
| Granted Patents | {{len(granted)}} ({{len(granted)/total_count*100:.1f}}%) |
| Career Span | {{career_span}} |
| Primary Technology | Art Unit {{top_art_unit[0]}} ({{specialization:.0f}}% of portfolio) |
| {"PTAB Challenges | {len(ptab_challenges)}" if analysis_scope == "comprehensive" else "Filing Rate | {apps_per_year:.1f} apps/year"} |

**Representative Patents** (sample 3-5 granted patents with titles and numbers)

**Technology Diversification Chart** (art unit distribution)

**Filing Timeline** (applications per year over career span)

{"**Risk Assessment** (PTAB challenges and FPD petition history)" if analysis_scope == "comprehensive" else ""}

---

## Notes

- Use `analysis_scope='basic'` for quick portfolio overview
- Use `analysis_scope='comprehensive'` for due diligence, litigation prep, or M&A research
- PTAB and FPD checks require those MCPs to be available
- For very prolific inventors (200+ applications), increase limit and use pagination

For related workflows:
- Technology landscape analysis: `technology_landscape_mapping_PTAB`
- Art unit quality assessment: `art_unit_quality_assessment_FPD`
- Patent package retrieval: `complete_patent_package_retrieval_PTAB_FPD`

---

**Analysis complete. Present results with specific patent examples and actionable portfolio insights."""



