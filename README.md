# USPTO Patent File Wrapper MCP Server

A high-performance Model Context Protocol (MCP) server for the USPTO Patent File Wrapper API with token saving **context reduction** capabilities, smart field mapping, and **secure browser-accessible downloads**.

[![Platform Support](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![API](https://img.shields.io/badge/API-USPTO%20Patent%20File%20Wrapper-green.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[📥 Installation Guide](INSTALL.md)** | Complete cross-platform setup with automated scripts |
| **[🔑 API Key Guide](API_KEY_GUIDE.md)** | Step-by-step instructions for obtaining USPTO and Mistral API keys with screenshots |
| **[📖 Usage Examples](USAGE_EXAMPLES.md)** | Function examples, workflows, and integration patterns |
| **[🎯 Prompt Templates](PROMPTS.md)** | Detailed guide to sophisticated prompt templates for legal & research workflows |
| **[⚙️ Field Customization](CUSTOMIZATION.md)** | Comprehensive guidance on customizing field sets for the minimal and balanced tools |
| **[🔒 Security Guidelines](SECURITY_GUIDELINES.md)** | Comprehensive security best practices |
| **[🛡️ Security Scanning](SECURITY_SCANNING.md)** | Automated secret detection and prompt injection protection guide |
| **[🧪 Testing Guide](tests/README.md)** | Test suite documentation and API key setup |
| **[⚖️ License](LICENSE)** | MIT License terms and conditions |

##  ⚡Quick Start

### Windows Install

**Run PowerShell as Administrator**, then:

```powershell
# Navigate to your user profile
cd $env:USERPROFILE

# If git is installed:
git clone https://github.com/john-walkoe/uspto_pfw_mcp.git
cd uspto_pfw_mcp

# If git is NOT installed:
# Download and extract the repository to C:\Users\YOUR_USERNAME\uspto_pfw_mcp
# Then navigate to the folder:
# cd C:\Users\YOUR_USERNAME\uspto_pfw_mcp

# The script detects if uv is installed and if it is not it will install uv - https://docs.astral.sh/uv

# Run setup script (sets execution policy for this session only):
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process
.\deploy\windows_setup.ps1

# View INSTALL.md for sample script output.
# Close Powershell Window.
# If choose option to "configure Claude Desktop integration" during the script then restart Claude Desktop
```

The PowerShell script will:

- ✅ Check for and auto-install uv (via winget or PowerShell script)
- ✅ Install dependencies and create executable
- ✅ Prompt for USPTO API key (required) and Mistral API key (optional) or Detect if you had installed the developer's other USPTO MCPs and ask if want to use existing keys from those installation.
- 🔒 **If entering in API keys, the script will automatically store API keys securely using Windows DPAPI encryption**
- ✅ Ask if you want Claude Desktop integration configured
- 🔒 **Offer secure configuration method (recommended) or traditional method (API keys in plain text in the MCP JSON file)**
- ✅ Backups and then automatically merge with existing Claude Desktop config (preserves other MCP servers)
- ✅ Provide installation summary and next steps

### Claude Desktop Configuration - Manual installs

```json
{
  "mcpServers": {
    "uspto_pfw": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/Users/YOUR_USERNAME/uspto_pfw_mcp",
        "run",
        "patent-filewrapper-mcp"
      ],
      "env": {
        "USPTO_API_KEY": "your_actual_USPTO_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL",
        "PROXY_PORT": "8080"
      }
    }
  }
}
```

**For detailed installation, manual setup, and troubleshooting**, see **[INSTALL.md](./INSTALL.md)**

##  🎯Key Benefits

- **🔒 Secure API Key Storage** - Windows DPAPI encryption for API keys (secure storage option during setup)
- **🗺️ Smart Field Mapping** - Use simple names like `"inventionTitle"` instead of `"applicationMetaData.inventionTitle"`
- **⚙️ User-Customizable Fields** - Configure field sets through YAML without code changes
- **🎯 Context Reduction** - Get focused responses instead of massive API dumps
- **🔍 Multi-Strategy Search** - Comprehensive, fuzzy, and exact inventor searches
- **⚡ Convenience Parameters** - Attorney-friendly search parameters (art_unit, examiner_name, applicant_name, etc.) eliminate need for complex query syntax
- **🏛️ Professional-Grade Fields** - additional fields for patent prosecution, international work, and analytics

- **🔄 Circuit Breaker Resilience** - Automatic retry logic with exponential backoff prevents API failures
- **📊 Progressive Disclosure** - context reduction through optimized minimal → balanced → detailed workflows
- **🔗 Cross-MCP Integration** - Purpose-built for multi-database patent research with Developer's other PTAB, FPD, Citations, and Pinecone (Assistant or RAG) MCPs
  - **🆕 Centralized Document Hub** - PFW proxy now serves as unified download infrastructure for all USPTO MCPs (accepts FPD document registrations)
- **📝 Attorney-Focused Prompt Templates** - 10+ sophisticated workflow templates for legal research, litigation, and due diligence

- **✨ Intelligent Document Extraction** - Auto-optimized hybrid extraction (free PyPDF2 → Mistral OCR fallback) + secure browser downloads
- **🌐 Secure Browser Downloads** - Click proxy URLs to download PDFs directly while keeping API keys secure
- **👁️ Advanced OCR Capabilities** - Extract text for LLM use from scanned PDFs, formulas, diagrams, and complex layouts
- **📁 Document Bag Integration** - Full prosecution document access (Abstract, Claims, NOA, etc.) alongside XML content analysis of patents/applications
- **💰 Mistral OCR Cost Transparency** - Real-time cost calculation (~$0.001-$0.003 per patent document) when using Mistral OCR
- **🚀 High Performance** - Optimized for AI workflows with targeted field selection + retry logic with exponential backoff
- **🛡️ Production Ready** - Enhanced error handling, structured logging with request IDs, and comprehensive security guidelines
- **💻 Cross-Platform** - Works seamlessly on Linux and Windows
- **📋 Complete API Coverage** - All USPTO Patent File Wrapper endpoints supported

### Workflow Design - All preformed by the LLM with Minimal User Guidance

**User Requests the following:**

- *"Look for patents about LCD TV technology related to QLED"*
- *"Show me Apple's patent applications filed in 2024"*
- *"Get me PDFs download links for the patent "Integrated delivery and protection device for digital objects"*
- *"I need you to look at the patent details of 7971071 and summarize it for me"*
- *"Research this IPR case IPR2025-00562 and compare it to the original prosecution"* -* Requires that the USPTO Patent Trial and Appeal Board (PTAB) be installed - [uspto_ptab_mcp](https://github.com/john-walkoe/uspto_ptab_mcp.git) and also recommended to ask LLM to perform a pfw_get_guidance tool call prior to this or any cross MCP prompt (see quick reference chart for section selection, additional details in [Usage Examples](USAGE_EXAMPLES.md))

**LLM Performs these steps:**

**Step 1: Discovery minimal** → **Step 2: Selection (and searches balanced - Optional)** → **Step 3: Content Analysis** → **Step 4 (Optional): Select additional prosecution documents for examination** → **Step 5 (Optional): Retrieve doc_id(s) of the selected from documentBag** → **Step 6 (Optional): Document Extraction for LLM use and/or Download Links of PDFs for user's use**

The field configuration supports an optimized research progression:

1. **Discovery searches minimal** return 20-50 applications efficiently without prosecution document bloat
2. **Selection (and searches balanced - Optional)** from the retrieved select likely application(s)/patent(s).  Optional balanced search(es) performed if needed in advanced workflows and/or USPTO PTAB (Patent Trial and Appeal Board) MCP cross workflows
3. **Content analysis** via XML retrieval for selected patents with structured data for LLM's use in analysis
4. **Select additional prosecution documents for examination** (Optional) e.g. Notice of Allowance, Applicant Citations (disclosed prior art), Examiner's Office Action Rejections, etc.
5. **Retrieve doc_id(s) of the selected from documentBag** (Optional) use get application documents tool to get the doc_id(s)
6. **Document Extraction for LLM use and/or Download Links of PDFs for user's use** (Optional) Document extraction via intelligent hybrid tool that auto-optimizes for cost and quality and Downloads of the documents as PDFs uses URLs from a HTTP proxy that obscures the USPTO's API key from chat history

##  🎯 Prompt Templates

This MCP server includes sophisticated AI-optimized prompt templates for complex patent workflows. For detailed documentation on all templates, features, and usage examples, see **[PROMPTS.md](PROMPTS.md)**.

### Quick Template Overview

| Category | Templates | Purpose |
|----------|-----------|---------|
| **Legal Analysis** | `/patent_search`, `/patent_explanation_for_attorneys`, `/patent_invalidity_analysis_defense_pinecone_PTAB` | Patent discovery, technical translation, defensive litigation |
| **Research & Prosecution** | `/art_unit_quality_assessment_FPD`, `/litigation_research_setup_PTAB_FPD`, `/technology_landscape_mapping_PTAB` | Examiner analysis, litigation prep, competitive intelligence |
| **Document Management** | `/complete_patent_package`, `/document_filtering_assistant`, `/inventor_portfolio_analysis` | Organized retrieval, smart filtering, portfolio mapping |

**Key Features Across All Templates:**
- **Enhanced Input Processing** - Flexible identifier support (patent numbers, application numbers, title keywords)
- **Smart Validation** - Automatic format detection and guidance
- **Cross-MCP Integration** - Seamless workflows with PTAB, FPD, Citations, and Pinecone MCPs
- **Context Optimization** - token reduction through progressive disclosure

##  📊Available Functions

### Search Functions (6 Focused Tools)
| Function (Display Name) | Context Reduction | Use Case |
|----------|------------------|----------|
| `pfw_search_applications` (Search applications custom) | Variable | Custom patent search with user-defined fields |
| `pfw_search_inventor` (Search inventor custom) | Variable | Smart inventor search with multiple strategies |
| `pfw_search_applications_minimal` (Search applications minimal) | typical 95-99% | Ultra-fast search (user-customizable minimal fields) |
| `pfw_search_applications_balanced` (Search applications balanced) | typical 85-95% | Key fields for discovery (no documentBag) |
| `pfw_search_inventor_minimal` (Search inventor minimal) | typical 95-99% | Ultra-fast inventor search (user-customizable) |
| `pfw_search_inventor_balanced` (Search inventor balanced) | typical 85-95% | Balanced inventor search (no documentBag) |

##  Search Strategies

### Inventor Search Strategies

- **`exact`** - Exact name matching only
- **`fuzzy`** - Multiple name format variations
- **`comprehensive`** - All strategies + partial matching

### Query Examples

```python
# Exact strategy
"applicationMetaData.inventorBag.inventorNameText:\"John Smith\""

# Comprehensive strategy
[
  "applicationMetaData.inventorBag.inventorNameText:\"John Smith\"",
  "applicationMetaData.inventorBag.inventorNameText:\"Smith, John\"",
  "applicationMetaData.inventorBag.inventorNameText:Smith*",
  "applicationMetaData.inventorBag.inventorNameText:*Smith*"
]
```

### Document Processing Functions

| Function (Display Name)                                      | Purpose                                                      | Requirements                                       |
| ------------------------------------------------------------ | ------------------------------------------------------------ | -------------------------------------------------- |
| `pfw_get_patent_or_application_xml` (Get patent or application xml) | Get structured XML content for patents/applications for LLM use with **91-99% token reduction** via `include_raw_xml=False` (recommended) and optional `include_fields` for selective extraction | USPTO_API_KEY                                      |
| `pfw_get_granted_patent_documents_download` (Get granted patent documents download) | Get complete granted patent package (Abstract, Drawings, Specification, Claims) in one call as secure browser-accessible download URLs | USPTO_API_KEY                                      |
| `pfw_get_application_documents` (Get application documents)  | Get prosecution documents' doc_id from documentBag with advanced filtering (document_code, direction_category) | USPTO_API_KEY                                      |
| `pfw_get_document_content` (PFW get document content with mistral ocr) | For LLM readability of non ORC scanned prosecution documents uses intelligent document extraction with cost transparency | USPTO_API_KEY (+ MISTRAL_API_KEY for OCR fallback) |
| `pfw_get_document_download` (PFW get document download)      | Secure browser-accessible download URLs                      | USPTO_API_KEY                                      |
| `pfw_get_guidance` (PFW get guidance)                        | **RECOMMENDED**: Context-efficient selective guidance sections (95-99% token reduction) | None                                               |

### Document Processing Capabilities

- **XML Content Tier (`pfw_get_patent_or_application_xml`)**: Structured patent/application content with **extreme context optimization**
  - **🎯 RECOMMENDED: `include_raw_xml=False`** - Removes ~50K token raw XML overhead (91% token reduction!)
  - **Selective field extraction (`include_fields`)** - Request only needed fields for 95-99% token reduction
  - **Default optimized response** - Returns abstract, claims, description (~5K tokens with `include_raw_xml=False`)
  - **Ultra-efficient modes** - Claims only (~1.5K tokens), Citations only (569 tokens), Inventors only (428 tokens)
  - **Intelligent patent-to-application mapping** - Automatically finds applications for granted patents
  - **Auto-detection** - Automatically determines patent vs application from identifier
  - **LLM-optimized parsing** - Extracts abstract, claims, inventors, classifications, citations on demand
  - **Dual XML support** - Handles both PTGRXML (granted patents) and APPXML (applications)
  - **Data limitation** - Only available for patents/applications filed after January 1, 2001
- **Complete Patent Package Tier (`pfw_get_granted_patent_documents_download`)**: Single-call granted patent retrieval
  - **All-in-one convenience** - Retrieves Abstract, Drawings, Specification, Claims in one call (replaces 4 separate calls)
  - **Intelligent component selection** - Auto-selects original vs. granted claims, optional drawings
  - **Organized download links** - Returns structured metadata with proxy download URLs for all components
  - **Perfect for attorneys** - Ideal for due diligence, litigation prep, portfolio review, hard copy generation
  - **Efficient workflow** - Use for 'give me the patent' requests instead of manual document hunting
  - **Graceful degradation** - Succeeds if 3+ of 4 components available, clearly indicates missing items
  - **LLM-optimized guidance** - Built-in formatting instructions for clickable markdown links
  - **Total page count** - Shows overall document size upfront for planning (typically 40-80 pages)
- **Prosecution Documents Tier (`pfw_get_application_documents`)**: - Targeted document access from documentBag
  - **Token-efficient design** - Get prosecution documents only when needed (no search bloat)
  - **Advanced filtering** - Filter by `document_code` (NOA, CTFR, 892, etc.) and `direction_category` (INCOMING/OUTGOING/INTERNAL)
  - **Context reduction** - Achieve 98.6% reduction for heavily-litigated applications (200+ docs → 1-2 docs)
  - **Smart document filtering** - Focus on key documents (ABST, CLM, SPEC, NOA, etc.)
  - **Workflow optimization** - Use after discovery search for specific applications
  - **Document guidance** - Intelligent summary and download recommendations
  - **Replaces documentBag in search** - Prevents 100x token explosion in discovery workflows
- **✨ Intelligent Extraction Tier (`pfw_get_document_content`)**: - Hybrid auto-optimized extraction
  - **Smart method selection** - Automatically tries PyPDF2 first (free), falls back to Mistral OCR (API key needed) when needed
  - **Cost optimization** - Only pay for OCR when PyPDF2 extraction fails quality check
  - **Quality detection** - Automatically determines if extraction is usable or requires OCR
  - **With Mistral API Key - Always works** - Guaranteed text extraction for any USPTO document (no blank results)
  - **Transparent reporting** - Shows which method was used and associated costs
  - **Unified interface** - Single tool handles all document types (eliminates tool confusion)
  - **Advanced capabilities** - Extracts text from scanned documents, formulas, diagrams, complex layouts
  - **Cost** - Free for text-based PDFs, ~$0.001-$0.003 per document for scanned OCR using Mistral
- **Browser Download Tier (`pfw_get_document_download`)**: Secure proxy downloads
  - **Click-to-download** URLs that work directly in any browser
  - **API key security** - USPTO API credentials never exposed in chat history or browser
  - **Rate limiting compliance** - Automatic enforcement of USPTO's 5 downloads per 10 seconds
  - **Enhanced filenames** - Professional, human-readable filenames for both PFW and FPD documents:
    - PFW: `APP-{app_number}_PAT-{patent_number}_{invention_title}_{type}.pdf`
    - FPD: `PET-{date}_APP-{app}_PAT-{patent}_{description}.pdf`
  - **Hybrid server architecture** - HTTP proxy runs alongside MCP server
  - **Adjustable TCP port** - HTTP proxy's TCP port can be adjusted by an environment variable
  - **🆕 Centralized proxy hub** - PFW proxy (port 8080) now accepts document registrations from FPD MCP for unified download experience across USPTO MCPs.  (Planned future PTAB centralized proxy hub)

#### Enhanced Filename Format used in `pfw_get_document_download` and `pfw_get_granted_patent_documents_download`

The system automatically generates descriptive filenames using application metadata:

**For PFW Documents - Granted Patents:**
```
APP-11752072_PAT-7971071_INTEGRATED_DELIVERY_AND_PROTECTION_ABST.pdf
APP-14171705_PAT-9049188_HYBRID_DEVICE_HAVING_A_PERSONAL_DIGITAL_CLM.pdf
```

**For PFW Documents - Pending Applications:**
```
APP-17896175_COMMUNICATION_METHOD_AND_APPARATUS_SPEC.pdf
APP-16543210_MACHINE_LEARNING_OPTIMIZATION_SYSTEM_DRW.pdf
```

**For FPD Documents - Petition Decisions:**

```
PET-2025-09-03_APP-18462633_PAT-8803593_PATENT_PROSECUTION_HIGHWAY_DECISION.pdf
PET-2024-05-15_APP-17414168_REVIVAL_PETITION_DECISION.pdf
```

**Features:**
- **APP-** prefix for clear application number identification
- **PAT-** prefix shows the granted patent number (when available)
- **PET-** prefix for FPD petition documents with decision date
- **40-character titles** for better readability (PFW) or **40-character descriptions** (FPD)
- **Document type codes** (PFW: ABST, CLM, SPEC, DRW; FPD: DECISION, etc.)
- **Chronological sorting** - FPD filenames start with dates for easy timeline navigation
- **Cross-platform safe** characters and length limits
- **Portfolio-friendly** organization for patent attorneys

### LLM Guidance Functions

| Function (Display Name)               | Purpose                              | Requirements |
| ------------------------------------- | ------------------------------------ | ------------ |
| `pfw_get_guidance` (PFW get guidance) | Context-efficient selective guidance | None         |

#### Context-Efficient Guidance System

**NEW: `pfw_get_guidance` Tool** - Solves MCP Resources visibility problem with selective guidance sections:

🎯 **Quick Reference Chart** - Know exactly which section to call:
- 🔍 "Find patents by inventor/company/art unit" → `pfw_get_guidance("fields")`
- 📄 "Get complete patent package/documents" → `pfw_get_guidance("documents")`
- 🔖 "Decode document codes (NOA, CTFR, 892, etc.)" → `pfw_get_guidance("document_codes")`
- 🤝 "Research IPR vs prosecution patterns" → `pfw_get_guidance("workflows_ptab")`
- 🚩 "Analyze petition red flags + prosecution" → `pfw_get_guidance("workflows_fpd")`
- 📊 "Citation analysis for examiner behavior" → `pfw_get_guidance("workflows_citations")`
- 🧠 "Domain-based RAG for legal framework (§101, §103, §112)" → `pfw_get_guidance("workflows_pinecone")`
- 🏢 "Complete company due diligence" → `pfw_get_guidance("workflows_complete")`
- ⚙️ "Convenience parameter searches" → `pfw_get_guidance("tools")`
- ❌ "Search errors or download issues" → `pfw_get_guidance("errors")`
- 💰 "Reduce API costs" → `pfw_get_guidance("cost")`



##  Smart Field Mapping

Transform complex API field names into user-friendly alternatives:

```python
#  User-friendly (automatically mapped)
fields = [
    "applicationNumberText",    # Direct passthrough
    "inventionTitle",           # applicationMetaData.inventionTitle
    "patentNumber",             # applicationMetaData.patentNumber
    "filingDate",               # applicationMetaData.filingDate
    "parentPatentNumber"        # parentContinuityBag.parentPatentNumber
]

#  Advanced API paths (still supported)
fields = [
    "applicationMetaData.inventionTitle",
    "applicationMetaData.examinerNameText",
    "parentContinuityBag.parentApplicationNumberText"
]
```

### Supported Field Mappings
| User-Friendly | Maps To API Field |
|---------------|------------------|
| `inventionTitle` | `applicationMetaData.inventionTitle` |
| `patentNumber` | `applicationMetaData.patentNumber` |
| `filingDate` | `applicationMetaData.filingDate` |
| `applicationStatusDescriptionText` | `applicationMetaData.applicationStatusDescriptionText` |
| `firstInventorName` | `applicationMetaData.firstInventorName` |
| `parentPatentNumber` | `parentContinuityBag.parentPatentNumber` |
| `docketNumber` | `applicationMetaData.docketNumber` |

*Full mapping with 30+ fields available in `src/patent_filewrapper_mcp/api/helpers.py`*

## 💻 Usage Examples & Integration Workflows

For comprehensive usage examples, including:
- **Convenience parameter searches** (art unit, examiner, applicant, dates)
- **Advanced document filtering** (document codes, direction categories, context reduction)
- **Cross-MCP integration workflows** (PFW + PTAB + FPD + Pinecone)
- **Complete lifecycle due diligence** examples
- **Litigation research patterns**
- **Art unit quality assessment**
- **Cost optimization strategies**

See the detailed **[USAGE_EXAMPLES.md](USAGE_EXAMPLES.md)** documentation.

## 🔧 Field Customization

The MCP server supports user-customizable field sets through YAML configuration for optimal context reduction. You can modify field sets without changing any code!

**Configuration file:** `field_configs.yaml` (in project root)

For complete customization guidance, including progressive workflow strategies, token optimization, and advanced field selection patterns, see **[CUSTOMIZATION.md](CUSTOMIZATION.md)**.

## 🔗 Cross-MCP Integration

This MCP is designed to work seamlessly with three other USPTO MCPs for comprehensive patent lifecycle analysis:

### Related USPTO MCP Servers

| MCP Server                                     | Purpose                                                      | GitHub Repository                                            |
| ---------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **USPTO Patent File Wrapper (PFW)**            | Prosecution history & documents                              | [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp.git) |
| **USPTO Patent Trial and Appeal Board (PTAB)** | Patent Trial and Appeal Board proceedings                    | [uspto_ptab_mcp](https://github.com/john-walkoe/uspto_ptab_mcp.git) |
| **USPTO Enriched Citation**                    | Information about which references, or prior art, were cited in specific patent application office actions.  Uses [USPTO Enriched Citation API v3](https://developer.uspto.gov/api-catalog/uspto-enriched-citation-api-v3) | [uspto_enriched_citation_mcp](https://github.com/john-walkoe/uspto_enriched_citation_mcp.git) |
| **USPTO Final Petition Decisions (FPD)**       | Final Petition Decisions                                     | [uspto_fpd_mcp](https://github.com/john-walkoe/uspto_fpd_mcp.git) |
| **Pinecone Assistant MCP**                     | Patent law knowledge base with AI-powered chat and citations (MPEP, examination guidance) - 1 API key, limited free tier | [pinecone_assistant_mcp](https://github.com/john-walkoe/pinecone_assistant_mcp.git) |
| **Pinecone RAG MCP**                           | Patent law knowledge base with custom embeddings (MPEP, examination guidance) - Requires Pinecone + embedding model, monthly resetting free tier | [pinecone_rag_mcp](https://github.com/john-walkoe/pinecone_rag_mcp.git) |

### Integration Overview

The **Patent File Wrapper (PFW) MCP** serves as the foundation for patent research, providing prosecution history and document access. When combined with the other MCPs, it enables:

- **PFW + PTAB**: Cross-reference PTAB proceedings with prosecution history for litigation research
- **PFW + Enriched Citations**: AI-powered examiner citation analysis and prior art research patterns
- **PFW + FPD**: Understand petition history and procedural issues during prosecution
- **PFW + FPD + PTAB**: Complete patent lifecycle tracking from filing through post-grant challenges
- **PFW + Pinecone (Assistant or RAG)**: Research MPEP guidance before extracting expensive prosecution documents

### Key Integration Patterns

**Cross-Referencing Fields:**
- `applicationNumberText` - Primary key linking PTAB proceedings to PFW prosecution
- `groupArtUnitNumber` - Art unit analysis across all MCPs
- `examinerNameText` - Examiner behavior patterns and quality assessment
- `firstApplicantName` / `inventorBag` - Party matching across MCPs

**Progressive Workflow:**
1. **Discovery** (PFW): Find applications/patents using minimal search with convenience parameters
2. **Citation Analysis** (Enriched Citations): Analyze examiner citation patterns and prior art references
3. **Petition Check** (FPD): Review prosecution procedural history
4. **Challenge Assessment** (PTAB): Check for post-grant challenges
5. **Knowledge Research** (Pinecone): Research MPEP guidance if available (Assistant MCP: `assistant_context` / RAG MCP: `semantic_search`)
6. **Document Analysis** (PFW): Extract targeted prosecution documents

For detailed integration workflows, cross-referencing examples, and complete use cases, see [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md#cross-mcp-integration-workflows).

##  📈Performance Comparison

| Method | Response Size | Context Usage | Features |
|--------|---------------|---------------|----------|
| **Direct curl** | ~100KB+ | High | Raw API access |
| **MCP Balanced** | ~5KB | Medium | Key fields + mapping |
| **MCP Minimal** | ~1KB | Very Low | Essential data only |

##  🧪Testing

### Quick Test
```bash
# Basic functionality test (most essential)
uv run python tests/test_fields_fix.py
```

**Expected Output:**
```
✅ ALL TESTS PASSED - Fields fix is working correctly!
```

For comprehensive testing including proxy server, document extraction, tool reflections, and API key setup instructions, see the **[Testing Guide](tests/README.md)**.

##  📁Project Structure

```
uspto_pfw_mcp/
├── field_configs.yaml             # Root-level field customization
├── launcher.py                     # Entry point launcher
├── .security/                      # Security scanning components
│   ├── patent_prompt_injection_detector.py # Enhanced prompt injection detection
│   └── check_prompt_injections.py # Standalone scanning script
├── src/
│   └── patent_filewrapper_mcp/
│       ├── main.py                 # MCP server with 11+ tools
│       ├── __init__.py
│       ├── __main__.py
│       ├── exceptions.py
│       ├── secure_storage.py       # Windows DPAPI secure storage
│       ├── shared_secure_storage.py
│       ├── config/
│       │   ├── field_manager.py   # Configuration management
│       │   └── tool_reflections.py # Migration notices (guidance moved to pfw_get_guidance)
│       ├── api/
│       │   ├── enhanced_client.py  # Enhanced client with field mapping
│       │   ├── field_constants.py # Field constant definitions
│       │   ├── helpers.py         # Field mapping & utilities
│       │   └── ppubs/             # Patent publication client
│       ├── models/
│       │   ├── constants.py       # System constants
│       │   └── search_params.py   # Search parameter models
│       ├── prompts/               # AI prompt templates
│       │   ├── patent_search.py
│       │   ├── patent_explanation_for_attorneys.py
│       │   ├── patent_invalidity_analysis_defense_Pinecone_PTAB_FPD_Citations.py
│       │   ├── litigation_research_setup_PTAB_FPD.py
│       │   ├── technology_landscape_mapping_PTAB.py
│       │   ├── art_unit_quality_assessment_FPD.py
│       │   ├── complete_patent_package_retrieval_PTAB_FPD.py
│       │   ├── document_filtering_assistant.py
│       │   ├── inventor_portfolio_analysis.py
│       │   ├── examiner_behavior_intelligence_CITATION.py
│       │   └── prior_art_analysis_CITATION.py
│       ├── proxy/
│       │   ├── server.py          # HTTP proxy for secure downloads
│       │   ├── rate_limiter.py    # USPTO rate limiting compliance
│       │   ├── secure_link_cache.py
│       │   ├── models.py
│       │   ├── fpd_document_store.py
│       │   └── ptab_document_store.py
│       ├── reflections/           # Reflection system (legacy)
│       │   ├── base_reflection.py
│       │   ├── pfw_reflections.py
│       │   └── reflection_manager.py
│       ├── services/
│       │   └── ocr_service.py     # OCR quality detection and processing
│       ├── shared/
│       │   └── internal_auth.py   # Shared authentication
│       ├── util/
│       │   ├── database.py
│       │   ├── dpapi_utils.py
│       │   ├── error_handlers.py
│       │   ├── identifier_normalization.py
│       │   ├── input_processing.py
│       │   ├── logging.py         # Enhanced logging utilities
│       │   ├── package_manager.py
│       │   └── security_logger.py
│       └── json/
│           └── search_query.json  # Sample JSON structures
├── deploy/
│   ├── linux_setup.sh            # Linux deployment script
│   ├── deploy_linux.sh
│   ├── windows_setup.ps1         # PowerShell deployment script
│   ├── manage_api_keys.ps1       # API key management utilities
│   ├── Validation-Helpers.psm1   # PowerShell validation module
│   └── validation_helpers.sh     # Bash validation helpers
├── tests/                         # Current test files
│   ├── README.md                  # Testing documentation
│   ├── test_fields_fix.py        # Core functionality test
│   ├── test_proxy_simple.py      # Proxy server test
│   ├── test_mcp_server.py        # MCP server startup test
│   ├── test_quality_detection.py # OCR quality detection test
│   ├── test_unified_key_management.py # Secure key storage test
│   ├── test_download.py
│   ├── test_enhanced_filename.py
│   ├── test_fpd_integration.py
│   ├── test_granted_patent_documents_download.py
│   ├── test_include_fields.py
│   ├── test_mistral_key_logic.py
│   ├── test_optional_mistral.py
│   ├── test_placeholder_detection.py
│   ├── test_ptab_integration.py
│   ├── test_resilience_features.py
│   ├── test_tool_reflections.py
│   ├── simple_test.py
│   └── test_utils.py
├── reference/
│   ├── README.md
│   ├── Document_Descriptions_List.csv
│   └── PatentFileWrapper_swagger.yaml
├── logs/
│   └── security.log              # Security logging output
├── pyproject.toml                 # Package configuration
├── uv.lock                        # uv lockfile
├── README.md                      # This file
├── INSTALL.md                     # Comprehensive installation guide
├── USAGE_EXAMPLES.md             # Function examples and workflows
├── CUSTOMIZATION.md              # Field configuration and optimization guide
├── PROMPTS.md                    # Prompt templates documentation
├── SECURITY_GUIDELINES.md       # Security best practices
└── SECURITY_SCANNING.md         # Automated secret detection guide
```

##  🔍Troubleshooting

### Common Issues

#### API Key Issues
- **For Claude Desktop:** API keys in config file are sufficient
- **For test scripts:** Environment variables must be set

**Setting USPTO API Key:**
- **Windows Command Prompt:** `set USPTO_API_KEY=your_key`
- **Windows PowerShell:** `$env:USPTO_API_KEY="your_key"`
- **Linux/macOS:** `export USPTO_API_KEY=your_key`

**Setting Mistral API Key (for OCR):**
- **Windows Command Prompt:** `set MISTRAL_API_KEY=your_key`
- **Windows PowerShell:** `$env:MISTRAL_API_KEY="your_key"`
- **Linux/macOS:** `export MISTRAL_API_KEY=your_key`

#### uv vs pip Issues
- **uv advantages:** Better dependency resolution, faster installs
- **Mixed installation:** Can use both `uv sync` and `pip install -e .`
- **Testing:** Use `uv run` prefix for uv-managed projects

#### Fields Not Returning Data
- **Cause:** Field name not in mapping
- **Solution:** Add to `field_mapping` in `helpers.py` or use full API field name

#### Authentication Errors
- **Cause:** Missing or invalid API key
- **Solution:** Verify `USPTO_API_KEY` environment variable or Claude Desktop config

#### MCP Server Won't Start
- **Cause:** Missing dependencies or incorrect paths
- **Solution:** Re-run setup script, restart all PowerShell windows, restart Claude Desktop (or other MCP Client) and verify configuration
- **If problems persist:** Reset the MCP installation (see "Resetting MCP Installation" below)

#### Virtual Environment Issues (Windows Setup)
- **Symptom:** "No pyvenv.cfg file" errors during `windows_setup.ps1`
- **Cause:** Claude Desktop locks `.venv` files when running, preventing proper virtual environment creation
- **Solution:**
  1. Close Claude Desktop completely before running setup script
  2. Remove `.venv` folder: `Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue`
  3. Run `.\deploy\windows_setup.ps1` again

#### Resetting MCP Installation

**If you need to completely reset the MCP installation to run the Windows Quick installer again:**

```powershell
# Navigate to the project directory
cd C:\Users\YOUR_USERNAME\uspto_pfw_mcp

# Remove Python cache directories
Get-ChildItem -Path ./src -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue
}

# Remove database files
Remove-Item ./proxy_link_cache.db -Force -ErrorAction SilentlyContinue
Remove-Item ./fpd_documents.db -Force -ErrorAction SilentlyContinue
Remove-Item ./ptab_documents.db -Force -ErrorAction SilentlyContinue

# Now you can run the setup script again
.\deploy\windows_setup.ps1
```

**Linux/macOS Reset:**
```bash
# Navigate to the project directory
cd ~/uspto_pfw_mcp

# Remove Python cache directories
find ./src -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Remove virtual environment and database files
rm -rf .venv
rm -f proxy_link_cache.db fpd_documents.db ptab_documents.db

# Run setup script again
./deploy/linux_setup.sh
```

### Getting Help
1. Check the test scripts for working examples
2. Review the field mapping in `src/patent_filewrapper_mcp/api/helpers.py`
3. Verify your Claude Desktop configuration matches the provided templates in INSTALL.md

## 🛡️ Security & Production Readiness

### Enhanced Error Handling
- **Retry logic with exponential backoff** - Automatic retries for transient failures (3 attempts with 1s, 2s, 4s delays)
- **Smart retry strategy** - Doesn't retry authentication errors or client errors (4xx)
- **Structured logging** - Request ID tracking for better debugging and monitoring
- **Production-grade resilience** - Handles timeouts, network issues, and API rate limits gracefully

### Security Features
- **Environment variable API keys** - No hardcoded credentials anywhere in codebase
- **Secure test patterns** - Test files use environment variables with fallbacks
- **Comprehensive .gitignore** - Prevents accidental credential commits
- **Security guidelines** - Complete documentation for secure development practices
- **Automated secret scanning** - CI/CD and pre-commit hooks prevent API key leaks (detect-secrets)
- **20+ secret types detected** - AWS keys, GitHub tokens, JWT, private keys, API keys, and more
- **Baseline management** - Tracks known placeholders while catching real secrets
- **Prompt injection detection** - 70+ pattern detection system protects against AI-specific attacks
- **Patent-specific security** - Custom patterns detect USPTO API bypass and data extraction attempts
- **Enhanced filtering** - Minimizes false positives while maintaining comprehensive threat coverage

### Request Tracking & Debugging
All API requests include unique request IDs (8-char UUIDs) for correlation:
```
[a1b2c3d4] Starting GET request to applications/search
[a1b2c3d4] Request successful on attempt 1
```

### Documentation
- `SECURITY_GUIDELINES.md` - Comprehensive security best practices
- `SECURITY_SCANNING.md` - Automated secret detection and prevention guide
- `tests/README.md` - Complete testing guide with API key setup
- Enhanced error messages with request IDs for better support

##  📝Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

##  📄License

MIT License

## ⚠️ Disclaimer

**THIS SOFTWARE IS PROVIDED "AS IS" AND WITHOUT WARRANTY OF ANY KIND.**

**Independent Project Notice**: This is an independent personal project and is not affiliated with, endorsed by, or sponsored by the United States Patent and Trademark Office (USPTO).

The author makes no representations or warranties, express or implied, including but not limited to:

- **Accuracy & AI-Generated Content**: No guarantee of data accuracy, completeness, or fitness for any purpose. Users are specifically cautioned that outputs generated or assisted by Artificial Intelligence (AI) components, including but not limited to text, data, or analyses, may be inaccurate, incomplete, fictionalized, or represent "hallucinations" (confabulations) by the AI model.
- **Availability**: USPTO API and Mistral API dependencies may cause service interruptions.
- **Legal Compliance**: Users are solely responsible for ensuring their use of this software, and any submissions or actions taken based on its outputs, strictly comply with all applicable laws, regulations, and policies, including but not limited to:
  - The latest [Guidance on Use of Artificial Intelligence-Based Tools in Practice Before the United States Patent and Trademark Office](https://www.federalregister.gov/documents/2024/04/11/2024-07629/guidance-on-use-of-artificial-intelligence-based-tools-in-practice-before-the-united-states-patent) (USPTO Guidance).
  - The USPTO's Duty of Candor and Good Faith (e.g., 37 CFR 1.56, 11.303), which includes a duty to disclose material information and correct errors.
  - The USPTO's signature requirements (e.g., 37 CFR 1.4(d), 2.193(c), 11.18), certifying human review and reasonable inquiry.
  - All rules regarding inventorship (e.g., each claimed invention must have at least one human inventor).
- **Legal Advice**: This tool provides data access and processing only, not legal counsel. All results must be independently verified, critically analyzed, and professionally judged by qualified legal professionals.
- **Commercial Use**: Users must verify USPTO and Mistral terms for commercial applications.
- **Confidentiality & Data Security**: The author makes no representations regarding the confidentiality or security of any data, including client-sensitive or technical information, input by the user into the software's AI components or transmitted to third-party AI services (e.g., Mistral API). Users are responsible for understanding and accepting the privacy policies, data retention practices, and security measures of any integrated third-party AI services.
- **Foreign Filing Licenses & Export Controls**: Users are solely responsible for ensuring that the input or processing of any data, particularly technical information, through this software's AI components does not violate U.S. foreign filing license requirements (e.g., 35 U.S.C. 184, 37 CFR Part 5) or export control regulations (e.g., EAR, ITAR). This includes awareness of potential "deemed exports" if foreign persons access such data or if AI servers are located outside the United States.

**LIMITATION OF LIABILITY:** Under no circumstances shall the author be liable for any direct, indirect, incidental, special, or consequential damages arising from use of this software, even if advised of the possibility of such damages.

### USER RESPONSIBILITY: YOU ARE SOLELY RESPONSIBLE FOR THE INTEGRITY AND COMPLIANCE OF ALL FILINGS AND ACTIONS TAKEN BEFORE THE USPTO.

- **Independent Verification**: All outputs, analyses, and content generated or assisted by AI within this software MUST be thoroughly reviewed, independently verified, and corrected by a human prior to any reliance, action, or submission to the USPTO or any other entity. This includes factual assertions, legal contentions, citations, evidentiary support, and technical disclosures.
- **Duty of Candor & Good Faith**: You must adhere to your duty of candor and good faith with the USPTO, including the disclosure of any material information (e.g., regarding inventorship or errors) and promptly correcting any inaccuracies in the record.
- **Signature & Certification**: You must personally sign or insert your signature on any correspondence submitted to the USPTO, certifying your personal review and reasonable inquiry into its contents, as required by 37 CFR 11.18(b). AI tools cannot sign documents, nor can they perform the required human inquiry.
- **Confidential Information**: DO NOT input confidential, proprietary, or client-sensitive information into the AI components of this software without full client consent and a clear understanding of the data handling practices of the underlying AI providers. You are responsible for preventing inadvertent or unauthorized disclosure.
- **Export Controls**: Be aware of and comply with all foreign filing license and export control regulations when using this tool with sensitive technical data.
- **Service Compliance**: Ensure compliance with all USPTO (e.g., Terms of Use for USPTO websites, USPTO.gov account policies, restrictions on automated data mining) and Mistral terms of service. AI tools cannot obtain USPTO.gov accounts.
- **Security**: Maintain secure handling of API credentials and client information.
- **Testing**: Test thoroughly before production use.
- **Professional Judgment**: This tool is a supplement, not a substitute, for your own professional judgment and expertise.

**By using this software, you acknowledge that you have read this disclaimer and agree to use the software at your own risk, accepting full responsibility for all outcomes and compliance with relevant legal and ethical obligations.**

> **Note for Legal Professionals:** While this tool provides access to patent research tools commonly used in legal practice, it is a data retrieval and AI-assisted processing system only. All results require independent verification, critical professional analysis, and cannot substitute for qualified legal counsel or the exercise of your personal professional judgment and duties outlined in the USPTO Guidance on AI Use.

##  🔗Related Links

- [USPTO Open Data Portal](https://data.uspto.gov/myodp)
- [USPTO Enriched Citation API v3](https://developer.uspto.gov/api-catalog/uspto-enriched-citation-api-v3)
- [USPTO Patent Trial and Appeal Board (PTAB) API v2](https://developer.uspto.gov/api-catalog/ptab-api-v2-migrating-odp-soon)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Claude](https://claude.ai)
- [uv Package Manager](https://github.com/astral-sh/uv)
- [Mistral OCR](https://mistral.ai/solutions/document-ai)

## 💝 Support This Project

If you find this USPTO Patent File Wrapper MCP Server useful, please consider supporting the development! This project was developed during my personal time over many hours to provide a comprehensive, production-ready tool for the patent community.

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://paypal.me/walkoe)

Your support helps maintain and improve this open-source tool for everyone in the patent community. Thank you!

##  Acknowledgments

- [USPTO](https://www.uspto.gov/) for providing the Patent File Wrapper API
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- **[Claude Code](https://claude.ai/code)** for exceptional development assistance, architectural guidance, documentation creation, PowerShell automation, test organization, and comprehensive code development throughout this project
- **[Claude Desktop](https://claude.ai)** for additional development support and testing assistance

---

**Questions?** See [INSTALL.md](INSTALL.md) for complete cross-platform installation guide or review the test scripts for working examples.
