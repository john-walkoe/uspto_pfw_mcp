"""Patent XML parsing for LLM consumption (audit F3 split).

Free functions — parsing USPTO PTGRXML/APPXML has no dependency on the HTTP
client. EnhancedPatentClient delegates here to keep its public surface.
"""
import re
from typing import List, Optional, Tuple

# defusedxml: hardens against XXE / entity-expansion in USPTO-served XML (audit L12)
import defusedxml.ElementTree as ET

#: Description is summarized to its first N paragraphs. The cap itself is
#: unchanged (default response sizes stay what they were); what changed is that
#: the response now SAYS so — `description` used to be a plain key holding a
#: 5-paragraph excerpt of a 300-paragraph specification with no marker at all,
#: so a caller reading it as "the description" was silently reading 1.7% of it.
DESCRIPTION_PARAGRAPH_LIMIT = 5

#: Same story for citations: a bare `citations[:10]` with no total.
CITATION_LIMIT = 10

#: Marker keys the extractors add alongside their content. Excluded from
#: `fields_included` so field discoverability keeps listing content fields only.
MARKER_KEYS = (
    "description_paragraphs_returned",
    "description_paragraphs_total",
    "description_note",
    "citations_returned",
    "citations_total",
    "citations_note",
    "citations_status",
    "citations_container",
    "npl_citations_total",
    "claims_independent_count",
    "claims_type_note",
)

#: Every element name USPTO has used for the references-cited container and its
#: per-reference child, across grant-XML generations.
#:
#: PROBE-VERIFIED 2026-08-30 (grant XML fetched from api.uspto.gov):
#:   US 7,971,071 (app 11752072, granted 2011) -> <references-cited> with 100
#:       <citation> children (91 <patcit>, 9 <nplcit>)
#:   US 9,135,462 (app 13975827, granted 2015) -> <us-references-cited> with 640
#:       <us-citation> children (529 <patcit>, 111 <nplcit>)
#:   US 9,496,922 (app 14257618, granted 2016) -> <us-references-cited> with 255
#:       <us-citation> children (251 <patcit>, 4 <nplcit>)
#: The extractor only ever looked for `.//citation`, so every grant issued
#: under the newer ICE schema reported citations_total: 0 with success: true
#: (OPEN_ITEMS #1). Both spellings are now read.
CITATION_ELEMENTS = ("citation", "us-citation")
REFERENCES_CONTAINERS = ("references-cited", "us-references-cited")

#: `citations_status` values. A zero must never again be indistinguishable
#: from a parse failure.
CITATIONS_PARSED = "parsed"          # a container was found and yielded citations
CITATIONS_UNAVAILABLE = "unavailable"  # this XML carries no references-cited block at all
CITATIONS_PARSE_FAILED = "parse_failed"  # a container exists but nothing was extracted

#: Claim-text markers for a dependent claim. A dependent claim refers to another
#: claim by number; an independent one does not. Derived from the text because
#: the previous `type` field was a keyword guess ("comprising:" / "wherein:" in
#: the body) that was wrong in BOTH directions (OPEN_ITEMS #2): on US 9,496,922
#: claim 16 ("The method of claim 14, comprising:") was labelled independent and
#: claim 17 ("A computer memory ... comprising instructions") dependent.
_DEPENDENCY_PATTERNS = (
    r"\b(?:of|in|to|per)\s+(?:any\s+(?:one\s+)?of\s+)?claims?\s+\d+",
    r"\baccording\s+to\s+(?:any\s+(?:one\s+)?of\s+)?claims?\s+\d+",
    r"\bas\s+(?:claimed|recited|defined|set\s+forth|described)\s+in\s+claims?\s+\d+",
    r"\bclaims?\s+\d+\s*,?\s*(?:wherein|further|above)",
)
_DEPENDENCY_RE = re.compile("|".join(_DEPENDENCY_PATTERNS), re.IGNORECASE)


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
            structured.update(_claims_block(root))

        if "description" in include_fields:
            text, returned, total = _extract_description_with_counts(root)
            structured["description"] = text
            structured["description_paragraphs_returned"] = returned
            structured["description_paragraphs_total"] = total
            if total > returned:
                structured["description_note"] = (
                    f"Summary only: the first {returned} of {total} description "
                    "paragraphs. For the full specification use "
                    "PFW_get_application_documents(document_code='SPEC') plus "
                    "PFW_get_document_content_with_ocr, or read raw_xml "
                    "(include_raw_xml=True)."
                )

        if "inventors" in include_fields:
            structured["inventors"] = _extract_inventors(root)

        if "applicants" in include_fields:
            structured["applicants"] = _extract_applicants(root)

        if "classifications" in include_fields:
            structured["classifications"] = _extract_classifications(root)

        if "citations" in include_fields:
            structured.update(_citations_block(root))

        if "publication_info" in include_fields:
            structured["publication_info"] = _extract_publication_info(root)

        return structured

    except Exception as e:
        return {
            "error": f"XML parsing failed: {str(e)}",
            "raw_available": True
        }

def _claims_block(root) -> dict:
    """The `claims` field plus its derived-type bookkeeping."""
    claims = _extract_claims(root)
    return {
        "claims": claims,
        "claims_independent_count": sum(
            1 for c in claims if c.get("type_derived") == "independent"
        ),
        "claims_type_note": (
            "`type` == `type_derived`, derived from the claim text (a dependent claim "
            "refers to another claim by number) and from the XML's own <claim-ref> "
            "links. `type_reported` is the old keyword guess kept for comparison only; "
            "it was wrong in both directions and is NOT authoritative."
        ),
    }


def _citations_block(root) -> dict:
    """The `citations` field plus counts, status and the matching note."""
    block: dict = {}
    citations, total, status, container, npl_total = _extract_citations_with_counts(root)
    block["citations"] = citations
    block["citations_returned"] = len(citations)
    block["citations_total"] = total
    block["citations_status"] = status
    block["citations_container"] = container
    block["npl_citations_total"] = npl_total
    if status == CITATIONS_UNAVAILABLE:
        block["citations_note"] = (
            "citations_total is 0 because this XML carries no references-cited "
            "block at all (pre-grant publication XML normally does not). This is "
            "an absence of data, not a parse failure. For the citation record use "
            "the uspto_enriched_citation_mcp tools, or "
            "PFW_get_application_documents(document_code='892'|'1449')."
        )
    elif status == CITATIONS_PARSE_FAILED:
        block["citations_note"] = (
            f"A <{container}> block IS present in this XML but no patent citation "
            "could be parsed out of it. Treat citations_total=0 as a PARSE FAILURE, "
            "not as 'this patent cites nothing'. Use the "
            "uspto_enriched_citation_mcp tools or "
            "PFW_get_application_documents(document_code='892'|'1449')."
        )
    elif total > len(citations):
        block["citations_note"] = (
            f"Showing the first {len(citations)} of {total} patent citations "
            f"found in this XML (plus {npl_total} non-patent citations, which are "
            "counted but not listed). For the complete citation record use the "
            "uspto_enriched_citation_mcp tools, or "
            "PFW_get_application_documents(document_code='892'|'1449')."
        )
    return block


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

    # Fields actually included (from structured_content, excluding xml_type,
    # error bookkeeping, and the description/citation truncation markers)
    fields_included = [
        k for k in structured_content.keys()
        if k not in ["xml_type", "error", "raw_available"] and k not in MARKER_KEYS
    ]

    metadata = {
        "fields_included": fields_included,
        "fields_available": all_fields,
        "using_default": include_fields is None
    }

    # Add simple hint if using defaults (for LLM discoverability)
    if include_fields is None:
        metadata["note"] = "Using default fields (abstract, claims, description). Add include_fields=['inventors', 'applicants'] for entity info. raw_xml is OFF by default since 2026-08-21 (~50K tokens) — pass include_raw_xml=True only for debugging or custom XML parsing. See PFW_get_guidance(section='tools') for all options"
    else:
        metadata["note"] = "Custom fields selected. raw_xml is OFF by default since 2026-08-21 (~50K tokens) — pass include_raw_xml=True only if you need the source XML."

    return metadata

def _extract_abstract(root) -> str:
    """Extract abstract text from XML"""
    abstract_elem = root.find('.//abstract')
    if abstract_elem is not None:
        return ' '.join(abstract_elem.itertext()).strip()
    return "Abstract not found"

def derive_claim_type(claim_text: str, has_claim_ref: bool = False) -> str:
    """independent / dependent, derived from what the claim actually says.

    A dependent claim refers to another claim by number ("of claim 3",
    "according to claim 3", "as claimed in claim 3"); an independent one does
    not. USPTO grant XML also links the dependency explicitly with a
    <claim-ref idref="CLM-000NN"> element, which is used as a second signal.
    """
    if has_claim_ref:
        return "dependent"
    return "dependent" if _DEPENDENCY_RE.search(claim_text or "") else "independent"


def _reported_claim_type(claim_text: str) -> str:
    """The pre-2026-08-30 keyword guess, kept only so a caller can see what it
    said. It looked for "comprising:"/"wherein:" anywhere in the body, which is
    not a property of independence at all."""
    return "independent" if "comprising:" in claim_text or "wherein:" in claim_text else "dependent"


def _extract_claims(root) -> list:
    """Extract all claims from XML.

    Each claim carries `type_reported` (the old keyword guess), `type_derived`
    (from the claim text and the XML's <claim-ref> links) and `type`, which is
    an alias of `type_derived` — the derived value is the authoritative one
    (OPEN_ITEMS #2).
    """
    claims = []
    for claim in root.findall('.//claim'):
        claim_num = claim.get('num', 'Unknown')
        claim_text = ' '.join(claim.itertext()).strip()
        refs = [
            ref.get('idref') for ref in claim.findall('.//claim-ref')
            if ref.get('idref')
        ]
        derived = derive_claim_type(claim_text, has_claim_ref=bool(refs))
        claims.append({
            "number": claim_num,
            "text": claim_text,
            "type": derived,
            "type_derived": derived,
            "type_reported": _reported_claim_type(claim_text),
            "depends_on": refs,
        })
    return claims

def _extract_description(root) -> str:
    """Extract description/specification text (capped summary; see
    _extract_description_with_counts for the returned/total counters)."""
    return _extract_description_with_counts(root)[0]


def _extract_description_with_counts(root) -> Tuple[str, int, int]:
    """Return (summary_text, paragraphs_returned, paragraphs_total).

    The text is still the first DESCRIPTION_PARAGRAPH_LIMIT paragraphs — the
    counters exist so the caller can see how much of the specification that
    actually is.
    """
    desc_elem = root.find('.//description')
    if desc_elem is None:
        return "Description not found", 0, 0
    all_paragraphs = desc_elem.findall('.//p')
    paragraphs = all_paragraphs[:DESCRIPTION_PARAGRAPH_LIMIT]
    text = '\n\n'.join([' '.join(p.itertext()).strip() for p in paragraphs])
    return text, len(paragraphs), len(all_paragraphs)

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
    """Extract patent citations (capped; see _extract_citations_with_counts
    for the total actually present in the XML)."""
    return _extract_citations_with_counts(root)[0]


def _citation_container(root) -> Optional[str]:
    """Name of the references-cited container present in this XML, or None."""
    for name in REFERENCES_CONTAINERS:
        if root.find(f'.//{name}') is not None:
            return name
    return None


def _extract_citations_with_counts(root) -> Tuple[list, int, str, Optional[str], int]:
    """Return (citations_capped, patent_citations_total, status, container, npl_total).

    Reads BOTH element spellings: <citation> (pre-ICE grants) and <us-citation>
    (2013+ grants). Only patent citations (<patcit>) are listed and counted in
    `citations_total`, unchanged; non-patent literature (<nplcit>) is counted
    separately so nothing is silently dropped.
    """
    citations = []
    npl_total = 0
    for element in CITATION_ELEMENTS:
        for cite in root.findall(f'.//{element}'):
            patent_cite = cite.find('.//patcit')
            if patent_cite is not None:
                doc_num = patent_cite.findtext('.//doc-number', '')
                if doc_num:
                    citations.append({
                        "type": "patent",
                        "number": doc_num.strip()
                    })
            elif cite.find('.//nplcit') is not None:
                npl_total += 1

    container = _citation_container(root)
    if citations or npl_total:
        status = CITATIONS_PARSED
    elif container is None:
        status = CITATIONS_UNAVAILABLE
    else:
        status = CITATIONS_PARSE_FAILED
    return citations[:CITATION_LIMIT], len(citations), status, container, npl_total

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
