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
- Referenced by `PFW_get_guidance('document_codes')` for common code decoder
- Full reference for all possible documentBag codes
- Used with `PFW_get_application_documents(app_number, document_code='CODE')`

**Common Codes:**
- **CTNF** - Office Action (Non-Final Rejection)
- **CTFR** - Office Action (Final Rejection)
- **NOA** - Notice of Allowance
- **892** - Notice of References Cited (Examiner Citations)
- **IDS** - Information Disclosure Statement
- **1449** - Information Disclosure Statement (PTO-1449)
- **CLM** - Claims
- **ABST** - Abstract
- **SPEC** - Specification
- **DRW** - Drawings

See `PFW_get_guidance('document_codes')` for the top 50+ most useful codes.

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

### Office Action API references

Both OA tools read the ODP Office Action API
(`/api/v1/patent/office-action/search` and
`/api/v1/patent/office-action/{officeActionRecordIdentifier}/download/officeActionText`,
client `api/office_action_client.py`), documented on the USPTO Open Data
Portal; the live-probed coverage is in the `tools/oa_tools.py` module
docstring.

Four files document the two RETIRED Office Action datasets the OA tools used
to call (both answer an HTML 404 since about 2026-10-10), kept for history:

- `oa-rejections.yaml` / `Office Action Rejections.txt` - the Office Action
  Rejections dataset (`/api/v1/patent/oa/oa_rejections/v2`)
- `oa-text-retrieval.yaml` / `Office Action Text Retrieval.txt` - the Office
  Action text dataset (`/api/v1/patent/oa/oa_actions/v1`)

---

## Integration with MCP

### Document Codes
The `document_codes` section in `PFW_get_guidance` provides a curated list of 50+ most useful codes from `Document_Descriptions_List.csv`, organized by:
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
```

`field_configs.yaml` is hand-maintained: edit it directly, then restart the
server. There is no generator script.

---

## Related Documentation

- **Tool Documentation:** See tool docstrings under `src/patent_filewrapper_mcp/tools/`
- **Field Configs:** See `field_configs.yaml` for field selection
- **API Helpers:** See `src/patent_filewrapper_mcp/api/helpers.py` for field mapping
- **Guidance System:** Use `PFW_get_guidance('document_codes')` for code decoder
- **MCP Resource:** Use MCP RESOURCE: USPTO Document Code Decoder for user initiated code decoder

---

## Notes

**Exclusions:** The curated document_codes section in get guidance excludes:

- Petition codes (refer to FPD MCP for petition-specific documents)
- PTAB codes (refer to PTAB MCP for trial proceedings)
- PCT/International codes (focus on US prosecution)

These exclusions keep the decoder focused on core US patent prosecution workflows.  (The MCP RESOURCE: USPTO Document Code Decoder does include the PTAB and FPD documents)
