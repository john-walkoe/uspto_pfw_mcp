"""Patent Explanation For Attorneys Prompt"""

from . import mcp

@mcp.prompt(
    name="patent_explanation_for_attorneys",
    description="Generate layperson-friendly patent explanations for attorneys with technical analysis, claim scope assessment, and strategic implications. At least ONE identifier required (patent_number, application_number, or title_keywords). Requires PFW MCP."
)
async def patent_explanation_for_attorneys_prompt(
    patent_number: str = "",
    application_number: str = "",
    title_keywords: str = ""
) -> str:
    """
    Generate clear, accessible patent explanations for attorneys with strategic legal context.

    Identifiers (at least ONE required): patent_number, application_number, or title_keywords
    """

    return f"""# Attorney-Friendly Patent Explanation

**Inputs:** Patent "{patent_number}", App "{application_number}", Title "{title_keywords}"

---

## PHASE 1: Patent Retrieval

### Step 1: Identifier Resolution

```python
# Resolve to application number
if patent_number:
    results = await pfw_search_applications_minimal(
        query=patent_number,
        fields=['applicationNumberText', 'patentNumber', 'inventionTitle'],
        limit=1
    )
    app_number = results['applications'][0]['applicationNumberText']

# Get full technical content (FREE - uses XML, no OCR costs)
# NOTE: Set include_raw_xml=False for 91% token reduction (removes ~50K raw XML overhead)
# For inventor/assignee reports, add include_fields if not already obtained via search_balanced:
patent_xml = await pfw_get_patent_or_application_xml(
    identifier=app_number,
    include_fields=['abstract', 'claims', 'description', 'inventors', 'applicants'],
    include_raw_xml=False
)
```

### Step 2: Extract Core Elements

```python
# Parse XML for structured content
title = patent_xml['structured_content'].get('title')
abstract = patent_xml['structured_content']['abstract']
claims = patent_xml['structured_content']['claims']  # All claims with claim numbers
description = patent_xml['structured_content']['description']

# Extract metadata (included because we requested 'inventors' and 'applicants' fields)
inventors = [inv['name'] for inv in patent_xml['structured_content'].get('inventors', [])]
assignee = patent_xml['structured_content'].get('applicants', {{}}).get('name', 'Unknown')
filing_date = patent_xml.get('filing_date')
issue_date = patent_xml.get('issue_date')

# OPTIMIZATION TIP: If you already ran pfw_search_applications_balanced earlier,
# you may already have inventor/applicant info and can use default XML call
# (no include_fields needed - saves ~1K tokens)
```

---

## PHASE 2: Plain English Analysis

### Step 3: Create Executive Summary

**Template:**
```markdown
## Patent: {{title}} ({{patent_number}})

**Inventors:** {{', '.join(inventors)}}
**Assignee:** {{assignee}}
**Filed:** {{filing_date}} | **Issued:** {{issue_date}}

### What This Patent Protects

[2-3 sentence plain English summary of the invention]

**The Problem:** [What issue does this solve?]

**The Solution:** [How does the invention address it?]

**Why It Matters:** [Commercial significance, target market]
```

### Step 4: Technical Overview (Simplified)

```python
# Identify independent claims (broader scope)
independent_claims = [c for c in claims if c['claim_type'] == 'independent']

# Simplify technical language
print("### Core Innovation")
print()
print("**Key Components:**")
for claim in independent_claims:
    # Extract main elements from claim text
    # Translate technical terms to plain English
    print(f"- Claim {{claim['number']}}: [Simplified description]")
```

---

## PHASE 3: Legal Analysis

### Step 5: Claim Scope Assessment

```python
print("### Patent Scope Analysis")
print()

# Count claim types
total_claims = len(claims)
independent_count = len(independent_claims)
dependent_count = total_claims - independent_count

print(f"**Total Claims:** {{total_claims}}")
print(f"- Independent Claims: {{independent_count}} (broader scope)")
print(f"- Dependent Claims: {{dependent_count}} (narrower, defensive)")

# Assess breadth
if independent_count <= 3:
    print("\\n**Claim Strategy:** Focused - Limited independent claims suggest specific embodiments")
elif independent_count > 6:
    print("\\n**Claim Strategy:** Broad - Multiple independent claims cover various embodiments")
else:
    print("\\n**Claim Strategy:** Balanced - Moderate independent claim count")
```

### Step 6: Enforcement Considerations

```python
print("### Enforcement Analysis")
print()

# Analyze claim language for enforcement strength
claim_text = ' '.join([c['text'] for c in independent_claims])

# Indicators of enforcement strength
if 'means for' in claim_text.lower():
    print("- **Functional Language:** Contains means-plus-function claims (112(f) analysis needed)")

if any(term in claim_text.lower() for term in ['system', 'apparatus', 'device']):
    print("- **Product Claims:** Easier to detect infringement")

if any(term in claim_text.lower() for term in ['method', 'process', 'step']):
    print("- **Method Claims:** May require process monitoring for detection")

# Abstractness check
if any(term in claim_text.lower() for term in ['computer', 'software', 'algorithm']):
    print("- **101 Risk:** Software/business method patent - subject to Alice analysis")
```

### Step 7: Strategic Implications

```python
print("### Strategic Considerations")
print()

# Identify affected industries
print("**Potential Infringement Scenarios:**")
# Based on claim scope and technical field
print("- [Industry/Activity 1]")
print("- [Industry/Activity 2]")

print("\\n**Design-Around Opportunities:**")
# Analyze claim limitations for potential workarounds
print("- [Limitation 1]: Could be avoided by [alternative approach]")
print("- [Limitation 2]: Narrow scope suggests design-around possible")

print("\\n**Key Terms for Claim Construction:**")
# Identify 3-5 critical terms that will drive claim scope
print("- '{{term1}}': [Definition needed, impact on scope]")
print("- '{{term2}}': [Potentially ambiguous, check specification]")
```

---

## PHASE 4: Structured Output

### Final Report Format

```markdown
# Patent Analysis: {{title}}

**Patent Number:** {{patent_number}}
**Application:** {{app_number}}
**Inventors:** {{', '.join(inventors)}}
**Assignee:** {{assignee}}
**Filed:** {{filing_date}} | **Issued:** {{issue_date}}

---

## Executive Summary

[2-3 sentences in plain English describing what the patent protects]

**Problem Addressed:** [What market need or technical challenge]

**Innovation:** [How this invention solves it differently]

**Commercial Significance:** [Target market, potential licensees/infringers]

---

## Technical Overview

### Core Concept
[Plain English explanation of the invention without technical jargon]

### Key Components
- **Element 1:** [Simplified description]
- **Element 2:** [Simplified description]
- **Element 3:** [Simplified description]

### How It Works
[Step-by-step explanation in layperson terms]

---

## Legal Analysis

### Claim Scope
- **Total Claims:** {{total_claims}} ({{independent_count}} independent, {{dependent_count}} dependent)
- **Breadth Assessment:** [Broad/Moderate/Narrow based on claim count and language]
- **Claim Strategy:** [Analysis of filing strategy]

### Enforcement Strength
- **Infringement Detection:** [Easy/Moderate/Difficult]
- **Claim Type:** [Product/Method/System - implications for enforcement]
- **§101 Analysis:** [Any subject matter eligibility concerns]
- **§112 Considerations:** [Functional claiming, enablement issues]

### Strategic Implications

**Potential Infringement Activities:**
1. [Specific commercial activity covered by claims]
2. [Industry/market segment at risk]
3. [Product types that may infringe]

**Design-Around Analysis:**
- **Claim Limitations:** [Key constraints that enable workarounds]
- **Alternative Approaches:** [Potential non-infringing implementations]

**Critical Claim Terms:**
1. **"{{term1}}"** - [Why it's critical, how it affects scope]
2. **"{{term2}}"** - [Construction issues, spec support]
3. **"{{term3}}"** - [Potential ambiguity, impact on enforcement]

---

## Bottom Line for Counsel

**In Plain English:** [1-2 sentence summary of what this patent means]

**Key Takeaway:** [Practical legal significance - strength, scope, enforcement likelihood]

**Recommended Action:** [Next steps based on use case - due diligence/clearance/enforcement]
```

---

## Notes

- Uses `pfw_get_patent_or_application_xml` for FREE technical content (no OCR costs)
- **ALWAYS set include_raw_xml=False** to remove ~50K token raw XML overhead (91% reduction)
- **Default XML response:** abstract, claims, description (~5K tokens with include_raw_xml=False)
- **Add inventor/applicant fields:** Use include_fields=['abstract', 'claims', 'description', 'inventors', 'applicants'] for reports (~6K tokens with include_raw_xml=False)
- **Optimization:** If you used pfw_search_applications_minimal and need inventor/company info, add those fields
- **Alternative:** If you already ran pfw_search_applications_balanced, inventor/applicant data may already be in context
- Plain English translation requires domain knowledge of technical field
- Claim construction analysis preliminary - formal construction may differ
- Strategic implications depend on specific enforcement context

**For detailed prosecution history:** Use `complete_patent_package_retrieval_PTAB_FPD`
**For prior art analysis:** Use `prior_art_analysis_CITATION` (2017+ applications)

---

**Deliverable:** Attorney-ready patent explanation with plain English summary, technical analysis, claim scope assessment, and strategic enforcement implications."""
