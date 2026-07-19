"""SSRF hardening for FPD/PTAB registration download URLs (audit H2).

The proxy attaches the real USPTO API key when fetching download_url, so the
validator must parse the hostname — substring checks let attacker-controlled
hosts through.
"""

import pytest
from pydantic import ValidationError

from patent_filewrapper_mcp.proxy.models import (
    FPDDocumentRegistration,
    PTABDocumentRegistration,
)

VALID_FPD = dict(
    source="fpd",
    petition_id="12345678-1234-1234-1234-123456789abc",
    document_identifier="DOC1",
    access_token="tok-0123456789",
)
VALID_PTAB = dict(
    source="ptab",
    proceeding_number="IPR2025-00895",
    document_identifier="DOC1",
    access_token="tok-0123456789",
)

GOOD_URLS = [
    "https://api.uspto.gov/api/v1/download/abc.pdf",
    "https://beta.api.uspto.gov/some/path",
    "https://uspto.gov/download",
]

BAD_URLS = [
    "https://evil.example/uspto.gov",            # domain in path
    "https://uspto.gov.evil.com/download",       # suffix-spoofed host
    "https://api-uspto.gov/download",            # lookalike host
    "https://evil.example/?x=api.uspto.gov",     # domain in query
    "http://api.uspto.gov/download",             # not https
    "https://user@evil.example/api.uspto.gov",   # userinfo trick
]


@pytest.mark.parametrize("url", GOOD_URLS)
def test_valid_uspto_urls_accepted(url):
    assert FPDDocumentRegistration(**VALID_FPD, download_url=url).download_url == url
    assert PTABDocumentRegistration(**VALID_PTAB, download_url=url).download_url == url


@pytest.mark.parametrize("url", BAD_URLS)
def test_non_uspto_urls_rejected(url):
    with pytest.raises(ValidationError):
        FPDDocumentRegistration(**VALID_FPD, download_url=url)
    with pytest.raises(ValidationError):
        PTABDocumentRegistration(**VALID_PTAB, download_url=url)
