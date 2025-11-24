# Field Customization Guide

This document provides comprehensive guidance on customizing field sets for the USPTO Patent File Wrapper MCP Server to optimize context usage and workflow efficiency.

## 🔧 Field Customization

### User-Configurable Field Sets

The MCP server supports user-customizable field sets through YAML configuration at the project root. You can modify field sets that the minimal and balanced searches bring back without changing any code!

**Configuration file:** `field_configs.yaml` (in project root)

### Easy Customization Process

1. **Open** `field_configs.yaml` in the project root directory
2. **Uncomment fields** you want by removing the `#` symbol
3. **Save the file** - changes take effect on next Claude Desktop restart
4. **Use the simplified tools** with your custom field selections

### Available Field Sets (Progressive Workflow)

- **`applications_minimal`** - Ultra-minimal for application searches: **15 essential fields** for high-volume discovery (20-50 results)
- **`applications_balanced`** - Comprehensive application analysis: **18 key fields** for detailed application/patent analysis and fields used in cross searches with the USPTO Patent Trial and Appeal Board MCP
- **`inventor_minimal`** - Ultra-minimal for inventor searches: **15 essential fields** for high-volume inventor discovery
- **`inventor_balanced`** - Comprehensive inventor analysis: **18 key fields** for detailed inventor analysis and fields used in cross searches with the USPTO PTAB (Patent Trial and Appeal Board) MCP

### Professional Field Categories Available

- **Critical Dates**: `applicationStatusDate`, `effectiveFilingDate`, `earliestPublicationDate`
- **Entity Information**: `firstApplicantName`, `docketNumber`, `applicationConfirmationNumber`
- **International/PCT**: `nationalStageIndicator`, `pctPublicationNumber`, `pctPublicationDate`
- **Patent Classification**: `class`, `subclass`, `cpcClassificationBag`, `uspcSymbolText`
- **AIA Compliance**: `firstInventorToFileIndicator`
- **Publication Tracking**: `publicationCategoryBag`, `publicationSequenceNumberBag`

### Example Customization

**File: `field_configs.yaml`**
```yaml
predefined_sets:
  applications_minimal:
    description: "Ultra-minimal fields for application searches (95-99% context reduction)"
    fields:
      # === MOST USED FIELDS ===
      - applicationNumberText                           # Application number (required)
      - applicationMetaData.inventionTitle              # Patent title (required)
      - applicationMetaData.inventorBag                 # All inventors (array)
      - applicationMetaData.firstApplicantName          # First applicant (often company/organization)
      - applicationMetaData.uspcSymbolText              # US Patent Classification (combined)
      - applicationMetaData.cpcClassificationBag        # Cooperative Patent Classification
      - applicationMetaData.patentNumber                # Patent number (if granted)
      - parentPatentNumber                              # Parent patent numbers (short form)
      - associatedDocuments                             # XML files metadata
      - applicationMetaData.examinerNameText            # Assigned examiner
      - applicationMetaData.groupArtUnitNumber          # Art unit number
      - applicationMetaData.filingDate                  # Original filing date
      - applicationMetaData.grantDate                   # Grant date (if granted)
      - applicationMetaData.customerNumber              # Customer number
      - applicationMetaData.applicationStatusCode       # Status code
      # ... 40+ more organized field options

  applications_balanced:
    description: "Key fields for application searches (85-95% context reduction)"
    fields:
      # === BALANCED FIELDS FOR ADDITIONAL INFO AND CROSS REFRENCE WITH OTHER USPTO MCPs ===
      - applicationNumberText                           # Application number (required)
      - applicationMetaData.inventionTitle              # Patent title (required)
      - applicationMetaData.inventorBag                 # All inventors (array)
      - applicationMetaData.firstApplicantName          # First applicant (often company/organization)
      - applicationMetaData.uspcSymbolText              # US Patent Classification (combined)
      - applicationMetaData.cpcClassificationBag        # Cooperative Patent Classification
      - applicationMetaData.patentNumber                # Patent number (if granted)
      - parentPatentNumber                              # Parent patent numbers (short form)
      - associatedDocuments                             # XML files metadata
      - applicationMetaData.examinerNameText            # Assigned examiner
      - applicationMetaData.groupArtUnitNumber          # Art unit number
      - applicationMetaData.filingDate                  # Original filing date
      - applicationMetaData.grantDate                   # Grant date (if granted)
      - applicationMetaData.customerNumber              # Customer number
      - applicationMetaData.applicationStatusCode       # Status code
      - applicationMetaData.applicantBag                # All applicants (array)
      - assignmentBag                                   # Assignment records
      - applicationMetaData.applicationStatusDescriptionText  # Human-readable status
      # ... additional field categories organized below
```

### Complete Field Categories in field_configs.yaml

The `field_configs.yaml` file contains over 40 professional patent prosecution fields organized into the following categories:

#### Core Required Fields
- `applicationNumberText` - Application number (always required)
- `applicationMetaData.inventionTitle` - Patent title (always required)

#### Inventor and Applicant Information
- `applicationMetaData.inventorBag` - All inventors (array)
- `applicationMetaData.firstInventorName` - First named inventor
- `applicationMetaData.firstApplicantName` - First applicant (often company/organization)
- `applicationMetaData.applicantBag` - All applicants (array)

#### Patent Classification Systems
- `applicationMetaData.uspcSymbolText` - US Patent Classification (combined)
- `applicationMetaData.cpcClassificationBag` - Cooperative Patent Classification
- `applicationMetaData.class` - Primary US class
- `applicationMetaData.subclass` - Primary US subclass

#### Patent Numbers and Status
- `applicationMetaData.patentNumber` - Patent number (if granted)
- `applicationMetaData.applicationStatusCode` - Status code (150=granted, 30=pending)
- `applicationMetaData.applicationStatusDescriptionText` - Human-readable status

#### Critical Dates
- `applicationMetaData.filingDate` - Original filing date
- `applicationMetaData.grantDate` - Grant date (if granted)
- `applicationMetaData.applicationStatusDate` - Status date
- `applicationMetaData.effectiveFilingDate` - Effective filing date
- `applicationMetaData.earliestPublicationDate` - Earliest publication date

#### Prosecution Information
- `applicationMetaData.examinerNameText` - Assigned examiner
- `applicationMetaData.groupArtUnitNumber` - Art unit number
- `applicationMetaData.customerNumber` - Customer number
- `applicationMetaData.docketNumber` - Applicant's docket number

#### Parent/Child Relationships
- `parentPatentNumber` - Parent patent numbers (short form)
- `parentContinuityBag` - Full parent/child tracking
- `childPatentNumber` - Child patent numbers (short form)

#### International/PCT Fields
- `applicationMetaData.nationalStageIndicator` - PCT national stage indicator
- `applicationMetaData.pctPublicationNumber` - PCT publication number
- `applicationMetaData.pctPublicationDate` - PCT publication date

#### Assignment and Entity Information
- `assignmentBag` - Assignment records
- `applicationMetaData.firstInventorToFileIndicator` - AIA first-inventor-to-file

#### Document Access
- `associatedDocuments` - XML files metadata
- `documentBag` - Prosecution documents (WARNING: 100x token explosion - use pfw_get_application_documents instead)

#### Advanced Publication Tracking
- `applicationMetaData.publicationCategoryBag` - Publication categories
- `applicationMetaData.publicationSequenceNumberBag` - Publication sequence tracking

### Context Reduction Strategies

#### Token Efficiency by Field Set

| Field Set | Field Count | Token Usage (50 results) | Reduction | Use Case |
|-----------|------------|--------------------------|-----------|----------|
| **Custom (2-3 fields)** | 2-3 | ~5KB | 99% | Citation workflows, app number extraction |
| **Minimal (default)** | 15 | ~25KB | 95% | Discovery, user selection workflows |
| **Balanced (default)** | 18 | ~50KB | 85-90% | Analysis, cross-MCP integration |
| **Full with documentBag** | 40+ | ~500KB+ | 0% | **NEVER USE** |

#### Custom Fields Parameter (Ultra-Minimal Mode)

All minimal and balanced search tools support an optional `fields` parameter for maximum token efficiency:

```python
# Standard minimal search (15 fields, 95% reduction)
pfw_search_applications_minimal(art_unit='2128', limit=50)

# Ultra-minimal search (2 fields, 99% reduction)
pfw_search_applications_minimal(
    art_unit='2128',
    fields=['applicationNumberText', 'examinerNameText'],
    limit=50
)

# Citation workflow optimization (3 fields only)
pfw_search_applications_minimal(
    examiner_name='SMITH, JANE',
    fields=['applicationNumberText', 'examinerNameText', 'filingDate'],
    limit=30
)
```

#### When to Use Each Approach

**Ultra-Minimal Mode (Custom Fields Parameter)**:
- Citation workflows: PFW → Citations integration
- Single-record lookups: Patent number → app number conversion
- High-volume extraction: 100+ results where only 2-3 fields needed
- Cross-MCP integration: Extract minimal fields for PTAB/FPD cross-reference

**Preset Minimal (YAML Configuration)**:
- Discovery workflows: Need title, inventor, classification for user selection
- General patent research: Standard discovery workflow
- First-time exploration: Don't know which fields you'll need yet

**Preset Balanced (YAML Configuration)**:
- Analysis workflows: Need comprehensive metadata for pattern analysis
- Cross-MCP integration: Full field set for PTAB/FPD cross-reference
- Attorney workflows: Need assignment, dates, status information

### Field Mapping System

The MCP server includes smart field mapping that transforms complex API field names into user-friendly alternatives:

#### Supported Field Mappings

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

#### Field Mapping Examples

```python
# User-friendly (automatically mapped)
fields = [
    "applicationNumberText",    # Direct passthrough
    "inventionTitle",           # applicationMetaData.inventionTitle
    "patentNumber",             # applicationMetaData.patentNumber
    "filingDate",               # applicationMetaData.filingDate
    "parentPatentNumber"        # parentContinuityBag.parentPatentNumber
]

# Advanced API paths (still supported)
fields = [
    "applicationMetaData.inventionTitle",
    "applicationMetaData.examinerNameText",
    "parentContinuityBag.parentApplicationNumberText"
]
```

### Best Practices for Field Customization

#### Progressive Workflow Design

1. **Start Minimal**: Use 15-field preset for discovery (95% reduction)
2. **User Selection**: Present results for user/attorney to choose promising patents
3. **Targeted Analysis**: Use balanced preset or custom fields for detailed analysis
4. **Document Extraction**: Use targeted document tools only when needed

#### Token Budget Management

**High-Volume Workflows (100+ results)**:
- Use ultra-minimal mode (2-3 fields)
- Extract only essential fields for initial filtering
- Progress to detailed analysis only for selected results

**Analysis Workflows (10-20 results)**:
- Use preset minimal or balanced configurations
- Include classification and examiner fields for pattern analysis
- Add assignment fields for entity analysis

**Cross-MCP Integration**:
- Use balanced preset to include cross-reference fields
- Include `applicationNumberText`, `groupArtUnitNumber`, `examinerNameText`
- Add `firstApplicantName` and `inventorBag` for entity matching

#### Common Field Selection Patterns

**Citation Analysis Workflow**:
```yaml
fields: ['applicationNumberText', 'examinerNameText', 'filingDate', 'groupArtUnitNumber']
# Purpose: Extract minimal data for PFW → Citations workflow
```

**Entity Portfolio Analysis**:
```yaml
fields: ['applicationNumberText', 'inventionTitle', 'patentNumber', 'firstApplicantName', 'inventorBag']
# Purpose: Map company/inventor patent portfolios
```

**Art Unit Quality Assessment**:
```yaml
fields: ['applicationNumberText', 'examinerNameText', 'groupArtUnitNumber', 'filingDate', 'grantDate', 'applicationStatusCode']
# Purpose: Analyze art unit prosecution patterns and examiner performance
```

**Litigation Research**:
```yaml
fields: ['applicationNumberText', 'inventionTitle', 'patentNumber', 'examinerNameText', 'filingDate', 'grantDate', 'assignmentBag']
# Purpose: Comprehensive patent analysis for litigation preparation
```

### Field Configuration Validation

#### Testing Your Configuration

After modifying `field_configs.yaml`:

1. **Restart Claude Desktop** - Changes only take effect after restart
2. **Test minimal search** - Run a small test search to verify fields
3. **Check token usage** - Monitor context consumption in your workflows

#### Common Configuration Issues

**Missing Required Fields**:
- Always include `applicationNumberText` (required for all workflows)
- Include `applicationMetaData.inventionTitle` for user-readable results

**Token Explosion**:
- Never include `documentBag` in field configurations
- Use `associatedDocuments` instead for XML file metadata

**Cross-MCP Integration Issues**:
- Include `examinerNameText` for citation workflows
- Include `applicationNumberText` for PTAB cross-reference
- Include `groupArtUnitNumber` for art unit analysis

#### Field Performance Notes

**Fast Fields** (minimal processing overhead):
- `applicationNumberText`, `inventionTitle`, `patentNumber`
- `filingDate`, `grantDate`, `applicationStatusCode`
- `examinerNameText`, `groupArtUnitNumber`

**Medium Fields** (moderate processing):
- `inventorBag`, `applicantBag`, `cpcClassificationBag`
- `parentPatentNumber`, `assignmentBag`

**Expensive Fields** (heavy processing - use sparingly):
- `parentContinuityBag` (full continuity chain)
- `documentBag` (NEVER use - 100x token explosion)

### Advanced Customization

#### Creating Custom Field Sets

You can create entirely new field sets beyond the default minimal/balanced:

```yaml
predefined_sets:
  applications_citation_workflow:
    description: "Ultra-minimal for citation integration (99% reduction)"
    fields:
      - applicationNumberText
      - examinerNameText
      - filingDate
      - groupArtUnitNumber

  applications_entity_analysis:
    description: "Entity portfolio mapping (90% reduction)"
    fields:
      - applicationNumberText
      - applicationMetaData.inventionTitle
      - applicationMetaData.patentNumber
      - applicationMetaData.firstApplicantName
      - applicationMetaData.inventorBag
      - assignmentBag

  applications_litigation_ready:
    description: "Comprehensive litigation research (70% reduction)"
    fields:
      - applicationNumberText
      - applicationMetaData.inventionTitle
      - applicationMetaData.patentNumber
      - applicationMetaData.examinerNameText
      - applicationMetaData.groupArtUnitNumber
      - applicationMetaData.filingDate
      - applicationMetaData.grantDate
      - applicationMetaData.applicantBag
      - applicationMetaData.inventorBag
      - assignmentBag
      - parentContinuityBag
```

#### Dynamic Field Selection

For advanced users who need programmatic field selection:

```python
# Use the fields parameter to override any preset
pfw_search_applications_minimal(
    query='artificial intelligence',
    fields=['applicationNumberText', 'inventionTitle', 'patentNumber'],
    limit=50
)
# This overrides the YAML configuration for this specific search
```

### Troubleshooting Field Configuration

#### Common Error Messages

**"Field not found in mapping"**:
- Check spelling of field names in your YAML file
- Verify field exists in `src/patent_filewrapper_mcp/api/helpers.py`
- Use full API path if user-friendly mapping doesn't exist

**"Empty results with custom fields"**:
- Ensure `applicationNumberText` is always included
- Check that your search criteria are valid
- Test with default fields first, then add custom fields

**"High token usage despite minimal configuration"**:
- Remove `documentBag` from your field list immediately
- Limit results with appropriate `limit` parameter
- Use ultra-minimal mode for discovery workflows

#### Performance Validation

To validate your configuration efficiency:

```bash
# Test your custom configuration
uv run python tests/test_field_mapping_diagnostic.py

# Check for token explosion issues
uv run python tests/test_fields_fix.py
```

#### Field Availability Reference

**Always Available**:
- `applicationNumberText`, `applicationMetaData.inventionTitle`
- `applicationMetaData.patentNumber`, `applicationMetaData.filingDate`

**Granted Patents Only**:
- `applicationMetaData.grantDate`
- Some advanced classification fields

**Application-Dependent**:
- `assignmentBag` (only if assignments exist)
- `parentContinuityBag` (only if continuity relationships exist)
- `pctPublicationNumber` (only for PCT applications)

This comprehensive field customization system allows you to optimize the MCP server for your specific workflows while maintaining the flexibility to adjust as your needs evolve.
