"""Tests for the free-text variant tiers (2026-08-25 follow-up).

PFW_get_document_content_with_ocr used to read only the rasterized IFW PDF
render, so desktop users paid Mistral OCR for text the ODP API already serves
for free via the downloadOptionBag's .docx / xmlarchive / as-uploaded PDF
variants — and PyPDF2 on the raster render reported SUCCESS with every page
"[no text recovered]". These tests pin: the variant preference order, the
application-number check on every variant (one live xmlarchive fetch returned
another control number's CLM), and the all-empty PyPDF2 result being a failure.

Hermetic: fixture bytes only, no network, no USPTO key beyond a placeholder.
"""

import io
import tarfile
import zipfile

import pytest

from patent_filewrapper_mcp.api import enhanced_client as ec_mod
from patent_filewrapper_mcp.api import free_text_variants as ftv
from patent_filewrapper_mcp.api.enhanced_client import (
    PYPDF_EMPTY_PAGE_PLACEHOLDER,
    EnhancedPatentClient,
    _pypdf_body_text,
)

APP = "90016076"
OTHER_APP = "90020162"

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CUSTOM_NS = (
    'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"'
)
_USPTO_NS = 'xmlns:uscom="urn:us:gov:doc:uspto:common" xmlns:uspat="urn:us:gov:doc:uspto:patent"'

#: Realistic page text for the fake PyPDF2 reader (long enough for
#: is_good_extraction's alphabetic-ratio heuristic — see test_bounds_bug_fixes).
_PAGE_BODY = (
    "The claims stand rejected under thirty five United States Code section "
    "one hundred three as being unpatentable over the cited reference in view "
    "of the applicant admitted prior art of record on page %d. "
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    c = EnhancedPatentClient()
    c.mistral_api_key = None
    return c


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def build_docx(paragraphs, app_number=None, footnote=None):
    """Minimal OOXML zip. ``paragraphs`` is a list of run-lists; a run may be
    the string "<tab/>" to emit a w:tab."""
    body = ""
    for runs in paragraphs:
        body += "<w:p>" + "".join(
            "<w:r><w:tab/></w:r>" if run == "<tab/>" else f"<w:r><w:t xml:space=\"preserve\">{run}</w:t></w:r>"
            for run in runs
        ) + "</w:p>"
    document = f'<?xml version="1.0"?><w:document {_W}><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", document)
        if app_number is not None:
            zf.writestr(
                "docProps/custom.xml",
                f'<Properties {_CUSTOM_NS}><property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" '
                f'name="FormattedApplicationNumber"><vt:lpwstr>{app_number}</vt:lpwstr></property>'
                f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="3" name="controlNo">'
                f'<vt:lpwstr>29626143</vt:lpwstr></property></Properties>',
            )
        if footnote:
            zf.writestr(
                "word/footnotes.xml",
                f'<w:footnotes {_W}><w:footnote><w:p><w:r><w:t>{footnote}</w:t></w:r></w:p></w:footnote></w:footnotes>',
            )
    return buf.getvalue()


def build_tar(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def build_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def claims_xml(app_number, electronic=None):
    """Shape of a live incoming CLM member: metadata, OCR-confidence markup,
    Ins/Del amendment markup, and a header/footer bag."""
    attr = f' uscom:electronicText="{electronic}"' if electronic else ""
    return (
        f'<?xml version="1.0" encoding="utf-8"?><uspat:ClaimsDocument {_USPTO_NS}>'
        f"<uspat:DocumentMetadata><uscom:DocumentCode>CLM</uscom:DocumentCode>"
        f"<uscom:ApplicationNumberText{attr}>{app_number}</uscom:ApplicationNumberText>"
        f"<uscom:OfficialDate>2026-03-23</uscom:OfficialDate></uspat:DocumentMetadata>"
        f"<uspat:Claims><uscom:P>VII. PROPOSED AMENDMENTS</uscom:P>"
        f"<uspat:Claim><uspat:ClaimText>1. (Currently amended) A widget under "
        f'<uscom:OCRConfidenceData uscom:ocrConfidenceCode="5">§</uscom:OCRConfidenceData> 1.530 comprising a '
        f"<uscom:Ins>flanged</uscom:Ins> <uscom:Del>round</uscom:Del> base.</uspat:ClaimText></uspat:Claim>"
        f"</uspat:Claims><uscom:BoundaryDataBag><uscom:BoundaryData>"
        f"<uscom:HeaderText>Request for Ex Parte Reexamination</uscom:HeaderText>"
        f"<uscom:HeaderText>27</uscom:HeaderText></uscom:BoundaryData></uscom:BoundaryDataBag>"
        f"</uspat:ClaimsDocument>"
    ).encode()


def outgoing_xml(formatted, electronic):
    """Shape of a live outgoing (USPTO-authored) member: no OCR markup, the
    application number repeated per page in the boundary bag with "Page N"."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><uspat:OutgoingDocument {_USPTO_NS}>'
        f'<uspat:DocumentMetadata><uscom:DocumentCode>RNRC</uscom:DocumentCode>'
        f'<uscom:ApplicationNumberText uscom:electronicText="{electronic}">{formatted}</uscom:ApplicationNumberText>'
        f"</uspat:DocumentMetadata>"
        f"<uscom:P><uscom:Font>NOTICE OF INTENT TO ISSUE REEXAMINATION CERTIFICATE</uscom:Font></uscom:P>"
        f"<uscom:P>A substantial new question of patentability is raised.</uscom:P>"
        f"<uscom:BoundaryDataBag><uscom:BoundaryData><uscom:SpannedBoundaryData>"
        f"<uscom:HeaderText><uscom:ApplicationNumberText>{formatted}\tPage 2</uscom:ApplicationNumberText></uscom:HeaderText>"
        f"</uscom:SpannedBoundaryData></uscom:BoundaryData></uscom:BoundaryDataBag>"
        f"</uspat:OutgoingDocument>"
    ).encode()


SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><image href="p1.png"/></svg>'


# ---------------------------------------------------------------------------
# downloadOptionBag classification
# ---------------------------------------------------------------------------

_BASE = "https://api.uspto.gov/api/v1/download/applications/90016076"


def _bag(*kinds):
    """Live-shaped options. kinds: render, docx, xml, png, uploaded_pdf, uploaded_docx."""
    table = {
        "render": {"mimeTypeIdentifier": "PDF", "downloadUrl": f"{_BASE}/DOC1.pdf", "pageTotalQuantity": 9},
        "docx": {"mimeTypeIdentifier": "MS_WORD",
                 "downloadUrl": f"{_BASE}/DOC1/files/RX%20-%20Ex%20Parte%20Reexam%20Order%20-%20Granted.docx"},
        "xml": {"mimeTypeIdentifier": "XML", "downloadUrl": f"{_BASE}/DOC1/xmlarchive"},
        "png": {"mimeTypeIdentifier": "PNG", "downloadUrl": f"{_BASE}/DOC1/files/media_image1.png"},
        "uploaded_pdf": {"mimeTypeIdentifier": "PDF", "downloadUrl": f"{_BASE}/DOC1/files/48385b64.pdf"},
    }
    return [dict(table[k]) for k in kinds]


def test_classify_download_options_by_mime_and_url_shape():
    buckets = ftv.classify_download_options(_bag("render", "docx", "png", "xml", "uploaded_pdf"))
    assert [o["downloadUrl"] for o in buckets["render_pdf"]] == [f"{_BASE}/DOC1.pdf"]
    assert len(buckets["docx"]) == 1 and buckets["docx"][0]["mimeTypeIdentifier"] == "MS_WORD"
    assert [o["downloadUrl"] for o in buckets["xmlarchive"]] == [f"{_BASE}/DOC1/xmlarchive"]
    assert [o["downloadUrl"] for o in buckets["uploaded_pdf"]] == [f"{_BASE}/DOC1/files/48385b64.pdf"]
    # PNG page images are not a text variant
    assert sum(len(v) for v in buckets.values()) == 4


def test_classify_tolerates_junk():
    buckets = ftv.classify_download_options([None, {}, {"mimeTypeIdentifier": "PDF"}])
    assert buckets["render_pdf"] == [{"mimeTypeIdentifier": "PDF"}]


# ---------------------------------------------------------------------------
# Application-number verification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("90016076", "90016076"),
    ("90/016,076", "90016076"),
    ("90/016,076\tPage 2", "90016076"),
    ("18,500,100", "18500100"),
    ("Page 2", None),
    ("", None),
    (None, None),
])
def test_normalize_application_number(raw, expected):
    assert ftv.normalize_application_number(raw) == expected


def test_check_application_number_outcomes():
    assert ftv.check_application_number(["90016076", "90/016,076\tPage 3"], APP) == (True, [])
    assert ftv.check_application_number(["90016076", OTHER_APP], APP) == (False, [OTHER_APP])
    # No evidence at all is "unverified", not "mismatched"
    assert ftv.check_application_number([], APP) == (False, [])
    assert ftv.check_application_number(["Page 2"], APP) == (False, [])


# ---------------------------------------------------------------------------
# .docx variant
# ---------------------------------------------------------------------------

def test_docx_text_and_verification():
    data = build_docx([["NOTICE OF INTENT"], ["Claims 1 and 13 are confirmed."]], app_number="90/016,076")
    parsed = ftv.extract_docx(data, APP)
    assert parsed["text"] == "NOTICE OF INTENT\nClaims 1 and 13 are confirmed."
    assert parsed["extraction_method"] == "docx variant"
    assert parsed["application_number_verified"] is True


def test_docx_runs_join_without_inserted_spaces():
    """Word splits 'Patent Owner' into runs at formatting boundaries; joining
    runs with spaces (the naive approach) yields 'P atent O wner'."""
    data = build_docx([["P", "atent ", "O", "wner", "<tab/>", "waived"]])
    assert ftv.extract_docx(data, APP)["text"] == "Patent Owner\twaived"


def test_docx_mismatched_application_number_is_rejected():
    data = build_docx([["Some text"]], app_number="90/020,162")
    with pytest.raises(ftv.VariantMismatchError) as exc:
        ftv.extract_docx(data, APP)
    assert OTHER_APP in str(exc.value)


def test_docx_without_property_is_served_but_unverified():
    parsed = ftv.extract_docx(build_docx([["Some text"]]), APP)
    assert parsed["application_number_verified"] is False
    assert parsed["text"] == "Some text"


def test_docx_footnotes_follow_the_body():
    parsed = ftv.extract_docx(build_docx([["Body"]], footnote="Footnote one"), APP)
    assert parsed["text"] == "Body\n\nFootnote one"


def test_docx_with_no_text_is_empty():
    with pytest.raises(ftv.VariantEmptyError):
        ftv.extract_docx(build_docx([]), APP)


def test_docx_that_is_not_a_zip_raises():
    with pytest.raises(zipfile.BadZipFile):
        ftv.extract_docx(b"%PDF-1.7 not a docx", APP)


# ---------------------------------------------------------------------------
# xmlarchive variant
# ---------------------------------------------------------------------------

def _member(app, name="90016076.03-23-2026.DOC1.CLM.XML"):
    return f"{app}/DOC1/{name}"


def test_xmlarchive_claims_text_keeps_amendment_markup_and_drops_scaffolding():
    data = build_tar([(_member(APP), claims_xml(APP, electronic=APP))])
    parsed = ftv.extract_xmlarchive(data, APP)
    text = parsed["text"]
    assert "VII. PROPOSED AMENDMENTS" in text
    # Ins/Del delimited so amended claim text does not merge into gibberish;
    # low-confidence OCR characters are kept verbatim.
    assert "comprising a <ins>flanged</ins> <del>round</del> base." in text
    assert "under § 1.530" in text
    # Metadata and page header/footer bag are not document text
    assert "CLM" not in text
    assert "2026-03-23" not in text
    assert "Request for Ex Parte Reexamination" not in text
    assert parsed["extraction_method"] == "xmlarchive (USPTO OCR)"
    assert parsed["application_number_verified"] is True


def test_xmlarchive_outgoing_document_is_labeled_xml_not_ocr():
    data = build_tar([(f"{APP}/DOC1/RX - Ex Parte Notice.xml", outgoing_xml("90/016,076", APP))])
    parsed = ftv.extract_xmlarchive(data, APP)
    assert parsed["extraction_method"] == "xmlarchive (USPTO XML)"
    # Paragraphs (uscom:P) are separated by a blank line
    assert parsed["text"].startswith("NOTICE OF INTENT TO ISSUE REEXAMINATION CERTIFICATE\n\nA substantial")
    # The per-page "90/016,076\tPage 2" header is evidence, not a mismatch
    assert parsed["application_number_verified"] is True
    assert "Page 2" not in parsed["text"]


def test_xmlarchive_member_path_for_another_application_is_rejected():
    """The observed failure: an archive fetched for 90/016,076 that holds
    90/020,162's CLM. The path component disagrees with the request."""
    data = build_tar([(_member(OTHER_APP), claims_xml(OTHER_APP))])
    with pytest.raises(ftv.VariantMismatchError) as exc:
        ftv.extract_xmlarchive(data, APP)
    assert OTHER_APP in str(exc.value)


def test_xmlarchive_element_disagreeing_with_path_is_rejected():
    data = build_tar([(_member(APP), claims_xml(OTHER_APP, electronic=OTHER_APP))])
    with pytest.raises(ftv.VariantMismatchError):
        ftv.extract_xmlarchive(data, APP)


def test_xmlarchive_electronic_text_attribute_wins_over_display_text():
    # Display text formatted, electronicText plain — both normalize to the request
    data = build_tar([(_member(APP), claims_xml("90/016,076", electronic=APP))])
    assert ftv.extract_xmlarchive(data, APP)["application_number_verified"] is True


def test_xmlarchive_svg_only_members_are_empty():
    data = build_tar([(f"{APP}/DOC1/page1.svg", SVG), (f"{APP}/DOC1/page2.svg", SVG)])
    with pytest.raises(ftv.VariantEmptyError) as exc:
        ftv.extract_xmlarchive(data, APP)
    assert "SVG" in str(exc.value)


def test_xmlarchive_skips_svg_but_serves_xml_siblings():
    data = build_tar([(f"{APP}/DOC1/page1.svg", SVG), (_member(APP), claims_xml(APP))])
    parsed = ftv.extract_xmlarchive(data, APP)
    assert "PROPOSED AMENDMENTS" in parsed["text"]
    assert "<svg" not in parsed["text"]


def test_xmlarchive_zip_container_is_accepted():
    data = build_zip([(_member(APP), claims_xml(APP))])
    assert "PROPOSED AMENDMENTS" in ftv.extract_xmlarchive(data, APP)["text"]


def test_xmlarchive_without_any_evidence_is_unverified_not_rejected():
    xml = f'<Doc {_USPTO_NS}><uscom:P>Just text</uscom:P></Doc>'.encode()
    parsed = ftv.extract_xmlarchive(build_tar([("member.xml", xml)]), APP)
    assert parsed["text"] == "Just text"
    assert parsed["application_number_verified"] is False


# ---------------------------------------------------------------------------
# PyPDF2: an all-empty text layer is a FAILURE
# ---------------------------------------------------------------------------

class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    pages_to_serve = []

    def __init__(self, _stream):
        self.pages = _FakeReader.pages_to_serve


@pytest.fixture
def fake_pypdf(monkeypatch):
    import PyPDF2

    monkeypatch.setattr(PyPDF2, "PdfReader", _FakeReader)
    return _FakeReader


def test_pypdf_body_text_strips_headers_and_placeholders():
    text = f"=== PAGE 1 ===\n{PYPDF_EMPTY_PAGE_PLACEHOLDER}\n\n=== PAGE 2 ===\nreal words here"
    assert _pypdf_body_text(text) == "\nreal words here"


@pytest.mark.asyncio
async def test_pypdf_all_empty_pages_is_reported_as_failure(client, fake_pypdf):
    """Thirty placeholder lines used to pass is_good_extraction — the tool
    said "PyPDF2 successful" for a rasterized render with no text at all."""
    fake_pypdf.pages_to_serve = [_FakePage("") for _ in range(30)]
    status = {}
    text = await client.extract_with_pypdf2(b"%PDF-", status)
    assert status["pages_with_text"] == 0
    assert client.is_good_extraction(text), "sanity: the placeholder text alone fools the heuristic"
    assert await client._try_pypdf2_tier(b"%PDF-", "DOC1") is None


@pytest.mark.asyncio
async def test_pypdf_mostly_empty_pages_fall_through(client, fake_pypdf):
    fake_pypdf.pages_to_serve = [_FakePage("Fig. 1")] + [_FakePage("  ") for _ in range(29)]
    assert await client._try_pypdf2_tier(b"%PDF-", "DOC1") is None


@pytest.mark.asyncio
async def test_pypdf_real_text_still_succeeds(client, fake_pypdf):
    fake_pypdf.pages_to_serve = [_FakePage(_PAGE_BODY % i) for i in range(1, 4)] + [_FakePage("")]
    update = await client._try_pypdf2_tier(b"%PDF-", "DOC1")
    assert update["extraction_method"] == "PyPDF2"
    assert update["auto_optimization"] == "PyPDF2 successful - no OCR needed"
    assert "=== PAGE 4 ===\n" + PYPDF_EMPTY_PAGE_PLACEHOLDER in update["extracted_content"]


# ---------------------------------------------------------------------------
# Orchestration: preference order and what gets downloaded
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


def _wire(client, monkeypatch, options, served):
    """documentBag with one document DOC1 carrying ``options``; ``served``
    maps a URL substring to the bytes _download_once returns. Records URLs."""
    fetched = []

    async def fake_get_documents(app_number, *a, **k):
        return {"documentBag": [{
            "documentIdentifier": "DOC1", "documentCode": "RXNIRC",
            "documentCodeDescriptionText": "Notice of Intent", "officialDate": "2026-05-01T00:00:00",
            "downloadOptionBag": options,
        }]}

    async def fake_download_once(url):
        fetched.append(url)
        for needle, content in served.items():
            if needle in url:
                return _FakeResponse(content)
        raise AssertionError(f"unexpected download: {url}")

    monkeypatch.setattr(client, "get_documents", fake_get_documents)
    monkeypatch.setattr(client, "_download_once", fake_download_once)
    return fetched


@pytest.mark.asyncio
async def test_docx_is_preferred_and_the_render_is_never_downloaded(client, monkeypatch):
    fetched = _wire(client, monkeypatch, _bag("render", "docx", "png", "xml"), {
        ".docx": build_docx([["NIRC body text"]], app_number="90/016,076"),
        "xmlarchive": build_tar([(_member(APP), claims_xml(APP))]),
    })
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["success"] is True
    assert result["extraction_method"] == "docx variant"
    assert result["extracted_content"] == "NIRC body text"
    assert result["application_number_verified"] is True
    assert result["free_text_variants"] == [{"variant": "docx", "outcome": "used"}]
    # Page metadata comes from the documentBag, since no PDF was read
    assert result["page_count"] == 9 and result["page_count_source"] == "downloadOptionBag"
    assert result["document_code"] == "RXNIRC"
    assert fetched == [f"{_BASE}/DOC1/files/RX%20-%20Ex%20Parte%20Reexam%20Order%20-%20Granted.docx"]


@pytest.mark.asyncio
async def test_rejected_docx_falls_through_to_xmlarchive(client, monkeypatch):
    fetched = _wire(client, monkeypatch, _bag("render", "docx", "xml"), {
        ".docx": build_docx([["Wrong file"]], app_number="90/020,162"),
        "xmlarchive": build_tar([(_member(APP), claims_xml(APP))]),
    })
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["extraction_method"] == "xmlarchive (USPTO OCR)"
    assert "PROPOSED AMENDMENTS" in result["extracted_content"]
    assert [a["variant"] for a in result["free_text_variants"]] == ["docx", "xmlarchive"]
    assert result["free_text_variants"][0]["outcome"] == "rejected"
    assert OTHER_APP in result["free_text_variants"][0]["reason"]
    assert result["free_text_variants"][1] == {"variant": "xmlarchive", "outcome": "used"}
    assert not any(url.endswith("DOC1.pdf") for url in fetched)


@pytest.mark.asyncio
async def test_mismatched_xmlarchive_falls_through_to_the_render(client, monkeypatch, fake_pypdf):
    """The observed live failure end to end: the archive holds another control
    number's CLM, so the tool must NOT serve it and must go on to the PDF."""
    fake_pypdf.pages_to_serve = [_FakePage(_PAGE_BODY % i) for i in range(1, 4)]
    fetched = _wire(client, monkeypatch, _bag("render", "xml"), {
        "xmlarchive": build_tar([(_member(OTHER_APP), claims_xml(OTHER_APP))]),
        "DOC1.pdf": b"%PDF-",
    })
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["extraction_method"] == "PyPDF2"
    assert result["free_text_variants"][0]["outcome"] == "rejected"
    assert fetched[-1].endswith("DOC1.pdf")
    assert result["file_size_bytes"] == len(b"%PDF-")


@pytest.mark.asyncio
async def test_uploaded_pdf_text_layer_is_used_when_it_is_the_only_variant(client, monkeypatch, fake_pypdf):
    """APP.TEXT filings carry only files/<uuid>.pdf (+ .docx); no IFW render."""
    fake_pypdf.pages_to_serve = [_FakePage(_PAGE_BODY % i) for i in range(1, 3)]
    fetched = _wire(client, monkeypatch, _bag("uploaded_pdf"), {"files/48385b64.pdf": b"%PDF-"})
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["extraction_method"] == "as-uploaded pdf text layer"
    assert result["page_count"] == 2 and result["page_count_source"] == "pypdf"
    assert result["application_number_verified"] is False
    assert result["free_text_variants"] == [{"variant": "as-uploaded pdf", "outcome": "used"}]
    assert fetched == [f"{_BASE}/DOC1/files/48385b64.pdf"]


@pytest.mark.asyncio
async def test_uploaded_pdf_without_text_layer_falls_through(client, monkeypatch, fake_pypdf):
    fake_pypdf.pages_to_serve = [_FakePage("") for _ in range(3)]
    _wire(client, monkeypatch, _bag("uploaded_pdf"), {"files/48385b64.pdf": b"%PDF-"})
    monkeypatch.setattr(ec_mod, "DoclingClient", lambda: _NoDocling())
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["extraction_method"] == "failed"
    assert result["free_text_variants"][0]["outcome"] == "no text"


class _NoDocling:
    max_pages = 25

    def is_available(self):
        return False

    def within_page_limit(self, page_count):
        return True


@pytest.mark.asyncio
async def test_rasterized_render_with_no_variants_is_a_failure_not_a_success(client, monkeypatch, fake_pypdf):
    """The false-success case from the follow-up: bare IFW render, every
    page empty, no Mistral key, no Docling."""
    fake_pypdf.pages_to_serve = [_FakePage("") for _ in range(19)]
    _wire(client, monkeypatch, _bag("render"), {"DOC1.pdf": b"%PDF-"})
    monkeypatch.setattr(ec_mod, "DoclingClient", lambda: _NoDocling())
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["extraction_method"] == "failed"
    assert result["extracted_content"] == ""
    assert result["mistral_api_key_missing"] is True
    assert "free_text_variants" not in result  # nothing was offered, nothing was tried


@pytest.mark.asyncio
async def test_auto_optimize_false_skips_the_free_variants(client, monkeypatch):
    fetched = _wire(client, monkeypatch, _bag("render", "docx"), {
        ".docx": build_docx([["text"]]), "DOC1.pdf": b"%PDF-",
    })
    result = await client.extract_document_content_hybrid(APP, "DOC1", auto_optimize=False)
    assert result["extraction_method"] == "failed"
    assert result["mistral_api_key_missing"] is True
    assert "free_text_variants" not in result
    assert fetched == [f"{_BASE}/DOC1.pdf"]


@pytest.mark.asyncio
async def test_variant_download_failure_is_recorded_and_falls_through(client, monkeypatch, fake_pypdf):
    fake_pypdf.pages_to_serve = [_FakePage(_PAGE_BODY % i) for i in range(1, 3)]

    class _Boom(_FakeResponse):
        def raise_for_status(self):
            raise RuntimeError("HTTP 500")

    fetched = []

    async def fake_download_once(url):
        fetched.append(url)
        return _Boom(b"") if ".docx" in url else _FakeResponse(b"%PDF-")

    _wire(client, monkeypatch, _bag("render", "docx"), {})
    monkeypatch.setattr(client, "_download_once", fake_download_once)
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["extraction_method"] == "PyPDF2"
    assert result["free_text_variants"] == [
        {"variant": "docx", "outcome": "failed", "reason": "RuntimeError: HTTP 500"},
    ]


@pytest.mark.asyncio
async def test_download_failure_carries_the_variant_record(client, monkeypatch):
    class _Boom(_FakeResponse):
        def raise_for_status(self):
            raise RuntimeError("HTTP 500")

    async def fake_download_once(url):
        return _Boom(b"")

    _wire(client, monkeypatch, _bag("render", "xml"), {})
    monkeypatch.setattr(client, "_download_once", fake_download_once)
    result = await client.extract_document_content_hybrid(APP, "DOC1")
    assert result["success"] is False
    assert result["extraction_method"] == "download_failed"
    assert result["document_code"] == "RXNIRC"
    assert result["free_text_variants"][0]["variant"] == "xmlarchive"
