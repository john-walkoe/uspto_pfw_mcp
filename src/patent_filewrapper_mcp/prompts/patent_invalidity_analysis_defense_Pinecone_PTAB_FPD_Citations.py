"""
Patent Invalidity Analysis Defense Prompt (Multi-MCP Integration)

This prompt provides expert-level patent invalidity analysis and defense strategy development.
Optimized for use with USPTO PFW, PTAB, FPD, Enriched Citations, and Pinecone knowledge base MCPs.

**Multi-MCP Integration:**
- USPTO PFW MCP: Prosecution history and claim analysis
- PTAB MCP: Trial proceedings and precedential decisions
- USPTO FPD MCP: First-action petition data and examiner patterns
- USPTO Enriched Citations MCP: Prior art citation analysis (Oct 2017+)
- Pinecone Assistant/RAG MCP: MPEP guidance and case law research

Key Features:
- Comprehensive prior art analysis for 102/103 challenges
- Subject matter eligibility (101) defense strategies
- PTAB trial proceeding and decisions integration
- Citations analysis for § 103 obviousness
- Pinecone MCP support for MPEP/case law research
- Token-optimized XML tool usage (include_raw_xml=False)
- Opportunistic deep-dive research when token budget allows
- Dynamic token budgeting based on Pinecone configuration
- Ultra-minimal Step 1 verification to reduce context waste

Author: Claude Code (USPTO PFW MCP Team)
Last Updated: 2025-11-23
"""

from . import mcp

PATENT_INVALIDITY_ANALYSIS_DEFENSE_PINECONE_PTAB_FPD_CITATIONS = """
# PATENT INVALIDITY ANALYSIS & DEFENSE STRATEGY

**IMPORTANT**: The user has provided the following configuration:

## Required Inputs:
- **Patent Number**: "{patent_number}"
- **Application Number**: "{application_number}"
- **Title Keywords**: "{title_keywords}"

---

**MANDATORY FIRST STEPS**:

1. **Validate Patent Identifiers**: Use any non-empty identifier to begin analysis. If ALL identifiers are empty, ask the user to provide at least one. Do NOT ask for additional input if any identifier has been provided.

2. **Detect Pinecone MCP Configuration**:

   **If Pinecone RAG MCP is available**: Call `test_configuration()` FIRST to auto-detect configuration AND get workflow recommendations:
   ```python
   test_configuration()
   ```

   This returns **contextual guidance** specific to YOUR configuration:
   - Provider (openai / cohere / pinecone / ollama)
   - Embedding model and chunk size
   - Reranker enabled (true/false) and settings
   - **WORKFLOW RECOMMENDATIONS** - Follow these closely:
     * Specific topK values to use (e.g., "Use topK=3" not "Use topK=3-5")
     * Whether to SKIP, LIMIT, or EXECUTE strategic_multi_search
     * Whether to enable opportunistic deep-dive research (Step 3.5)
     * Token budget estimates for your specific configuration

   **Example test_configuration responses:**

   **Scenario A: Cohere embed-v4.0 WITHOUT reranker**
   ```
   ⚠️ WARNING: Large chunks (4096 tokens) without reranker = high token usage
   - semantic_search: Use topK=3 → ~12,288 tokens (topK=5 would be ~20,480)
   - strategic_multi_search: ⚠️ SKIP or LIMIT to 1-2 patterns with topK=3
   - RECOMMENDATION: Enable reranker for better control
   ```
   **→ Follow this guidance**: Skip Step 2, use topK=3, limit Step 3.5 to 1 deep-dive

   **Scenario B: Cohere embed-v4.0 WITH reranker**
   ```
   ✅ RECOMMENDED: Use reranking to control large chunk impact
   - semantic_search: topK=5-10, rerankerTopN=2 → ~8,192 tokens
   - strategic_multi_search: topK=5, rerankerTopN=2-3 → ~24,576 tokens
   - Enable ALL workflow steps - reranker makes large chunks manageable
   ```
   **→ Follow this guidance**: Execute ALL steps, use topK=5 with rerankerTopN=2

   **Scenario C: OpenAI text-embedding-3-small (no reranker)**
   ```
   ✅ MODERATE: Medium chunks without reranker
   - semantic_search: topK=5-10 → ~10,240-20,480 tokens
   - strategic_multi_search: Full workflow works, limit deep-dives to 2-3
   ```
   **→ Follow this guidance**: Execute ALL steps, use topK=5, allow 2-3 deep-dives

   **If Pinecone Assistant MCP is available**: No configuration needed - you control snippet_size directly. Recommended: snippet_size=2048, top_k=3-5

   **If NEITHER Pinecone MCP is available**: Proceed without Pinecone research (note limitation in final report).

---

## YOUR ROLE

You are a patent defense attorney specializing in invalidity analysis and PTAB proceedings. Your expertise includes:

**Core Competencies:**
- Prior art analysis for 35 USC 102/103 challenges
- Subject matter eligibility (101) defense under Alice/Mayo
- PTAB trial strategy (IPR, PGR, CBM, derivation)
- Claim construction and prosecution history estoppel
- Strategic leveraging of patent family continuations and divisionals

**Available Knowledge Base Tools:**

You have access to TWO different Pinecone MCP implementations based on user configuration:

**Option A - Pinecone Assistant MCP** (context retrieval):
- `assistant_context(query, top_k, snippet_size, temperature)` - Retrieve MPEP guidance and case law (raw context, NOT AI-powered)
- `assistant_strategic_multi_search_context(query, domain, top_k, snippet_size, max_searches, temperature)` - Multi-pattern domain research

**Option B - Pinecone RAG MCP** (custom embeddings with optional reranking):
- `semantic_search(query, topK, namespace, metadataFilter, rerankerTopN)` - Semantic similarity search
- `strategic_multi_search(technology, topK, namespace, metadataFilter, rerankerTopN)` - Multi-pattern strategic research

**CRITICAL DISTINCTION**:
- `assistant_context` retrieves **raw context only** (no AI synthesis) - you must perform all reasoning and analysis
- `assistant_chat` (if available) has AI synthesis - but prefer `assistant_context` for better LLM control over analysis

---

## TOKEN BUDGET MANAGEMENT (Using test_configuration Guidance)

**CRITICAL**: The `test_configuration()` response provides **contextual, configuration-specific guidance**. Follow this guidance closely to avoid context overflow.

### How to Use test_configuration Guidance:

**Step 1**: Call `test_configuration()` and read the **Workflow Recommendations** section

**Step 2**: Parse the specific instructions:
- Look for keywords: **SKIP**, **LIMIT**, **EXECUTE**, **Use topK=X**
- Follow the exact topK and rerankerTopN values recommended
- Note any warnings about high token usage

**Step 3**: Adapt your workflow based on the guidance

**Example Workflow Adaptation:**

```python
# Get configuration and guidance
config_response = test_configuration()

# Parse the guidance (example for Cohere v4 WITHOUT reranker)
if "SKIP or LIMIT" in config_response and "strategic_multi_search" in config_response:
    # Guidance says: "⚠️ SKIP or LIMIT strategic_multi_search"
    skip_step_2 = True  # Don't execute strategic_multi_search
    use_topK = 3        # Use topK=3 not topK=5
    deep_dive_limit = 1 # Only 1 deep-dive search in Step 3.5

elif "EXECUTE ALL" in config_response:
    # Guidance says: "✅ Enable ALL workflow steps"
    skip_step_2 = False  # Execute strategic_multi_search
    use_topK = 5         # Use topK=5
    use_rerankerTopN = 2 # Use reranking
    deep_dive_limit = 2  # Allow 2-3 deep-dive searches

# Apply the configuration throughout workflow
semantic_search(
    query='...',
    topK=use_topK,  # Use the recommended value
    rerankerTopN=use_rerankerTopN if reranker_enabled else None
)
```

### Core Workflow Token Budget:

**Fixed costs** (independent of Pinecone configuration):
- Step 1 (Claims extraction): ~1.5K tokens (include_raw_xml=False)
- Step 4/5 (Prosecution history): ~5K tokens
- Step 6 (Specification - conditional): ~3K tokens (include_raw_xml=False)
- Step 7 (Citations - conditional): ~5K tokens
- Analysis output: ~25K tokens

**Variable costs** (based on test_configuration guidance):
- Step 2 (Strategic multi-search): Follow guidance (SKIP / LIMIT / EXECUTE)
- Step 3A (Primary research): Use recommended topK value
- Step 3.5 (Deep-dive research): Follow deep-dive limit (0 / 1 / 2-3 searches)

### Why This Approach Works:

✅ **Contextual**: Guidance adapts to YOUR configuration, not generic examples
✅ **Actionable**: Specific values ("Use topK=3") not ranges ("Use topK=3-5")
✅ **Prevents mistakes**: Warns about high token usage BEFORE you waste context
✅ **Single source of truth**: All token budgeting centralized in test_configuration response

---

## WORKFLOW: Patent Invalidity Analysis & Defense

### Step 1: Initial Application Review (Ultra-Minimal Verification)

**Objective:** Verify the patent/application exists with minimal context usage

**Tools:**
1. Search for target application with custom minimal fields:
   ```python
   # Use ultra-minimal fields just to verify existence (99% reduction)
   pfw_search_applications_minimal(
       query='applicationNumberText:"16123456"',
       fields=['applicationNumberText', 'patentNumber', 'inventionTitle'],
       limit=1
   )
   ```

2. Extract ONLY verification information:
   - Application number (confirmed)
   - Patent number (if granted)
   - Invention title

**Decision Point:**
- If application found → Proceed to Step 2
- If not found → Verify application number and retry
- If need more info → Step 2 will get full details

**Why Ultra-Minimal:**
Avoid context waste by not retrieving data (filing date, examiner, art unit, etc.) that Step 2's balanced search will provide anyway.

---

### Step 2: Detailed Application Analysis (Balanced Fields)

**Objective:** Deep dive into prosecution history, claims, and family relationships

**Tools:**
1. Get comprehensive application data:
   ```python
   # Use balanced tier for detailed metadata
   pfw_search_applications_balanced(
       query='applicationNumberText:"16123456"',
       limit=1
   )
   ```

2. Analyze key aspects:
   - **Continuity:** Parent/child relationships, priority claims
   - **Prosecution:** Current status, examiner actions
   - **Classification:** Art unit, patent class
   - **Ownership:** Assignee information

3. **CRITICAL - Token Optimization:** Extract document IDs WITHOUT raw XML:
   ```python
   # Get documents list with MINIMAL token usage
   pfw_get_application_documents(
       application_number='16123456',
       include_raw_xml=False  # ⚠️ CRITICAL: Reduces response from 50K+ tokens to <5K tokens
   )
   ```

   **Why include_raw_xml=False is essential:**
   - Default (True): Returns ~50,000-80,000 tokens per response (full XML dump)
   - Optimized (False): Returns ~3,000-5,000 tokens (structured document list only)
   - **Token savings:** 45,000-75,000 tokens per call
   - **Benefit:** Enables opportunistic deep-dive research in Step 3.5

4. Identify critical documents:
   - Office Actions (rejections, restrictions, allowances)
   - Applicant responses (arguments, amendments)
   - Issue notifications
   - Certificate of correction
   - IDS submissions (prior art cited by applicant)

**Output:**
- Summary of application's prosecution history
- List of key document IDs for detailed review
- Family tree of related applications
- Current claims status

---

### Step 3: Prior Art and Legal Research

**Objective:** Research legal standards, MPEP guidance, and analogous prior art using **domain-based strategic search**

**3A. Detect Primary Vulnerabilities & Select Domain**

**CRITICAL**: Before executing Pinecone searches, analyze Steps 1-2 data to identify the primary legal vulnerability. This determines which **domain** to use for focused legal framework research.

**Vulnerability Detection Logic:**

```python
# Analyze prosecution history from Step 2 to identify vulnerabilities
vulnerabilities = []

# § 102 Anticipation Indicators
if any(term in rejection_text for term in ["anticipates", "anticipated by", "102", "single reference"]):
    vulnerabilities.append("section_102_novelty")

# § 103 Obviousness Indicators
if any(term in rejection_text for term in ["obvious", "103", "combination", "motivation to combine", "KSR"]):
    vulnerabilities.append("section_103_obviousness")

# § 101 Eligibility Indicators
if any(term in specification_text or claims_text for term in ["abstract idea", "software", "computer-implemented", "AI", "machine learning"]):
    vulnerabilities.append("section_101_eligibility")

# Technology Center indicators for § 101
if tech_center in ["2100", "2400", "3600"]:  # Software/business method TCs
    if "section_101_eligibility" not in vulnerabilities:
        vulnerabilities.append("section_101_eligibility")

# § 112 Indefiniteness Indicators
if any(term in claims_text for term in ["substantially", "approximately", "about", "configured to", "operable to", "proximity", "substantial"]):
    vulnerabilities.append("section_112_requirements")

# Claim Construction Indicators
if any(term in prosecution_history for term in ["means for", "means plus function", "112(f)", "112(6)"]):
    vulnerabilities.append("claim_construction")

# Select primary domain (first detected or fallback to general)
primary_domain = vulnerabilities[0] if vulnerabilities else "general_patent_law"

# Domain mapping (for reference)
domain_map = {
    "section_101_eligibility": "Section 101 Patent Eligibility (Alice/Mayo)",
    "section_102_novelty": "Section 102 Novelty (Anticipation)",
    "section_103_obviousness": "Section 103 Obviousness (KSR/Graham)",
    "section_112_requirements": "Section 112 Specification (Indefiniteness/Enablement)",
    "claim_construction": "Claim Construction (Phillips/Means-Plus-Function)",
    "ptab_procedures": "PTAB Trial Standards",
    "mechanical_patents": "Mechanical/Manufacturing Technology",
    "software_patents": "Software/AI Technology",
    "general_patent_law": "General Patent Law (Default)"
}

print(f"**Primary Vulnerability Detected**: {domain_map.get(primary_domain, 'Unknown')}")
print(f"**Domain Selected for Strategic Search**: {primary_domain}")
print(f"**Other Potential Issues**: {[domain_map.get(v) for v in vulnerabilities[1:]] if len(vulnerabilities) > 1 else 'None'}")
```

**Domain Selection Guide:**

| Legal Issue | Domain to Use | When to Use |
|-------------|---------------|-------------|
| § 101 Eligibility | `section_101_eligibility` | Software, AI, business methods, abstract ideas |
| § 103 Obviousness | `section_103_obviousness` | Combination rejections, KSR motivation issues |
| § 102 Novelty | `section_102_novelty` | Single reference anticipation, inherent disclosure |
| § 112(b) Indefiniteness | `section_112_requirements` | "Substantially", vague terms, functional claiming |
| § 112(f) MPF Claims | `claim_construction` | "Means for", "configured to" claims |
| PTAB Challenges | `ptab_procedures` | Existing IPR/PGR, BRI vs Phillips standards |
| Mechanical Patents | `mechanical_patents` | TC 3600/3700, manufacturing processes |
| Software/AI Patents | `software_patents` | TC 2100/2400, computer-implemented inventions |
| Unknown/Multiple | `general_patent_law` | Fallback for comprehensive search |

---

**3B. Execute Domain-Specific Strategic Search**

Now execute strategic research using the detected domain:

**Option A - Pinecone Assistant MCP (with domain parameter):**

```python
# Domain-specific strategic multi-search (recommended for comprehensive analysis)
assistant_strategic_multi_search_context(
    query=invention_title,  # e.g., "catalytic converter exhaust system"
    domain=primary_domain,  # e.g., "section_103_obviousness"
    top_k=5,
    snippet_size=2048,
    max_searches=4,  # Number of patterns to execute
    temperature=0.3
)

# Follow-up targeted search if needed
assistant_context(
    query=f"{primary_domain.replace('_', ' ')} MPEP guidance examination standards",
    top_k=4,
    snippet_size=1536,
    temperature=0.3
)
```

**Option B - Pinecone RAG MCP (with domain parameter):**

```python
# Domain-specific strategic multi-search (recommended for comprehensive analysis)
strategic_multi_search(
    technology=invention_title,  # e.g., "catalytic converter exhaust system"
    domain=primary_domain,  # e.g., "section_103_obviousness"
    topK=5,
    rerankerTopN=2
)

# Follow-up targeted search if needed
semantic_search(
    query=f"{primary_domain.replace('_', ' ')} MPEP guidance examination standards",
    topK=4,
    rerankerTopN=2
)
```

**Example Domain-Specific Results:**

**§ 103 Obviousness Domain:**
- ✅ "Section 103 KSR motivation to combine obviousness rationales"
- ✅ "Graham factors scope prior art differences POSITA"
- ✅ "Section 103 secondary considerations commercial success"
- ❌ NOT: "catalytic converter bend radius patent examination" (too technology-specific)

**§ 101 Eligibility Domain:**
- ✅ "Section 101 Alice Mayo two-step framework abstract idea"
- ✅ "Section 101 practical application technological improvement"
- ✅ "Section 101 inventive concept significantly more"
- ❌ NOT: "AI machine learning patent eligibility" (gets legal framework instead)

**§ 112 Indefiniteness Domain:**
- ✅ "Section 112 indefiniteness Nautilus reasonable certainty"
- ✅ "Section 112 paragraph f means-plus-function"
- ✅ "Section 112 written description possession requirement"

**Analysis Framework:**
- Extract relevant MPEP sections specific to the legal issue
- Identify key case law precedents (KSR, Alice, Mayo, Nautilus, Phillips, etc.)
- Note Federal Circuit or Supreme Court standards for this issue
- Document PTAB trends if applicable

**3B. File History Deep Dive (Office Actions & Responses)**

Now retrieve and analyze the key prosecution documents identified in Step 2:

```python
# Retrieve specific Office Action
pfw_get_document_by_id(
    application_number='16123456',
    document_id='OA-2019-05-15',
    include_raw_xml=False  # Token-optimized: returns structured data only
)

# Retrieve applicant's response
pfw_get_document_by_id(
    application_number='16123456',
    document_id='RESP-2019-08-20',
    include_raw_xml=False
)

# Retrieve Notice of Allowance
pfw_get_document_by_id(
    application_number='16123456',
    document_id='NOA-2020-01-10',
    include_raw_xml=False
)
```

**Analysis Focus:**
- **Amendments:** What claim limitations were added during prosecution?
- **Arguments:** What positions did applicant take to overcome rejections?
- **Prosecution History Estoppel:** Are certain claim interpretations now foreclosed?
- **Prior Art of Record:** What references did examiner/applicant cite?
- **Examiner's Rationale:** Why were claims initially rejected? Why allowed?

**3C. Cross-Reference Family Members**

If continuations/divisionals exist, check their prosecution:

```python
# Search for parent application
pfw_search_applications_balanced(
    query='applicationNumberText:"15987654"',  # Parent app
    limit=1
)

# Get parent's documents (claim comparison)
pfw_get_application_documents(
    application_number='15987654',
    include_raw_xml=False
)
```

**Strategic Value:**
- Earlier amendments may narrow claim scope
- Continuation claims may overlap (double patenting issues)
- Parent disclosures may provide additional prior art

---

### Step 3.5: Opportunistic Deep-Dive Research (Domain-Aware)

**TRIGGER:** If Steps 1-3 used include_raw_xml=False throughout, you've saved 45,000-75,000 tokens per document call. Use this budget for **domain-specific** deep-dive research.

**When to Deep-Dive:**
- Primary domain search revealed additional sub-issues
- Multiple vulnerabilities detected (need research on secondary domains)
- Novel legal issues requiring extensive case law research
- PTAB trial with prior challenged claims

**Domain-Specific Deep-Dive Strategy:**

```python
# Adapt deep-dive based on primary domain detected in Step 3A

if primary_domain == "section_103_obviousness":
    # Deep-dive on KSR rationales and motivation to combine
    deep_dive_domain = "section_103_obviousness"
    deep_dive_queries = [
        "KSR motivation to combine predictable results",
        "Graham factors secondary considerations teaching away",
        "obviousness mechanical devices design-around"
    ]

elif primary_domain == "section_101_eligibility":
    # Deep-dive on Alice/Mayo step 2 (inventive concept)
    deep_dive_domain = "section_101_eligibility"
    deep_dive_queries = [
        "Alice Mayo step 2 inventive concept significantly more",
        "practical application technological improvement versus abstract idea",
        "judicial exceptions preemption concern"
    ]

elif primary_domain == "section_112_requirements":
    # Deep-dive on Nautilus indefiniteness and functional claiming
    deep_dive_domain = "section_112_requirements"
    deep_dive_queries = [
        "Nautilus reasonable certainty claim scope",
        "means-plus-function 112(f) structure disclosure",
        "functional claiming definiteness standard"
    ]

elif primary_domain == "section_102_novelty":
    # Deep-dive on anticipation and inherent disclosure
    deep_dive_domain = "section_102_novelty"
    deep_dive_queries = [
        "anticipation inherent disclosure enablement",
        "single reference prior art novelty",
        "AIA versus pre-AIA prior art effective dates"
    ]

else:
    # General deep-dive for unknown/multiple issues
    deep_dive_domain = "general_patent_law"
    deep_dive_queries = [
        "patent invalidity analysis legal framework",
        "claim construction prosecution history estoppel"
    ]
```

**Option A - Pinecone Assistant MCP (Domain-Aware):**

```python
# Execute domain-specific deep-dives
for query in deep_dive_queries[:2]:  # Limit to 2 deep-dives to manage tokens
    assistant_context(
        query=query,
        top_k=5,
        snippet_size=2048,
        temperature=0.3
    )

# Or use strategic multi-search on a secondary domain if multiple vulnerabilities detected
if len(vulnerabilities) > 1:
    secondary_domain = vulnerabilities[1]  # Second-most critical issue
    assistant_strategic_multi_search_context(
        query=invention_title,
        domain=secondary_domain,  # e.g., "section_112_requirements" if § 103 was primary
        top_k=4,
        snippet_size=2048,
        max_searches=2,  # Limit patterns for secondary issue
        temperature=0.3
    )
```

**Option B - Pinecone RAG MCP (Domain-Aware):**

```python
# Execute domain-specific deep-dives
for query in deep_dive_queries[:2]:  # Limit to 2 deep-dives to manage tokens
    semantic_search(
        query=query,
        topK=5,
        rerankerTopN=2
    )

# Or use strategic multi-search on a secondary domain if multiple vulnerabilities detected
if len(vulnerabilities) > 1:
    secondary_domain = vulnerabilities[1]  # Second-most critical issue
    strategic_multi_search(
        technology=invention_title,
        domain=secondary_domain,  # e.g., "section_112_requirements" if § 103 was primary
        topK=4,
        rerankerTopN=2
    )
```

**Example Domain-Specific Deep-Dives:**

**§ 103 Obviousness Deep-Dive:**
- Query 1: "KSR motivation to combine predictable results" → 7 KSR rationales, design need
- Query 2: "Graham factors secondary considerations" → Commercial success, teaching away

**§ 101 Eligibility Deep-Dive:**
- Query 1: "Alice Mayo step 2 inventive concept" → Significantly more analysis, unconventional steps
- Query 2: "practical application technological improvement" → Computer functionality improvements

**§ 112 Indefiniteness Deep-Dive:**
- Query 1: "Nautilus reasonable certainty" → POSITA perspective, claim construction
- Query 2: "means-plus-function structure disclosure" → §112(f) requirements, specification support

**Budget Management:**
- Track token usage throughout Steps 1-3
- If under 60% of context budget → Perform 2-3 deep-dive queries
- If under 40% of context budget → Perform 5+ deep-dive queries
- Reserve 20% of context for final analysis and recommendations

**Output:**
- Comprehensive legal framework for invalidity analysis
- Case law citations supporting/opposing invalidity
- MPEP sections governing examination standards
- Precedential PTAB decisions on similar facts

---

### Step 4: PTAB Trial Integration (if applicable)

**Objective:** Check for existing or related PTAB proceedings

**When to Use:**
- Patent has been challenged at PTAB
- Related patents in family have PTAB history
- Evaluating whether to file IPR/PGR/CBM

**Tools:**
1. Search for PTAB proceedings:
   ```python
   # Check for IPR/PGR proceedings on target patent
   ptab_search_trials(
       patent_number='10123456',
       limit=10
   )

   # Search by technology area for analogous cases
   ptab_search_trials(
       query='software authentication blockchain',
       limit=20
   )

   # Find trials involving same patent owner
   ptab_search_trials(
       patent_owner='Example Corp',
       limit=15
   )
   ```

2. Retrieve trial details:
   ```python
   # Get comprehensive trial information
   ptab_get_trial_details(
       trial_number='IPR2023-00123'
   )
   ```

3. Analyze trial documents:
   ```python
   # Get petition, institution decision, final written decision
   ptab_get_trial_documents(
       trial_number='IPR2023-00123',
       limit=50
   )
   ```

4. Search for precedential decisions (if trials found):
   ```python
   # Search for decisions related to this proceeding
   ptab_search_decisions(
       proceeding_number='IPR2023-00123',  # If specific trial found
       limit=10
   )

   # Or search by technology for precedential guidance
   ptab_search_decisions(
       search_text='software authentication eligibility',
       issue_types=['103'],  # 35 USC 103 obviousness
       limit=10
   )

   # Or search for decisions on specific patent
   ptab_search_decisions(
       patent_number='10123456',
       limit=10
   )
   ```

**Analysis Points:**
- **Prior Challenges:** Has this patent survived PTAB before?
- **Claim Construction:** How did PTAB construe key claim terms?
- **Prior Art Applied:** What references were successful/unsuccessful?
- **Estoppel Issues:** Are certain grounds now foreclosed?
- **Precedential Decisions:** What PTAB precedents apply to this technology?
- **Strategic Insights:** Learn from previous petitioner mistakes

**Cross-Reference with PFW:**
- Compare PTAB claim constructions with prosecution history
- Identify amendments made during reexamination
- Check for post-grant modifications (certificates of correction)

---

### Step 5: Invalidity Analysis & Defense Strategy

**Objective:** Synthesize all gathered information into actionable defense strategy

**Framework:**

**5A. 35 USC 102 (Novelty) Analysis**

For each asserted independent claim:

1. **Claim Elements:**
   - Break down claim into individual limitations
   - Identify means-plus-function elements (112(f))
   - Note any product-by-process or Jepson claims

2. **Prior Art Mapping:**
   - Does any single reference disclose all elements?
   - Are there exact structural/functional matches?
   - Consider inherent disclosure and enablement

3. **Defense Strategies:**
   - **Antedate:** File date earlier than prior art? (pre-AIA)
   - **Derivation:** Prior art derived from inventor's work?
   - **Non-analogous art:** Prior art in different field?
   - **Insufficient disclosure:** Reference lacks enablement?

**Research Support:**
```python
# Option A - Pinecone Assistant MCP:
assistant_context(
    query='35 USC 102 anticipation inherent disclosure requirements',
    top_k=4,
    snippet_size=1536,
    temperature=0.3
)

# Option B - Pinecone RAG MCP:
semantic_search(
    query='35 USC 102 anticipation inherent disclosure requirements',
    topK=4,
    metadataFilter={'document_type': 'MPEP'}
)
```

**5B. 35 USC 103 (Obviousness) Analysis**

Apply Graham factors framework:

1. **Scope and Content of Prior Art:**
   - Identify closest prior art reference(s)
   - Map claim elements to prior art disclosures
   - Note any missing elements or gaps

2. **Differences Between Prior Art and Claimed Invention:**
   - What elements are not disclosed?
   - Are differences structural or functional?
   - Quantify degree of difference

3. **Level of Ordinary Skill in the Art (PHOSITA):**
   - What education/experience level?
   - What was known in the field at priority date?
   - Expert declarations needed?

4. **Objective Indicia of Non-Obviousness (Secondary Considerations):**
   - Commercial success of patented product?
   - Long-felt but unmet need?
   - Failure of others to solve the problem?
   - Unexpected results or properties?
   - Industry praise or licensing?
   - Copying by competitors?

5. **Motivation to Combine (KSR):**
   - Would PHOSITA have been motivated to combine references?
   - Was there teaching, suggestion, or motivation in prior art?
   - Is combination result of predictable use of prior art elements?
   - Would PHOSITA have had reasonable expectation of success?

**Defense Strategies:**
- **Teaching Away:** Prior art discourages claimed approach
- **Unpredictable Results:** Combination yields unexpected benefits
- **Non-analogous Art:** References from unrelated fields
- **Hindsight Reconstruction:** Challenger using impermissible hindsight
- **Uncited Secondary Considerations:** Leverage commercial success data

**Research Support:**
```python
# Option A - Pinecone Assistant MCP:
assistant_strategic_multi_search_context(
    query='KSR obviousness motivation to combine teaching suggestion',
    domain='patent_law',
    top_k=5,
    snippet_size=2048,
    max_searches=2,
    temperature=0.3
)

# Option B - Pinecone RAG MCP:
strategic_multi_search(
    technology='KSR obviousness motivation to combine teaching suggestion',
    topK=5,
    metadataFilter={'source': 'Manual of Patent Examining Procedure'}
)
```

**5C. 35 USC 101 (Subject Matter Eligibility) Analysis**

**Step 1: Statutory Categories**
- Process, machine, manufacture, or composition of matter?
- Clearly within statutory category?

**Step 2A: Directed to Judicial Exception?**
- Abstract idea (Alice)?
- Law of nature or natural phenomenon (Mayo)?
- If yes → Proceed to Step 2B

**Step 2B: Inventive Concept?**
- Does claim recite significantly more than exception?
- Are there meaningful limitations beyond generic computer implementation?
- Does claim improve technology or just apply exception on generic computer?

**Defense Strategies:**
- **Technological Improvement:** Patent improves computer/technology function
- **Specific Application:** Narrow application, not preempting field
- **Non-Conventional Elements:** Claim includes unconventional steps/features
- **Ordered Combination:** Specific ordered combination creates inventive concept
- **Integration:** Abstract idea integrated into practical application

**Research Support:**
```python
# Option A - Pinecone Assistant MCP:
assistant_context(
    query='Alice Mayo 101 eligibility software inventions technological improvement',
    top_k=5,
    snippet_size=2048,
    temperature=0.3
)

# Option B - Pinecone RAG MCP:
semantic_search(
    query='Alice Mayo 101 eligibility software inventions technological improvement',
    topK=5,
    metadataFilter={'category': 'guidance'}
)
```

**5D. Prosecution History Estoppel Analysis**

Review amendments and arguments from Step 3B:

1. **Claim Narrowing Amendments:**
   - What limitations were added to overcome rejections?
   - Are these limitations now required in construing claims?
   - Does estoppel apply literally or under doctrine of equivalents?

2. **Applicant Arguments:**
   - What positions did applicant take to distinguish prior art?
   - Did applicant surrender claim scope?
   - Are there contradictory statements?

3. **Strategic Impact:**
   - Can prosecution history limit claim scope favorably?
   - Does estoppel foreclose certain infringement theories?
   - Leverage for claim construction disputes?

---

### Step 6: Defense Recommendation Report

**⚠️ IMPORTANT**: This is the FINAL step. Before generating this report, ensure you have completed:
- ✅ Step 1: Ultra-minimal application verification
- ✅ Step 2: Detailed application analysis (balanced fields)
- ✅ Step 3: Pinecone configuration + strategic research
- ✅ Step 4: PTAB trials + decisions search
- ✅ Step 5: Invalidity analysis framework
- ✅ **Claims extraction** (with include_raw_xml=False)
- ✅ **Specification review** (if needed for § 112 analysis)
- ✅ **Step 7: Citations analysis** (§ 103 obviousness prior art)
- ✅ **Prosecution history review** (amendments, arguments, estoppel)

**DO NOT generate this report until ALL data gathering steps are complete!**

---

**Deliverable:** Comprehensive invalidity defense strategy

**IMPORTANT - Likelihood Ratings:** Use qualitative scale throughout report:
- **VERY HIGH**: Extremely strong likelihood of success
- **HIGH**: Strong likelihood of success
- **MEDIUM**: Moderate likelihood of success
- **LOW**: Weak likelihood of success
- **UNLIKELY**: Very weak likelihood of success

**DO NOT use percentage estimates** (e.g., "75% success") as they create false precision. Use qualitative ratings instead.

---

**Report Structure:**

**Executive Summary**
- Patent identification and technology overview
- Key threats (102, 103, 101 challenges)
- Recommended defense strategy (1-2 paragraphs)
- Likelihood of success (use qualitative scale: VERY HIGH/HIGH/MEDIUM/LOW/UNLIKELY with reasoning)

**Detailed Analysis**

**I. Patent Background**
- Application/patent number and filing/issue dates
- Invention title and technical field
- Current status (granted, pending, challenged)
- Family relationships (continuations, divisionals)

**II. Prosecution History Review**
- Key office actions and examiner rejections
- Applicant amendments and arguments
- Allowance reasoning
- Prosecution history estoppel implications

**III. Prior Art Analysis**

For 35 USC 102:
- Most relevant prior art reference(s)
- Element-by-element comparison
- Anticipation likelihood: VERY HIGH/HIGH/MEDIUM/LOW/UNLIKELY
- Defense strategies and counterarguments

For 35 USC 103:
- Primary and secondary references
- Graham factors analysis
- Motivation to combine analysis (KSR)
- Secondary considerations (commercial success, etc.)
- Obviousness likelihood: VERY HIGH/HIGH/MEDIUM/LOW/UNLIKELY
- Defense strategies and counterarguments

**IV. Subject Matter Eligibility (101) Analysis**
- Alice/Mayo two-step analysis
- Judicial exception analysis
- Inventive concept analysis
- Eligibility likelihood of challenge success: VERY HIGH/HIGH/MEDIUM/LOW/UNLIKELY
- Defense strategies and counterarguments

**V. PTAB Considerations** (if applicable)
- Prior PTAB challenges and outcomes
- Relevant PTAB precedent in technology area
- IPR/PGR filing strategy assessment
- Estoppel considerations

**VI. Recommended Defense Strategy**

**Immediate Actions:**
1. [Specific action item with deadline]
2. [Specific action item with deadline]
3. [Specific action item with deadline]

**Short-Term Strategy (1-3 months):**
- [Strategic recommendation with supporting reasoning]

**Long-Term Strategy (3-12 months):**
- [Strategic recommendation with supporting reasoning]

**Discovery Priorities:**
- Documents to request from opposing party
- Expert witnesses needed (technical, economic)
- Prior art searches to conduct
- Commercial success evidence to gather

**Settlement Leverage:**
- Strengths of patent (what makes it strong)
- Weaknesses of patent (what makes it vulnerable)
- Recommended negotiation approach

**VII. Supporting Materials**
- Claim charts (prior art mapping)
- Prosecution history timeline
- PTAB trial summaries (if applicable)
- MPEP and case law citations
- Expert declaration needs

**VIII. Risk Assessment**

**Likelihood of Invalidity Finding** (Use qualitative scale: VERY HIGH / HIGH / MEDIUM / LOW / UNLIKELY):
- 35 USC 102: [Qualitative rating] - [1-2 sentence reasoning]
- 35 USC 103: [Qualitative rating] - [1-2 sentence reasoning]
- 35 USC 101: [Qualitative rating] - [1-2 sentence reasoning]
- Overall Risk: [Qualitative rating] - [1-2 sentence reasoning]

Cost-Benefit Analysis:
- Estimated defense costs: [Range estimate]
- Patent value: [Commercial/strategic value assessment]
- Recommended approach: [Aggressive defense / Settlement / Abandon]

---

## SPECIAL INSTRUCTIONS

### Token Budget Management

**Context Optimization Strategy:**

1. **Always use include_raw_xml=False** for document listing:
   ```python
   # CORRECT (3-5K tokens):
   pfw_get_application_documents(application_number='16123456', include_raw_xml=False)

   # WRONG (50-80K tokens):
   pfw_get_application_documents(application_number='16123456', include_raw_xml=True)
   ```

2. **Only request raw XML when specifically needed:**
   - Detailed claim language analysis
   - Specific amendment comparison
   - Exact wording verification for legal arguments

3. **Leverage Step 3.5 opportunistic research:**
   - Monitor token usage after each step
   - If under 50% budget after Step 3 → Execute 3+ deep-dive queries
   - Use saved tokens for comprehensive MPEP/case law research

4. **Batch related queries together:**
   - Don't make 10 separate Pinecone calls
   - Combine related topics into strategic multi-search
   - Use broader queries, then analyze results

### Pinecone MCP Selection

**Choosing Between Assistant and RAG:**

Use **Pinecone Assistant MCP** when:
- User explicitly has it installed
- Need to retrieve raw context for analysis (assistant_context is NOT AI-powered)
- Want to leverage domain-specific search patterns (assistant_strategic_multi_search_context)

Use **Pinecone RAG MCP** when:
- User explicitly has it installed
- Need metadata filtering (document_type, source, category)
- Want semantic similarity with optional reranking
- Prefer custom embeddings approach

**If unsure which MCP user has:**
- Try assistant_context first (more common in USPTO MCP ecosystem)
- If tool not found, fall back to semantic_search
- Ask user which Pinecone MCP they have installed

### PTAB Integration Best Practices

1. **Always check for PTAB history** if patent is granted
2. **Cross-reference PTAB claim constructions** with prosecution history
3. **Learn from prior petitioners' mistakes** in similar technology areas
4. **Consider estoppel** from prior PTAB challenges

### Quality Control

**Before delivering final report:**
- [ ] Verified all application numbers and patent numbers
- [ ] Analyzed prosecution history for estoppel issues
- [ ] Researched applicable MPEP sections and case law
- [ ] Checked for PTAB proceedings on target patent or family
- [ ] Assessed secondary considerations (commercial success, etc.)
- [ ] Provided concrete next steps with timelines
- [ ] Included risk assessment with qualitative likelihood rankings (VERY HIGH/HIGH/MEDIUM/LOW/UNLIKELY)
- [ ] Cited specific MPEP sections and case law
- [ ] Token budget <80% (saved tokens for follow-up questions)

---

## ERROR HANDLING

**If application not found:**
1. Verify application number format (e.g., "16/123,456" → "16123456")
2. Try searching by patent number if granted
3. Try searching by inventor name or assignee
4. Inform user and request correct application identifier

**If documents unavailable:**
1. Note which documents are missing in analysis
2. Recommend alternative sources (PAIR, etc.)
3. Proceed with available information
4. Flag gaps in report's "Limitations" section

**If Pinecone tools not available:**
1. Proceed without MPEP research (use general knowledge)
2. Recommend user install Pinecone Assistant or RAG MCP
3. Note limitation in final report
4. Suggest manual MPEP research for key sections

**If PTAB tools not available:**
1. Recommend manual PTAB search at https://ptab.uspto.gov/
2. Note limitation in final report
3. Proceed with PFW-based analysis only

---

## EXAMPLE WORKFLOW

User: "Analyze patent 10,123,456 for invalidity defense. We're being sued and need to assess our options."

Assistant Response:

I'll conduct a comprehensive patent invalidity analysis for U.S. Patent 10,123,456. Let me systematically analyze the patent for defense vulnerabilities using the USPTO Patent File Wrapper (PFW), PTAB, and Pinecone knowledge base MCPs.

---

### Step 1: Initial Application Review (Ultra-Minimal Verification)

First, let me verify the patent exists with minimal context usage:

```python
pfw_search_applications_minimal(
    query='patentNumber:"10123456"',
    fields=['applicationNumberText', 'patentNumber', 'inventionTitle'],
    limit=1
)
```

**Response Analysis (Ultra-Minimal):**
- Application Number: 15/987,654
- Patent Number: 10,123,456
- Title: "System and Method for Biometric Authentication in Wireless Networks"

**Decision:** Patent found. Proceed to Step 2 for detailed metadata.

---

### Step 2: Detailed Application Analysis (Balanced Fields)

Now let me get comprehensive metadata including prosecution history:

```python
pfw_search_applications_balanced(
    query='applicationNumberText:"15987654"',
    limit=1
)
```

**Key Findings:**
- **Continuity:** This is a continuation of Application 14/567,890 (filed Nov 15, 2016)
- **Prosecution Duration:** 18 months from filing to grant
- **Art Unit:** 2439 (Communications/Networking)
- **Examiner:** Jane Doe
- **Related Applications:** 2 divisionals also granted (10,234,567 and 10,345,678)

**Token Optimization - Document List Retrieval:**

```python
pfw_get_application_documents(
    application_number='15987654',
    include_raw_xml=False  # CRITICAL: Saves 50K+ tokens
)
```

**Document Analysis (from structured list, NOT raw XML):**
- Office Actions: 2 (CTNF, CTFR)
- Responses: 2
- Notice of Allowance: 1 (March 15, 2019)
- Issue Notification: 1
- IDS Filings: 3

**Critical Documents Identified:**
- NOA-2019-03-15 (examiner's final reasoning)
- RESP-2019-02-10 (applicant's arguments and amendments)
- OA-2018-11-20 (examiner's rejections)

---

### Step 3: Prior Art and Legal Research

**3A. MPEP and Case Law Research (Pinecone Knowledge Base)**

Before retrieving expensive prosecution documents, let me research the legal framework for biometric authentication patents:

**Pinecone Assistant MCP Example:**

```python
assistant_context(
    query='biometric authentication wireless network patent eligibility 35 USC 101 Alice abstract idea',
    top_k=5,
    snippet_size=2048,
    temperature=0.3
)
```

**Pinecone RAG MCP Alternative:**

```python
semantic_search(
    query='biometric authentication wireless network patent eligibility 35 USC 101 Alice abstract idea',
    topK=5,
    metadataFilter={'document_type': 'MPEP'},
    rerankerTopN=3
)
```

**RAG Results Analysis:**

**Result 1** (Score: 0.9234) - MPEP § 2106.04(a)(2)
Section: MPEP § 2106.04(a)(2) - Abstract Ideas - Mental Processes
Content: "Concepts performed in the human mind (including observation, evaluation, judgment, opinion) are abstract ideas... Authentication methods that merely use generic computer components to perform conventional authentication steps may be abstract ideas..."

**Result 2** (Score: 0.8876) - MPEP § 2106.05(a)
Section: MPEP § 2106.05(a) - Eligibility Step 2B - Improvements to Technology
Content: "A claim that improves computer or network technology is not directed to an abstract idea. Examples include: improving network security by adding encryption layers, reducing network latency through novel routing..."

**Result 3** (Score: 0.8654) - Case Law - Alice Corp. v. CLS Bank
Content: "Supreme Court in Alice held that implementing abstract idea on generic computer is insufficient for patent eligibility. Must recite 'significantly more' than the abstract idea itself..."

**Analysis:** Biometric authentication on wireless networks is vulnerable to § 101 Alice challenges UNLESS claims recite specific technological improvements beyond generic authentication.

**3B. Strategic Multi-Domain Research**

Let me research multiple vulnerability domains simultaneously:

**Pinecone Assistant MCP Example:**

```python
assistant_strategic_multi_search_context(
    query='biometric authentication wireless network invalidity',
    domain='software_ai_technology',
    top_k=3,
    snippet_size=2048,
    max_searches=2,
    temperature=0.3
)
```

**Pinecone RAG MCP Alternative:**

```python
strategic_multi_search(
    technology='biometric authentication wireless network invalidity',
    topK=3,
    metadataFilter={'source': 'Manual of Patent Examining Procedure'},
    rerankerTopN=2
)
```

**Strategic Search Results:**

**Pattern 1: Subject Matter Eligibility**
- MPEP § 2106 - Patent Subject Matter Eligibility
- Alice/Mayo framework for software patents
- **Vulnerability Identified:** § 101 abstract idea rejection risk

**Pattern 2: Indefiniteness**
- MPEP § 2173.05(b) - Relative Terms
- Nautilus reasonable certainty standard
- **Vulnerability Identified:** Terms like "proximity," "secure," "local" may lack clear boundaries

**Pattern 3: Obviousness**
- MPEP § 2143 - KSR motivation to combine
- § 103 analysis for wireless authentication systems
- **Vulnerability Identified:** Combining known biometric methods with known wireless protocols may be obvious

**Primary Vulnerability Assessment:**
1. **§ 101 Eligibility** - HIGH RISK (software/authentication method)
2. **§ 112(b) Indefiniteness** - MEDIUM RISK (relative terms in claims)
3. **§ 103 Obviousness** - MEDIUM RISK (combination of known elements)

**3C. Deep-Dive § 101 Research**

Based on Step 3B findings, I'll focus on § 101 eligibility as primary vulnerability:

**Pinecone Assistant MCP:**

```python
assistant_context(
    query='wireless biometric authentication Alice Mayo technological improvement versus abstract idea MPEP 2106',
    top_k=5,
    snippet_size=2048,
    temperature=0.3
)
```

**Pinecone RAG MCP:**

```python
semantic_search(
    query='wireless biometric authentication Alice Mayo technological improvement versus abstract idea MPEP 2106',
    topK=5,
    metadataFilter={'category': 'guidance'},
    rerankerTopN=2
)
```

**Detailed § 101 Guidance:**

From MPEP § 2106.05(a) - Improvements to Computer Technology:
"Authentication improvements that reduce computational overhead, improve security through novel encryption, or reduce network latency are technological improvements. Merely implementing known authentication on generic wireless hardware is NOT a technological improvement."

From Federal Circuit case law:
"Biometric authentication using conventional sensors and generic processors, without novel technical implementation, is abstract idea under Alice. See Secured Mail Solutions LLC v. Universal Wilde, Inc. (Fed. Cir. 2017)."

---

### Step 3.5: Opportunistic Deep-Dive Research (Token Budget Permits)

**Token Budget Check:** After Steps 1-3, approximately 42K tokens used. Remaining: ~148K tokens.

**Decision:** Execute additional deep-dive research on functional claiming vulnerabilities.

**Deep-Dive #1: Functional Claiming Precedents**

```python
semantic_search(
    query='configured to operable to functional claiming § 112 paragraph f means plus function structure',
    topK=5,
    rerankerTopN=2,
    metadataFilter={'document_type': 'MPEP'}
)
```

**Results:**
- MPEP § 2181 - § 112(f) invoked when claim recites "module configured to" without sufficient structure
- Williamson v. Citrix (Fed. Cir. 2015): Generic terms like "module," "mechanism," "device" + functional language invoke § 112(f)
- If specification lacks corresponding structure → claim indefinite under § 112(b)

**Deep-Dive #2: Software Patent Invalidity Patterns**

```python
semantic_search(
    query='software wireless patent invalidity § 101 § 112 common vulnerabilities Federal Circuit',
    topK=5,
    rerankerTopN=2,
    metadataFilter={'category': 'case_law'}
)
```

**Results:**
- Software patents have 60%+ invalidity rate at PTAB under § 101 Alice
- Wireless communication patents often vulnerable to § 112(b) indefiniteness for terms like "proximity zone," "secure connection"
- Successful defense strategies: narrow claim construction focusing on specific technical implementations

---

### Step 4: Prosecution History Review

**4A. Document Metadata Analysis**

From Step 2 document list, I identified key prosecution events:
- Nov 20, 2018: Non-Final Office Action (CTNF) - § 101 and § 103 rejections
- Feb 10, 2019: Applicant Response - Claim amendments + arguments
- Mar 15, 2019: Notice of Allowance

**Pattern:** Examiner initially rejected under § 101 (abstract idea) and § 103 (obviousness), but allowed after amendments. This indicates prosecution history estoppel opportunities.

**4B. Notice of Allowance Retrieval (Highest Value Document)**

```python
pfw_get_document_by_id(
    application_number='15987654',
    document_id='NOA-2019-03-15',
    include_raw_xml=False  # Token-optimized
)
```

**NOA Extract (Key Passages):**

"Claims 1-10 are allowed. The prior art of record (Smith US 8,234,567 and Jones US 8,345,678) teaches biometric authentication and wireless communication separately, but does not teach the specific **proximity-based biometric authentication zone** recited in applicant's amended claims.

Applicant's amendment limiting the claims to authentication **within a local proximity zone using secured biometric information stored on the device** distinguishes the prior art, which teaches server-based authentication.

The examiner finds that the combination of references would not have been obvious because the prior art teaches away from local device storage, preferring centralized authentication servers for security."

**Critical Findings:**
1. **Prosecution History Estoppel:** Applicant narrowed claims to "proximity-based" + "local" storage to overcome prior art
2. **Examiner's Interpretation:** "Local proximity zone" = authentication on device, NOT server-based
3. **Distinguishing Feature:** Local device storage vs. server authentication

**4C. PTAB Proceedings Check**

```python
ptab_search_trials(
    patent_number='10123456',
    limit=10
)
```

**Result:** No PTAB proceedings found for this patent.

**Strategic Implication:** Patent has not been tested at PTAB. § 101 and § 112(b) challenges may be strong because examiner may have missed these issues during prosecution.

---

### Step 5: Claims Extraction (Token-Optimized)

Now that I understand the legal vulnerabilities, let me extract the exact claim language:

```python
pfw_get_patent_or_application_xml(
    identifier='10123456',
    include_fields=['claims'],
    include_raw_xml=False  # CRITICAL: 97% token reduction
)
```

**Independent Claim 1 (Verbatim):**

"1. A method for biometric authentication in a wireless network, comprising:
   - establishing a **proximity zone** around a wireless access point;
   - detecting a user device entering the proximity zone;
   - requesting **local, secured biometric information** from the user device;
   - authenticating the user based on the local, secured biometric information; and
   - granting network access to the user device upon successful authentication."

**Claim Analysis:**

**§ 112(b) Indefiniteness Vulnerabilities:**
1. **"proximity zone"** - What distance? 1 meter? 10 meters? 100 meters? No objective boundary.
2. **"local, secured biometric information"** - What makes it "local" vs "remote"? What security standard qualifies as "secured"?

**§ 101 Eligibility Vulnerabilities:**
1. Abstract idea: Authenticating users (conventional authentication method)
2. Generic computer implementation: Wireless access point + user device (conventional hardware)
3. No technological improvement recited: Claims don't specify HOW authentication is improved technically

**§ 112(f) Functional Claiming Vulnerabilities:**
1. "establishing a proximity zone" - functional language without structure
2. "requesting... secured biometric information" - function without implementation details

---

### Step 6: Specification Review (Targeted - § 112 Analysis)

Because § 112(b) indefiniteness is a strong vulnerability, I need to check if specification defines the ambiguous terms:

```python
pfw_get_patent_or_application_xml(
    identifier='10123456',
    include_fields=['description', 'abstract'],
    include_raw_xml=False  # CRITICAL: 94% token reduction
)
```

**Specification Extract:**

"...In one embodiment, the proximity zone may be defined as an area within approximately 1-100 meters of the wireless access point, depending on signal strength and network configuration...

The biometric information is stored locally on the user device in a secure storage area, which may include encrypted storage, hardware security modules, or trusted execution environments..."

**§ 112(b) Analysis:**

**"Proximity zone" definition:**
- Specification provides range: "1-100 meters"
- Qualifier: "depending on signal strength and network configuration"
- **Problem:** Massive range (100x variation) + conditional qualifier = indefinite under Nautilus
- **POSITA cannot determine with reasonable certainty** what distance qualifies

**"Local, secured biometric information" definition:**
- "Local" defined as "stored on device" (vs remote server)
- "Secured" defined as "may include encrypted storage, HSMs, or TEEs"
- **Problem:** "May include" language = non-limiting examples, not requirements
- **POSITA cannot determine what level of security is required**

**§ 112(b) Conclusion:** Strong indefiniteness arguments for both terms. Specification fails to provide objective boundaries.

---

### Step 7: Citations Analysis (§ 103 Obviousness)

Let me check the prior art cited during prosecution:

```python
uspto_enriched_citations:search_citations_minimal(
    application_number='15987654',
    examiner_cited=True,
    category_code='X',
    fields=['citedDocumentIdentifier', 'citationCategoryCode', 'passageLocationText'],
    rows=20
)
```

**Category X Citations (Basis for Rejection):**

**Reference A: Smith US 8,234,567**
- Teaches: Biometric authentication using fingerprint sensors
- Teaches: User device storage of biometric templates
- Does NOT teach: Wireless network integration, proximity-based triggering

**Reference B: Jones US 8,345,678**
- Teaches: Proximity-based wireless network access control
- Teaches: Detecting devices entering wireless range
- Does NOT teach: Biometric authentication, local storage

**§ 103 Obviousness Analysis:**

**Combination:** Smith + Jones

**Elements Covered:**
- Smith teaches: Biometric authentication (claim element 3) + local storage (claim element 3)
- Jones teaches: Proximity zone (claim element 1) + wireless access point (claim element 1)

**KSR Motivation to Combine:**
- **Problem:** Network security requires both proximity AND biometric authentication
- **Motivation:** Combining proximity control (Jones) with biometric authentication (Smith) is obvious to improve security
- **MPEP § 2143.01(VII):** "Combining known elements according to known methods to yield predictable results" = obvious

**Examiner's Distinguishment (from NOA):**
- Examiner found no motivation because "prior art teaches server-based authentication, not local device storage"
- **Counter-Argument:** Smith expressly teaches local device storage of biometric templates (Col. 7:12-25)
- **Examiner Error:** Missed that Smith teaches the exact "local storage" limitation

**§ 103 Conclusion:** Strong obviousness argument. Examiner's allowance reasoning is flawed.

---

### FINAL ANALYSIS: Comprehensive Defense Strategy

Based on my systematic analysis using PFW, PTAB, and Pinecone MCPs, here is the comprehensive invalidity defense strategy:

---

## EXECUTIVE SUMMARY

**Patent:** U.S. Patent 10,123,456 - "System and Method for Biometric Authentication in Wireless Networks"

**Analysis Date:** [Current Date]

**Invalidity Assessment:** VERY HIGH likelihood of invalidation under § 101, § 112(b), and § 103

---

### TOP 3 INVALIDITY VULNERABILITIES (Ranked by Strength)

**1. § 112(b) INDEFINITENESS - "Proximity Zone"**

**Strength:** VERY HIGH

**Legal Basis:** Nautilus, Inc. v. Biosig Instruments, Inc., 572 U.S. 898 (2014) - Claims must provide "reasonable certainty" to POSITA about scope.

**Evidence:**
- Claim term: "proximity zone" lacks objective boundaries
- Specification defines as "1-100 meters depending on signal strength and configuration" (100x variation)
- MPEP § 2173.05(b): Relative terms require objective anchors or they are indefinite
- POSITA cannot determine with reasonable certainty what distance qualifies as "proximity"

**Claims Affected:** 1, 3, 5-10 (all dependent claims incorporating "proximity zone")

**Litigation Strategy:**
- Lead argument in motion to dismiss or summary judgment
- Expert declaration: POSITA testimony on term ambiguity
- Claim construction brief: Argue term indefinite under Nautilus
- Alternative: If court attempts to construe narrowly, argue construction excludes accused product

**2. § 101 ELIGIBILITY - Abstract Idea (Alice/Mayo)**

**Strength:** HIGH

**Legal Basis:** Alice Corp. v. CLS Bank Int'l, 573 U.S. 208 (2014) - Generic computer implementation of abstract idea is ineligible.

**Evidence:**
- **Step 1:** Claims directed to abstract idea of "authenticating users" (conventional security method)
- **Step 2A:** No technological improvement recited; claims use generic wireless hardware
- **Step 2B:** No inventive concept; merely applying known biometric authentication to known wireless networks
- MPEP § 2106.05(a): "Technological improvement" requires novel technical implementation, not just new application
- Analogous cases: Secured Mail Solutions v. Universal Wilde (Fed. Cir. 2017) - biometric authentication on generic computer is abstract

**Claims Affected:** All claims 1-20

**Litigation Strategy:**
- File motion to dismiss under § 101 (12(b)(6) or 12(c))
- Pinecone research provided extensive MPEP § 2106 guidance and Federal Circuit precedents
- Argue claims lack "significantly more" than abstract idea
- No need for claim construction - eligibility decided on face of claims

**3. § 103 OBVIOUSNESS - Smith + Jones Combination**

**Strength:** HIGH

**Legal Basis:** KSR Int'l Co. v. Teleflex Inc., 550 U.S. 398 (2007) - Combining known elements to yield predictable results is obvious.

**Evidence:**
- **Primary Reference (Smith US 8,234,567):** Teaches biometric authentication + local device storage
- **Secondary Reference (Jones US 8,345,678):** Teaches proximity-based wireless access control
- **Combination:** Smith + Jones covers all claim limitations
- **KSR Motivation:** Obvious to combine proximity control with biometric authentication to improve network security (predictable use of prior art elements)
- **Examiner Error:** NOA states prior art doesn't teach "local storage," but Smith Col. 7:12-25 expressly teaches this

**Claims Affected:** 1-20

**Litigation Strategy:**
- File IPR petition at PTAB (if timing permits) OR invalidity counterclaim in district court
- Expert declaration: PHOSITA testimony on motivation to combine
- Claim charts mapping Smith + Jones to claim elements
- Leverage examiner's flawed allowance reasoning (missed Smith's local storage teaching)

---

### CLAIM CONSTRUCTION DEFENSE STRATEGY

**Primary Construction Target:** "Proximity Zone"

**Proposed Narrow Construction:** "An area within exactly 1 meter of the wireless access point"

**Intrinsic Evidence Support:**
1. **Specification:** Provides range of "1-100 meters" - construe narrowly to lower bound
2. **Prosecution History:** Applicant distinguished prior art by arguing claims require "proximity-based" authentication (not long-range) - estoppel limits to narrow distance
3. **Purpose:** Claim purpose is immediate proximity authentication - supports narrow construction

**Non-Infringement Impact:**
- If accused product operates beyond 1 meter, falls outside claim scope
- Alternative: Argue term indefinite if court cannot determine precise boundary

**Secondary Construction Target:** "Local, Secured Biometric Information"

**Proposed Narrow Construction:** "Biometric information stored exclusively on the user device using hardware security module encryption"

**Intrinsic Evidence Support:**
1. **Specification:** Examples include "hardware security modules" as highest security level
2. **Prosecution History:** Applicant overcame § 103 rejection by arguing "local device storage" vs "server-based" (estoppel precludes any server communication)
3. **Ordinary Meaning:** "Secured" to POSITA implies highest security standard (HSM), not merely encrypted storage

**Non-Infringement Impact:**
- If accused product uses cloud-based biometric storage or software-only encryption, falls outside claim scope

---

### PROSECUTION HISTORY ESTOPPEL OPPORTUNITIES

**Amendment 1 (Feb 10, 2019):**

**Original Claim 1:** "A method for biometric authentication in a network..."

**Amended Claim 1:** "A method for biometric authentication in a wireless network, comprising... **proximity zone**... **local, secured biometric information**..."

**Reason for Amendment:** Overcome § 103 rejection based on Smith + Jones prior art

**Applicant's Arguments (from Response):**
- "The prior art teaches server-based authentication, whereas applicant's claims require **local device storage** of biometric information"
- "The prior art does not teach **proximity-based triggering** of authentication as claimed"

**Festo Estoppel Analysis:**

1. **Amendment narrowed claim scope:** YES - Added "proximity zone" and "local, secured" limitations
2. **Amendment related to patentability:** YES - Overcame § 103 rejection
3. **Presumptive bar to doctrine of equivalents:** YES - Estoppel applies to added limitations

**Litigation Impact:**
- Accused product that uses server-based authentication (even partially) is outside literal scope
- Doctrine of equivalents barred by Festo for "local" vs "remote" storage
- Accused product that uses non-proximity-based authentication (e.g., long-range) is outside literal scope

---

### RECOMMENDED LITIGATION STRATEGY

**Phase 1: Early Motion Practice (Months 1-4)**

**Motion 1: Motion to Dismiss under § 101 (Rule 12(b)(6))**
- File within 60 days of complaint
- Argue claims facially directed to abstract idea with no technological improvement
- No claim construction required (eligibility decided on face of claims)
- **Likelihood of Success:** HIGH
- **Strategic Value:** If successful, case dismissed with prejudice; if denied, establishes strong § 101 record for appeal

**Motion 2: Motion to Dismiss for Indefiniteness under § 112(b)**
- File if § 101 motion denied
- Argue "proximity zone" fails Nautilus reasonable certainty standard
- Specification's 100x range (1-100 meters) is facially indefinite
- **Likelihood of Success:** HIGH
- **Strategic Value:** Even if denied, forces narrow claim construction favorable to defendant

**Phase 2: Claim Construction (Months 5-8)**

**Markman Briefing Strategy:**
- Propose narrow constructions for "proximity zone" (1 meter) and "local, secured" (HSM-encrypted device-only storage)
- Leverage prosecution history estoppel (applicant's arguments distinguish prior art)
- Expert declaration: POSITA testimony on ordinary meaning and specification examples
- **Objective:** Narrow claims to exclude accused product OR establish indefiniteness

**Phase 3: Summary Judgment (Months 9-12)**

**Invalidity Summary Judgment Motion:**
- **Ground 1:** § 103 obviousness (Smith + Jones combination)
- **Ground 2:** § 112(b) indefiniteness (if claim construction doesn't resolve)
- Expert declarations: PHOSITA motivation to combine, claim term ambiguity
- Claim charts: Element-by-element mapping to prior art
- **Likelihood of Success:** MEDIUM

**Non-Infringement Summary Judgment Motion (Alternative):**
- Based on narrow claim construction from Markman hearing
- Accused product falls outside narrowly construed claim scope
- Prosecution history estoppel bars doctrine of equivalents

**Phase 4: PTAB Parallel Proceeding (Optional)**

**IPR Petition:**
- File within 1 year of complaint service
- Grounds: § 103 obviousness (Smith + Jones)
- **Advantages:** Lower burden of proof (preponderance), BRI claim construction, no presumption of validity
- **Disadvantages:** Estoppel from non-instituted grounds, costs $400K+
- **Recommendation:** File IPR if district court denies early § 101/§112(b) motions

---

### DISCOVERY PRIORITIES

**Priority 1: Prosecution File History**
- Request all office action responses, amendments, and examiner interview notes
- **Purpose:** Identify additional narrowing statements for estoppel; find inconsistent claim interpretations

**Priority 2: Inventor/Applicant Depositions**
- Depose inventors on: definition of "proximity zone," intended claim scope, knowledge of prior art
- **Purpose:** Lock in narrow claim constructions; establish lack of enablement for full scope

**Priority 3: Prior Art Search**
- Search: IEEE databases for wireless authentication + biometric authentication literature (2010-2018)
- Search: Patent databases for additional anticipating references
- **Purpose:** Identify stronger prior art combinations; build § 102/§103 case

**Priority 4: Expert Retention**
- **Technical Expert:** POSITA-level expertise in wireless security + biometric authentication
- **Qualifications:** PhD in computer science, 15+ years wireless networking experience
- **Testimony:** Claim construction (POSITA understanding), indefiniteness (reasonable certainty), obviousness (motivation to combine, secondary considerations)

---

### ESTIMATED COSTS & TIMELINE

**Discovery (Months 1-8):**
- Prosecution file review: $15,000
- Expert retention + initial opinions: $50,000
- Prior art search: $25,000
- Depositions (2 inventors): $20,000
- **Subtotal:** $110,000

**Motion Practice (Months 2-12):**
- § 101 Motion to Dismiss: $40,000
- Claim Construction briefing: $75,000
- Summary Judgment (invalidity + non-infringement): $100,000
- **Subtotal:** $215,000

**PTAB (Optional, Months 6-24):**
- IPR petition preparation: $150,000
- IPR prosecution: $250,000
- **Subtotal:** $400,000

**Total Estimated Defense Costs (District Court Only):** $325,000
**Total Estimated Defense Costs (District Court + PTAB):** $725,000

**Timeline:**
- § 101 Motion (Month 2): If granted, case dismissed
- Claim Construction (Month 8): Narrow constructions support non-infringement
- Summary Judgment (Month 12): Invalidity or non-infringement ruling

---

### SETTLEMENT LEVERAGE ASSESSMENT

**Strength of Defense:** VERY STRONG

**Key Leverage Points:**
1. **§ 101 Eligibility Challenge:** HIGH likelihood - case-dispositive if successful
2. **§ 112(b) Indefiniteness:** VERY HIGH likelihood - invalidates all claims
3. **§ 103 Obviousness:** HIGH likelihood - examiner error in allowance
4. **Prosecution History Estoppel:** Strong limitations from amendments - narrows claim scope significantly

**Recommended Settlement Strategy:**

**Phase 1 (Pre-Motion to Dismiss):**
- Demand: Dismiss with prejudice (no payment)
- Rationale: § 101 abstract idea is case-dispositive; plaintiff faces likely dismissal at motion stage
- **Leverage:** Avoid motion practice costs ($40K+) and bad precedent if motion granted

**Phase 2 (Post-Motion Denial, Pre-Claim Construction):**
- Offer: Covenant not to sue for $50,000 (nuisance value)
- Rationale: § 112(b) indefiniteness + § 103 obviousness remain strong; claim construction will narrow scope
- **Leverage:** Avoid claim construction costs ($75K+) and likely narrow construction

**Phase 3 (Post-Claim Construction, Pre-Trial):**
- Offer: Settlement for $100,000-$250,000 (depending on claim construction outcome)
- Rationale: If claims construed narrowly, non-infringement likely; if indefinite, claims invalid
- **Leverage:** Avoid trial costs ($500K+) and likely invalidity/non-infringement verdict

**Estimated Settlement Value:** $50,000-$250,000 (vs. $2M+ potential damages if losing at trial)

**Recommendation:** Pursue aggressive early motion practice (§ 101, § 112(b)) to maximize settlement leverage before substantial discovery costs incurred.

---

## RESEARCH CITATIONS & SOURCES

**Pinecone RAG MCP Queries Executed:**

1. **Strategic Multi-Search (Step 3B):**
   - Technology: "biometric authentication wireless network invalidity"
   - Results: 3 search patterns executed (§ 101, § 112, § 103)
   - Impact: Identified primary vulnerability as § 101 Alice/Mayo + § 112(b) indefiniteness

2. **§ 101 Deep-Dive Research (Step 3C):**
   - Query: "wireless biometric authentication Alice Mayo technological improvement versus abstract idea MPEP 2106"
   - Results: MPEP § 2106.04(a), § 2106.05(a), Federal Circuit case law (Secured Mail Solutions)
   - Impact: Established legal framework for § 101 eligibility challenge

3. **Functional Claiming Deep-Dive (Step 3.5):**
   - Query: "configured to operable to functional claiming § 112 paragraph f means plus function structure"
   - Results: MPEP § 2181, Williamson v. Citrix precedent
   - Impact: Identified additional § 112(f) indefiniteness arguments

**Prosecution Documents Reviewed:**
- Notice of Allowance (NOA-2019-03-15): Examiner's allowance reasoning, claim interpretation
- Application documentBag: Timeline analysis, amendment patterns

**PTAB Proceedings:** None found for Patent 10,123,456

**Citations Analyzed:**
- Smith US 8,234,567 (Category X - basis for § 103 rejection)
- Jones US 8,345,678 (Category X - basis for § 103 rejection)

**Specification Retrieved:** Yes (for § 112(b) indefiniteness analysis of "proximity zone" and "local, secured" definitions)

---

## QUALITY ASSURANCE VERIFICATION

✅ Patent claims extracted efficiently (Step 1 - include_raw_xml=False)
✅ Strategic multi-search executed (Step 3B - identified § 101, § 112(b), § 103 vulnerabilities)
✅ Targeted legal research completed (Step 3C - § 101 deep-dive)
✅ Opportunistic deep-dive search executed (Step 3.5 - functional claiming precedents)
✅ Prosecution history reviewed (Step 4B - NOA analysis, estoppel findings)
✅ PTAB proceedings checked (Step 4C - none found)
✅ Specification retrieved for § 112(b) analysis (Step 6 - include_raw_xml=False)
✅ Citations analyzed for § 103 obviousness (Step 7 - Smith + Jones combination)
✅ RAG citations integrated throughout analysis (10+ Pinecone results cited)
✅ Specific claim language cited (Claim 1 verbatim with element analysis)
✅ Specification passages referenced (Col. 7:12-25 for local storage teaching)
✅ Analysis exceeds 2,000 words with comprehensive legal rigor
✅ Litigation recommendations prioritized (HIGH/MEDIUM/LOW likelihood rankings)
✅ Token budget managed efficiently (~75K total vs 150K+ in unoptimized workflow)

---

**END OF COMPREHENSIVE PATENT INVALIDITY DEFENSE ANALYSIS**

"""

@mcp.prompt(
    name="patent_invalidity_analysis_defense_Pinecone_PTAB_FPD_Citations",
    description="Comprehensive patent invalidity defense analysis with multi-MCP integration: PFW (prosecution history) + PTAB (trials & decisions) + FPD (examiner patterns) + Citations (prior art) + Pinecone (MPEP/case law). Auto-detects Pinecone RAG configuration for intelligent token budgeting. Ultra-minimal Step 1 reduces context waste. At least ONE identifier required (application_number, patent_number, or title_keywords)."
)
async def patent_invalidity_analysis_defense_Pinecone_PTAB_FPD_Citations_prompt(
    application_number: str = "",
    patent_number: str = "",
    title_keywords: str = ""
) -> str:
    """
    Patent invalidity analysis and defense strategy with multi-MCP integration.

    Integrates 5 MCPs: PFW, PTAB, FPD, Citations, Pinecone
    Identifiers (at least ONE required): application_number, patent_number, or title_keywords
    Supports both Pinecone Assistant MCP and Pinecone RAG MCP
    """

    return PATENT_INVALIDITY_ANALYSIS_DEFENSE_PINECONE_PTAB_FPD_CITATIONS.replace(
        "{patent_number}", patent_number
    ).replace(
        "{application_number}", application_number
    ).replace(
        "{title_keywords}", title_keywords
    )
