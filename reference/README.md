# USPTO PFW MCP Reference Documentation

This directory contains official USPTO reference documentation used by the Patent File Wrapper MCP.

## Files

### `Document_Descriptions_List.csv`
**Source:** USPTO Patent File Wrapper API
**Updated:** 04/27/2022
**Size:** ~189 KB (3,133 rows)

Comprehensive list of all USPTO document codes used in patent prosecution with descriptions.

**Contents:**
- **3,100+ document codes** with official descriptions
- Categories: Amendments, Office Actions, Appeals, Citations, Filings, etc.
- Columns: Category, Document Description, USPTO Business Process, DOC CODE, FILING TYPE, NEW/FOLLOWON

**Usage:**
- Referenced by `pfw_get_guidance('document_codes')` for common code decoder
- Full reference for all possible documentBag codes
- Used with `pfw_get_application_documents(app_number, document_code='CODE')`

**Common Codes:**
- **CTFR** - Office Action (Non-Final Rejection)
- **CTNF** - Office Action (Final Rejection)
- **NOA** - Notice of Allowance
- **892** - Notice of References Cited (Examiner Citations)
- **IDS** - Information Disclosure Statement
- **1449** - Information Disclosure Statement (PTO-1449)
- **CLM** - Claims
- **ABST** - Abstract
- **SPEC** - Specification
- **DRW** - Drawings

See `pfw_get_guidance('document_codes')` for the top 50+ most useful codes.

---

### `PatentFileWrapper_swagger.yaml`
**Source:** USPTO Patent File Wrapper API
**Updated:** 11/09/2024
**Size:** ~100 KB

OpenAPI/Swagger specification for the USPTO Patent File Wrapper (PFW) REST API.

**Contents:**
- Complete API endpoint definitions
- Request/response schemas
- Authentication requirements
- Field definitions and data types
- Query parameter specifications

**Key Endpoints:**
- `/applications` - Search patent applications
- `/applications/{applicationNumberText}` - Get application details
- `/applications/{applicationNumberText}/documentBag` - Get prosecution documents
- `/applications/{applicationNumberText}/download` - Download documents

**Usage:**
- API schema reference for enhanced_client.py
- Field path mapping for field_configs.yaml
- Parameter validation and documentation

---

## Integration with MCP

### Document Codes
The `document_codes` section in `pfw_get_guidance` provides a curated list of 50+ most useful codes from `Document_Descriptions_List.csv`, organized by:
- Examiner Communications (CTFR, NOA, 892, INTERVIEW, etc.)
- Applicant Responses (A..., RCEX, IDS, 1449, etc.)
- Patent Components (ABST, CLM, SPEC, DRW, etc.)
- Administrative Documents (FEE, POA, CONTIN, etc.)
- Prosecution History (ABRF, RPLY, FDEC, etc.)

### API Schema
The Swagger specification ensures:
- Type-safe API calls in enhanced_client.py
- Accurate field path mapping in helpers.py
- Complete parameter documentation in tool docstrings

---

## Updating Reference Files

These files should be updated when:
1. **USPTO releases new API versions ([Here](https://data.uspto.gov/swagger/swagger.yaml))** - Update `PatentFileWrapper_swagger.yaml`
2. **New document codes are added ([Here](https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description))**  - Update `Document_Descriptions_List.csv`
3. **API field schemas change** - Regenerate field_configs.yaml mappings

To update:
```bash
# Download latest Swagger spec from USPTO
curl -O https://developer.uspto.gov/patentapi/v1/swagger/PatentFileWrapper.yaml
mv PatentFileWrapper.yaml reference/PatentFileWrapper_swagger.yaml

# Download latest document codes (if available from USPTO)
# Update reference/Document_Descriptions_List.csv

# Regenerate field configs if needed
python scripts/generate_field_configs.py
```

---

## Related Documentation

- **Tool Documentation:** See tool docstrings in `src/patent_filewrapper_mcp/main.py`
- **Field Configs:** See `field_configs.yaml` for field selection
- **API Helpers:** See `src/patent_filewrapper_mcp/api/helpers.py` for field mapping
- **Guidance System:** Use `pfw_get_guidance('document_codes')` for code decoder
- **MCP Resource:** Use MCP RESOURCE: USPTO Document Code Decoder for user initiated code decoder

---

## Notes

**Exclusions:** The curated document_codes section in get guidance excludes:

- Petition codes (refer to FPD MCP for petition-specific documents)
- PTAB codes (refer to PTAB MCP for trial proceedings)
- PCT/International codes (focus on US prosecution)

These exclusions keep the decoder focused on core US patent prosecution workflows.  (The MCP RESOURCE: USPTO Document Code Decoder does include the PTAB and FPD documents)
