"""A persistent link is a tokenless bearer capability; it must be bounded and
revocable, and /cache/stats must not hand one out (audit M-1, M-2).

The hash IS the credential: GET /document/persistent/{hash} carries no
X-Proxy-Token by design, so anything that prints a full hash converts a scoped
server credential into a public URL.
"""

import pytest

from patent_filewrapper_mcp.proxy.secure_link_cache import SecureLinkCache


@pytest.fixture
def cache(tmp_path):
    return SecureLinkCache(
        cache_duration_days=1, db_path=str(tmp_path / "links.db"), max_uses=3
    )


def _hash_of(url):
    return url.rsplit("/", 1)[-1]


class TestUseCeiling:
    def test_a_link_stops_resolving_past_its_use_ceiling(self, cache):
        link_hash = _hash_of(cache.generate_persistent_link("16816197", "DOC-1"))

        for use in range(3):
            assert cache.resolve_persistent_link(link_hash) is not None, (
                f"use {use + 1} of 3 was refused"
            )

        assert cache.resolve_persistent_link(link_hash) is None, (
            "the 4th resolve of a max_uses=3 link succeeded; the ceiling is not "
            "enforced and a leaked hash is unlimited-use"
        )

    def test_an_exhausted_link_is_removed_not_merely_refused(self, cache):
        link_hash = _hash_of(cache.generate_persistent_link("16816197", "DOC-1"))
        for _ in range(4):
            cache.resolve_persistent_link(link_hash)
        assert cache.get_cache_stats()["total_links"] == 0

    def test_max_uses_zero_disables_the_ceiling(self, tmp_path):
        cache = SecureLinkCache(
            db_path=str(tmp_path / "links.db"), max_uses=0
        )
        link_hash = _hash_of(cache.generate_persistent_link("16816197", "DOC-1"))
        for _ in range(30):
            assert cache.resolve_persistent_link(link_hash) is not None


class TestRevocation:
    def test_revoke_link_makes_the_hash_stop_working(self, cache):
        link_hash = _hash_of(cache.generate_persistent_link("16816197", "DOC-1"))
        assert cache.resolve_persistent_link(link_hash) is not None

        assert cache.revoke_link(link_hash) is True
        assert cache.resolve_persistent_link(link_hash) is None, (
            "a revoked link still resolves"
        )

    def test_revoking_an_unknown_hash_reports_false_without_raising(self, cache):
        assert cache.revoke_link("0123456789abcdef01234567") is False


class TestDefaults:
    def test_the_default_lifetime_is_one_day_not_seven(self, tmp_path):
        cache = SecureLinkCache(db_path=str(tmp_path / "links.db"))
        assert cache.cache_duration.days == 1, (
            "the 7-day default made a leaked hash a working credential for a "
            "week with no ceiling and no revocation"
        )

    def test_the_default_carries_a_use_ceiling(self, tmp_path):
        cache = SecureLinkCache(db_path=str(tmp_path / "links.db"))
        assert cache.max_uses > 0


class TestStatsDisclosure:
    def test_stats_never_return_a_full_link_hash(self, cache):
        link_hash = _hash_of(cache.generate_persistent_link("16816197", "DOC-1"))
        cache.resolve_persistent_link(link_hash)

        stats = cache.get_cache_stats()
        most = stats["most_accessed"]

        assert "hash" not in most, "the full link hash is still returned"
        assert most["hash_prefix"] == f"{link_hash[:8]}..."
        assert link_hash not in str(stats), (
            "the full hash appears somewhere in the stats payload"
        )

    def test_stats_do_not_disclose_the_database_path(self, cache):
        stats = cache.get_cache_stats()
        assert "database_path" not in stats
        assert cache.db_path not in str(stats)

    def test_stats_report_the_active_bounds(self, cache):
        stats = cache.get_cache_stats()
        assert stats["cache_duration_days"] == 1
        assert stats["max_uses"] == 3

    def test_stats_with_no_links_do_not_crash(self, cache):
        assert cache.get_cache_stats()["most_accessed"] is None
