"""The security log keeps client IPs, and mcp_users mutations are audited.

Two findings from the 2026-09-03 review:

- M-16: the shared sanitizer masked IPv4 to two octets on every sink,
  including security.log, so the auth-failure and rate-limit records whose
  entire purpose is naming an abusive client could not attribute one. The
  threshold alerts also count per IP.
- M-15: no audit record for any `mcp_users` mutation, on the table PFW hosts
  and PTAB and FPD read.
"""

import logging
from datetime import datetime, timezone

import pytest

import patent_filewrapper_mcp.tools.admin_tools as admin_module
from patent_filewrapper_mcp.shared.log_sanitizer import LogSanitizer, SanitizingFilter
from patent_filewrapper_mcp.tools.admin_tools import pfw_manage_users
from patent_filewrapper_mcp.util.security_logger import SecurityLogger

_LINE = "auth failure from 203.0.113.9 key=abcdefghijklmnopqrstuvwxyz0123"


def test_default_sanitizer_still_masks_client_ips():
    assert "203.0.***.***" in LogSanitizer().sanitize_string(_LINE)


def test_security_sanitizer_keeps_the_client_ip():
    assert "203.0.113.9" in LogSanitizer(mask_ips=False).sanitize_string(_LINE)


def test_security_sanitizer_still_masks_secrets():
    result = LogSanitizer(mask_ips=False).sanitize_string(_LINE)

    assert "abcdefghijklmnopqrstuvwxyz0123" not in result
    assert "[USPTO_API_KEY]" in result


def test_filter_uses_the_sanitizer_it_was_given():
    record = logging.LogRecord(
        "security", logging.INFO, __file__, 1, _LINE, None, None
    )

    SanitizingFilter(LogSanitizer(mask_ips=False)).filter(record)

    assert "203.0.113.9" in record.msg


def test_security_handlers_carry_an_unmasked_ip_sanitizer(tmp_path):
    security = SecurityLogger(log_dir=str(tmp_path), enable_alerting=False)

    filters = [f for h in security.logger.handlers for f in h.filters
               if isinstance(f, SanitizingFilter)]
    assert filters, "security handlers lost their sanitizing filter"
    assert all(f.sanitizer.mask_ips is False for f in filters)


class _FakeUserStore:
    def __init__(self):
        self._users = {}

    async def upsert_user(self, email, role="user", display_name=None,
                          notes=None, active=True):
        existing = self._users.get(email, {})
        self._users[email] = {
            "email": email,
            "display_name": display_name,
            "role": role,
            "active": active,
            "added_at": existing.get("added_at", datetime.now(timezone.utc)),
            "last_login_at": None,
            "last_login_idp": None,
            "notes": notes,
        }

    async def get_user(self, email):
        return self._users.get(email)

    async def set_active(self, email, active):
        if email not in self._users:
            return False
        self._users[email]["active"] = active
        return True

    async def list_users(self):
        return list(self._users.values())


@pytest.fixture
def audited(monkeypatch):
    """Fake store plus a capture of every audit event the tool emits."""
    store = _FakeUserStore()
    monkeypatch.setattr(admin_module, "_get_user_store", lambda: store)
    events = []
    monkeypatch.setattr(
        admin_module.security_logger, "log_admin_action",
        lambda **kwargs: events.append(kwargs),
    )
    return events


@pytest.mark.parametrize(
    "action,kwargs",
    [
        ("add", {"role": "admin"}),
        ("set_role", {"role": "admin"}),
        ("activate", {}),
        ("deactivate", {}),
    ],
)
async def test_every_mutation_is_audited(audited, action, kwargs):
    await pfw_manage_users(action="add", email="alice@example.com", role="user")
    audited.clear()

    await pfw_manage_users(action=action, email="alice@example.com", **kwargs)

    assert [e["action"] for e in audited] == [action]
    assert audited[0]["target"] == "alice@example.com"
    assert audited[0]["success"] is True


async def test_list_is_not_audited(audited):
    await pfw_manage_users(action="list")

    assert audited == []


async def test_failed_mutation_is_audited_as_a_failure(audited):
    result = await pfw_manage_users(action="deactivate", email="nobody@example.com")

    assert "error" in result
    assert audited[0]["success"] is False
