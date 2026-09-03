"""Registration tokens must be bound to the resource they authorize (audit H-1),
and must not be replayable (audit L-4).

Before this, `/register-ptab-document` validated the HMAC and the issuing
service and then went straight to spending PFW's own shared USPTO key on a
caller-chosen uspto.gov URL, under a caller-chosen proceeding number. The FPD
twin already carried the binding check, which is what proved the omission was
copy-paste drift rather than design.
"""

import pytest
from httpx import ASGITransport, AsyncClient

_SECRET = "test-internal-auth-secret-for-registration-binding"


@pytest.fixture(autouse=True)
def _internal_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_AUTH_SECRET", _SECRET)
    # The auth manager is a lazily built module singleton; drop it so each test
    # gets a token issuer bound to this secret and a fresh replay guard.
    from patent_filewrapper_mcp.shared import internal_auth

    monkeypatch.setattr(internal_auth, "_pfw_auth_instance", None, raising=False)
    yield
    monkeypatch.setattr(internal_auth, "_pfw_auth_instance", None, raising=False)


@pytest.fixture
def proxy_app():
    # The registration routes share ONE process-global per-IP bucket at
    # 10 req/min, so without this reset the later cases in this module answer
    # 429 instead of exercising the token gate.
    from patent_filewrapper_mcp.proxy.rate_limiter import rate_limiter
    from patent_filewrapper_mcp.proxy.server import create_proxy_app

    rate_limiter.requests.clear()
    return create_proxy_app()


def _mint(service, metadata):
    from patent_filewrapper_mcp.shared.internal_auth import InternalAuthToken

    return InternalAuthToken(_SECRET).create_token(
        service_name=service, metadata=metadata
    )


# petition_id is a fixed-length UUID per FPDDocumentRegistration.
_PETITION_ID = "11111111-2222-3333-4444-555555555555"
_OTHER_PETITION_ID = "99999999-8888-7777-6666-555555555555"


def _fpd_body(token, **overrides):
    body = {
        "source": "fpd",
        "petition_id": _PETITION_ID,
        "document_identifier": "DOC-1",
        "download_url": "https://api.uspto.gov/api/v1/download/applications/1.pdf",
        "access_token": token,
    }
    body.update(overrides)
    return body


def _ptab_body(token, **overrides):
    body = {
        "source": "ptab",
        "proceeding_number": "IPR2025-01054",
        "document_identifier": "DOC-1",
        "download_url": "https://api.uspto.gov/api/v1/download/applications/1.pdf",
        "access_token": token,
    }
    body.update(overrides)
    return body


async def _post(app, path, body):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=body)


@pytest.mark.asyncio
class TestResourceBinding:
    async def test_ptab_token_for_another_document_is_rejected(self, proxy_app):
        """The core H-1 case: a valid ptab-mcp token minted for DOC-OTHER must
        not register DOC-1."""
        token = _mint("ptab-mcp", {"source": "ptab", "document_id": "DOC-OTHER"})
        resp = await _post(proxy_app, "/register-ptab-document", _ptab_body(token))
        assert resp.status_code == 401, (
            f"Expected 401 for a token minted for a different document, got "
            f"{resp.status_code}. The resource binding was dropped."
        )

    async def test_ptab_token_for_another_proceeding_is_rejected(self, proxy_app):
        token = _mint(
            "ptab-mcp",
            {
                "type": "document_access",
                "identifier": "IPR2099-99999",
                "document_identifier": "DOC-1",
            },
        )
        resp = await _post(proxy_app, "/register-ptab-document", _ptab_body(token))
        assert resp.status_code == 401

    async def test_ptab_token_with_no_binding_is_rejected(self, proxy_app):
        """Fail closed: empty metadata must not be read as 'nothing to check'."""
        token = _mint("ptab-mcp", {})
        resp = await _post(proxy_app, "/register-ptab-document", _ptab_body(token))
        assert resp.status_code == 401

    async def test_fpd_token_for_another_document_is_rejected(self, proxy_app):
        token = _mint(
            "fpd-mcp",
            {
                "type": "document_access",
                "petition_id": _PETITION_ID,
                "document_identifier": "DOC-OTHER",
            },
        )
        resp = await _post(proxy_app, "/register-fpd-document", _fpd_body(token))
        assert resp.status_code == 401

    async def test_fpd_token_for_another_petition_is_rejected(self, proxy_app):
        token = _mint(
            "fpd-mcp",
            {
                "type": "document_access",
                "petition_id": _OTHER_PETITION_ID,
                "document_identifier": "DOC-1",
            },
        )
        resp = await _post(proxy_app, "/register-fpd-document", _fpd_body(token))
        assert resp.status_code == 401

    async def test_fpd_token_with_no_binding_is_rejected(self, proxy_app):
        token = _mint("fpd-mcp", {"type": "document_access"})
        resp = await _post(proxy_app, "/register-fpd-document", _fpd_body(token))
        assert resp.status_code == 401

    async def test_wrong_token_type_is_rejected(self, proxy_app):
        token = _mint(
            "fpd-mcp",
            {
                "type": "service_call",
                "petition_id": _PETITION_ID,
                "document_identifier": "DOC-1",
            },
        )
        resp = await _post(proxy_app, "/register-fpd-document", _fpd_body(token))
        assert resp.status_code == 401

    async def test_matching_token_passes_the_binding_gate(self, proxy_app):
        """A correctly bound token must get PAST the auth gate. Registration
        itself needs a USPTO key and a writable store, so this asserts only
        that the answer is no longer 401."""
        token = _mint(
            "fpd-mcp",
            {
                "type": "document_access",
                "petition_id": _PETITION_ID,
                "document_identifier": "DOC-1",
            },
        )
        resp = await _post(proxy_app, "/register-fpd-document", _fpd_body(token))
        assert resp.status_code != 401, (
            "A token minted for exactly this petition and document was rejected"
        )

    async def test_deployed_ptab_service_token_shape_still_works(self, proxy_app):
        """uspto_ptab_mcp's live path mints create_service_token with metadata
        {source, document_id} and no `type`. The binding must be enforceable
        against that shape, not only against FPD's document_access shape."""
        token = _mint("ptab-mcp", {"source": "ptab", "document_id": "DOC-1"})
        resp = await _post(proxy_app, "/register-ptab-document", _ptab_body(token))
        assert resp.status_code != 401


@pytest.mark.asyncio
class TestReplay:
    async def test_a_registration_token_cannot_be_replayed(self, proxy_app):
        """Tokens carry no per-use state upstream, so an observed one was good
        for its whole 5-minute TTL (audit L-4)."""
        token = _mint("ptab-mcp", {"source": "ptab", "document_id": "DOC-1"})
        first = await _post(proxy_app, "/register-ptab-document", _ptab_body(token))
        assert first.status_code != 401
        second = await _post(proxy_app, "/register-ptab-document", _ptab_body(token))
        assert second.status_code == 401, (
            f"Replay of an already-consumed token returned {second.status_code}"
        )


class TestReplayGuard:
    def test_jti_is_present_and_unique(self):
        from patent_filewrapper_mcp.shared.internal_auth import InternalAuthToken

        issuer = InternalAuthToken(_SECRET)
        seen = set()
        for _ in range(20):
            info = issuer.get_token_info(issuer.create_token("pfw-mcp"))
            assert info["jti"], "every token must carry a jti"
            seen.add(info["jti"])
        assert len(seen) == 20, "jti values collided"

    def test_expired_entries_are_pruned(self):
        from patent_filewrapper_mcp.shared.internal_auth import _ReplayGuard

        guard = _ReplayGuard()
        assert guard.consume("stale", expires_at=1) is True
        # Already past its expiry, so the next consume prunes it and the same
        # identity is accepted again rather than accumulating forever.
        assert guard.consume("other", expires_at=2**31) is True
        assert guard.consume("stale", expires_at=2**31) is True
        assert guard.consume("other", expires_at=2**31) is False

    def test_signature_identity_is_used_when_a_token_has_no_jti(self):
        """Siblings mint from an older vendored copy with no jti; single-use
        still has to work against those."""
        import base64
        import json

        from patent_filewrapper_mcp.shared.internal_auth import InternalAuthToken

        issuer = InternalAuthToken(_SECRET)
        token = issuer.create_token("fpd-mcp", metadata={"a": 1})
        data = json.loads(base64.b64decode(token))
        data["payload"].pop("jti")
        # An older vendored copy has no key_id either — it is a legacy
        # raw-root-HMAC signer, not just a no-jti one.
        data.pop("key_id", None)
        data["signature"] = __import__("hmac").new(
            _SECRET.encode(),
            json.dumps(data["payload"], sort_keys=True).encode(),
            __import__("hashlib").sha256,
        ).hexdigest()
        legacy = base64.b64encode(json.dumps(data).encode()).decode()

        assert issuer.validate_token(legacy, single_use=True)[0] is True
        assert issuer.validate_token(legacy, single_use=True)[0] is False
