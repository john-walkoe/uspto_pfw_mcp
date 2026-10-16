"""The 2026-09 Mistral key shape (prefix_<32>_<suffix>, 45 chars) must be redacted
whole; the classic bare-32 pattern alone would leave the prefix and suffix in the log."""
from patent_filewrapper_mcp.shared.log_sanitizer import sanitize_string

FAKE = "mstrx_Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1W_Xy12Zq"  # synthetic, not a real key


def test_new_shape_is_redacted_whole() -> None:
    out = sanitize_string(f"mistral auth failed for key {FAKE} at 12:00")
    assert FAKE not in out
    assert "mstrx_" not in out and "_Xy12Zq" not in out
    assert "[MISTRAL_API_KEY]" in out or "[TOKEN]" in out  # the urlsafe-token rule may claim it first; either way it is gone


def test_classic_shape_still_redacted() -> None:
    classic = "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv"
    assert classic not in sanitize_string(f"key {classic} rejected")
