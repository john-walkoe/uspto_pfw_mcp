"""Patent XML parsing for LLM consumption (audit F3 split).

Free functions — parsing USPTO PTGRXML/APPXML has no dependency on the HTTP
client. EnhancedPatentClient delegates here to keep its public surface.
"""
from typing import List, Optional

# defusedxml: hardens against XXE / entity-expansion in USPTO-served XML (audit L12)
import defusedxml.ElementTree as ET


def parse_xml_for_llm(
    xml_content: str,
    include_fields: Optional[List[str]] = None
) -> dict:
    """
    Parse USPTO XML into LLM-friendly structured format.

    Optimized for context efficiency - only extracts requested fields.

    Args:
        xml_content: Raw XML string
        include_fields: Optional list of fields to include
                      Default: ["abstract", "claims", "description"]
                      Available: "abstract", "claims", "description", "inventors",
                                "applicants", "classifications", "citations", "publication_info"

    Note: Metadata fields (inventors, applicants, classifications) are also available
    via search_balanced. For citation analysis, use uspto_enriched_citation_mcp for
    richer citation data.
    """
    try:
        root = ET.fromstring(xml_content)

        # Determine XML type (PTGRXML vs APPXML)
        is_patent = root.tag in ['us-patent-grant', 'patent-grant']

        # Default to core content fields if not specified
        if include_fields is None:
            include_fields = ["abstract", "claims", "description"]

        # Start with xml_type (always included)
        structured = {
            "xml_type": "patent" if is_patent else "application"
        }

        # Conditionally add requested fields
        if "abstract" in include_fields:
            structured["abstract"] = _extract_abstract(root)

        if "claims" in include_fields:
            structured["claims"] = _extract_claims(root)

        if "description" in include_fields:
            structured["description"] = _extract_description(root)

        if "inventors" in include_fields:
            structured["inventors"] = _extract_inventors(root)

        if "applicants" in include_fields:
            structured["applicants"] = _extract_applicants(root)

        if "classifications" in include_fields:
            structured["classifications"] = _extract_classifications(root)

        if "citations" in include_fields:
            structured["citations"] = _extract_citations(root)

        if "publication_info" in include_fields:
            structured["publication_info"] = _extract_publication_info(root)

        return structured

    except Exception as e:
        return {
            "error": f"XML parsing failed: {str(e)}",
            "raw_available": True
        }

def build_fields_metadata(
    include_fields: Optional[List[str]],
    structured_content: dict
) -> dict:
    """
    Build minimal metadata about which fields were included in the response.

    Args:
        include_fields: The include_fields parameter passed by user (or None for default)
        structured_content: The structured content dict that was built

    Returns:
        Minimal metadata dict for field discoverability
    """
    # All available fields
    all_fields = [
        "abstract", "claims", "description",
        "inventors", "applicants", "classifications",
        "citations", "publication_info"
    ]

    # Fields actually included (from structured_content, excluding xml_type and error)
    fields_included = [
        k for k in structured_content.keys()
        if k not in ["xml_type", "error", "raw_available"]
    ]

    metadata = {
        "fields_included": fields_included,
        "fields_available": all_fields,
        "using_default": include_fields is None
    }

    # Add simple hint if using defaults (for LLM discoverability)
    if include_fields is None:
        metadata["note"] = "Using default fields. Add include_fields=['inventors', 'applicants'] for entity info. RECOMMENDED: Set include_raw_xml=False to remove ~50K token raw XML overhead. See pfw_get_guidance(section='tools') for all options"
    else:
        metadata["note"] = "Custom fields selected. RECOMMENDED: Set include_raw_xml=False to remove ~50K token raw XML overhead unless needed for debugging."

    return metadata

def _extract_abstract(root) -> str:
    """Extract abstract text from XML"""
    abstract_elem = root.find('.//abstract')
    if abstract_elem is not None:
        return ' '.join(abstract_elem.itertext()).strip()
    return "Abstract not found"

def _extract_claims(root) -> list:
    """Extract all claims from XML"""
    claims = []
    for claim in root.findall('.//claim'):
        claim_num = claim.get('num', 'Unknown')
        claim_text = ' '.join(claim.itertext()).strip()
        claims.append({
            "number": claim_num,
            "text": claim_text,
            "type": "independent" if "comprising:" in claim_text or "wherein:" in claim_text else "dependent"
        })
    return claims

def _extract_description(root) -> str:
    """Extract description/specification text"""
    desc_elem = root.find('.//description')
    if desc_elem is not None:
        # Get first few paragraphs for summary
        paragraphs = desc_elem.findall('.//p')[:5]  # Limit for LLM context
        return '\n\n'.join([' '.join(p.itertext()).strip() for p in paragraphs])
    return "Description not found"

def _extract_inventors(root) -> list:
    """Extract inventor information"""
    inventors = []

    # Try standard inventor elements first
    for inventor in root.findall('.//inventor'):
        name_elem = inventor.find('.//name')
        if name_elem is not None:
            first = name_elem.findtext('.//first-name', '')
            last = name_elem.findtext('.//last-name', '')
            inventors.append(f"{first} {last}".strip())

    # If no standard inventors found, try applicant-inventors
    if not inventors:
        for applicant in root.findall('.//applicant[@app-type="applicant-inventor"]'):
            addressbook = applicant.find('.//addressbook')
            if addressbook is not None:
                first = addressbook.findtext('.//first-name', '')
                last = addressbook.findtext('.//last-name', '')
                if first or last:
                    inventors.append(f"{first} {last}".strip())

    return inventors

def _extract_applicants(root) -> list:
    """Extract applicant information"""
    applicants = []

    # Try standard applicant elements first
    for applicant in root.findall('.//applicant'):
        name_elem = applicant.find('.//name')
        if name_elem is not None:
            applicants.append(' '.join(name_elem.itertext()).strip())

    # If no standard applicants found, try addressbook format
    if not applicants:
        for applicant in root.findall('.//applicant'):
            addressbook = applicant.find('.//addressbook')
            if addressbook is not None:
                # Check if it's an organization or person
                orgname = addressbook.findtext('.//orgname', '')
                if orgname:
                    applicants.append(orgname.strip())
                else:
                    first = addressbook.findtext('.//first-name', '')
                    last = addressbook.findtext('.//last-name', '')
                    if first or last:
                        applicants.append(f"{first} {last}".strip())

    return applicants

def _extract_classifications(root) -> dict:
    """Extract classification information"""
    classifications = {
        "uspc": [],
        "cpc": [],
        "ipc": []
    }

    # USPC classifications
    for uspc in root.findall('.//classification-us'):
        main = uspc.findtext('.//main-classification', '')
        if main:
            classifications["uspc"].append(main.strip())

    # CPC classifications
    for cpc in root.findall('.//classification-cpc'):
        symbol = cpc.findtext('.//symbol', '')
        if symbol:
            classifications["cpc"].append(symbol.strip())

    return classifications

def _extract_citations(root) -> list:
    """Extract patent and non-patent citations"""
    citations = []
    for cite in root.findall('.//citation'):
        patent_cite = cite.find('.//patcit')
        if patent_cite is not None:
            doc_num = patent_cite.findtext('.//doc-number', '')
            if doc_num:
                citations.append({
                    "type": "patent",
                    "number": doc_num.strip()
                })
    return citations[:10]  # Limit for context

def _extract_publication_info(root) -> dict:
    """Extract publication information"""
    pub_info = {}

    # Document number
    doc_num = root.findtext('.//doc-number')
    if doc_num:
        pub_info["document_number"] = doc_num.strip()

    # Publication date
    pub_date = root.findtext('.//publication-date')
    if pub_date:
        pub_info["publication_date"] = pub_date.strip()

    # Application number
    app_number = root.findtext('.//application-number')
    if app_number:
        pub_info["application_number"] = app_number.strip()

    return pub_info
