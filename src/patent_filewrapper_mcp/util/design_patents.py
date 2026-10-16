"""Design-patent detection and the one routing sentence that follows from it.

A design patent's claim is a single sentence -- "The ornamental design for a
candy, as shown and described." -- and it is not the claim. The drawings are.
A model that pulls the XML, reads that sentence and answers has answered
nothing, and nothing in the payload tells it so unless we do.

So the sentence lives here once and rides out on the return path of every
tool that can put a design record in a model's hands, GATED on the record
actually being a design patent. A note attached unconditionally trains the
consuming model to ignore it; this one is absent on the far larger number of
utility records, which is what makes it worth reading when it appears.
"""

from typing import Any, Dict, Iterable, Optional

#: Design applications are filed in the 29 series; design patents are printed
#: with a D prefix. Either is sufficient on its own.
DESIGN_SERIES_PREFIX = "29"
DESIGN_PATENT_PREFIX = "D"

DESIGN_DRAWINGS_NOTE = (
    "DESIGN PATENT: the claim is the drawings. A design patent claims one "
    "thing, in one sentence that names the article and then says 'as shown "
    "and described' -- the scope lives entirely in the sheets, where SOLID "
    "lines are the claimed design and BROKEN lines are unclaimed environment. "
    "Quoting the claim text alone describes nothing and compares nothing. "
    "List the drawing sheets with PFW_get_application_documents(app_number="
    "<this application>, document_code='DRW') and give the reader the sheets "
    "with PFW_get_document_download; do not OCR them, a drawing sheet yields "
    "only stray reference numerals."
)

#: Same fact, said where the document bag is the thing in hand.
DESIGN_DOCUMENTS_NOTE = (
    "DESIGN PATENT: the claim is the drawings, so the DRW documents in this "
    "bag are the substance of the patent and not an illustration of it. "
    "Give the reader the sheets with PFW_get_document_download rather than "
    "running text extraction on them (a drawing sheet yields only stray "
    "reference numerals). When the bag holds several DRW filings, the "
    "earlier ones are usually the priority-chain drawings."
)


def is_design_application(application_number: Optional[str]) -> bool:
    """True for a 29-series application number (the US design series).

    Hague design applications (35 series) are deliberately NOT included: they
    are design filings, but the 35 series also carries other work and the
    note is only worth firing where it is certainly true.
    """
    digits = "".join(ch for ch in str(application_number or "") if ch.isdigit())
    return digits.startswith(DESIGN_SERIES_PREFIX) and len(digits) >= 8


def is_design_patent_number(patent_number: Optional[str]) -> bool:
    """True for a D-prefixed patent number ('D618677', 'D618,677', 'USD618677')."""
    value = str(patent_number or "").strip().upper().lstrip("US").strip()
    return value.startswith(DESIGN_PATENT_PREFIX) and any(ch.isdigit() for ch in value)


def claims_ornamental_design(texts: Iterable[Any]) -> bool:
    """True when any supplied claim text reads as a design claim."""
    for text in texts:
        if isinstance(text, str) and "ornamental design" in text.lower():
            return True
    return False


def looks_like_design_record(
    application_number: Optional[str] = None,
    patent_number: Optional[str] = None,
    claim_texts: Optional[Iterable[Any]] = None,
) -> bool:
    """Any one signal is enough; all three are cheap and none needs a call."""
    return (
        is_design_application(application_number)
        or is_design_patent_number(patent_number)
        or claims_ornamental_design(claim_texts or ())
    )


def iter_claim_texts(structured_content: Any) -> Iterable[str]:
    """Claim strings out of the XML tool's structured_content, shape-tolerant."""
    claims = (structured_content or {}).get("claims") if isinstance(structured_content, dict) else None
    if isinstance(claims, str):
        yield claims
        return
    for claim in claims if isinstance(claims, list) else ():
        if isinstance(claim, str):
            yield claim
        elif isinstance(claim, dict):
            for key in ("text", "claim_text", "claimText"):
                value = claim.get(key)
                if isinstance(value, str):
                    yield value


def attach_design_note(result: Dict[str, Any], note: str) -> Dict[str, Any]:
    """Attach the note under `design_patent_note`, never overwriting one."""
    result.setdefault("design_patent_note", note)
    return result


__all__ = [
    "DESIGN_DOCUMENTS_NOTE",
    "DESIGN_DRAWINGS_NOTE",
    "attach_design_note",
    "claims_ornamental_design",
    "is_design_application",
    "is_design_patent_number",
    "iter_claim_texts",
    "looks_like_design_record",
]
