"""scripts/pip_audit_gate.py: the CI gate that fails on High and Critical
advisories (audit 2026-10-12 M3). No network: the OSV lookup is a stub."""

import importlib.util
import json
import pathlib

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pip_audit_gate.py"
_spec = importlib.util.spec_from_file_location("pip_audit_gate", _PATH)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _report(*vulns):
    return {"dependencies": [
        {"name": name, "version": "1.0", "vulns": [{"id": vid, "aliases": aliases, "fix_versions": ["2.0"]}]}
        for name, vid, aliases in vulns
    ]}


_SEVERITY = {"GHSA-high": "HIGH", "GHSA-crit": "CRITICAL", "GHSA-mod": "MODERATE"}


def test_high_and_critical_are_fatal_lower_ones_are_not():
    report = _report(("a", "PYSEC-1", ["GHSA-high"]), ("b", "PYSEC-2", ["GHSA-crit", "CVE-1"]),
                     ("c", "PYSEC-3", ["GHSA-mod"]), ("d", "PYSEC-4", ["CVE-2"]))
    fatal, advisory = gate.classify(report, _SEVERITY.get)
    assert [line.split()[0] for line in fatal] == ["a", "b"]
    assert [line.split()[0] for line in advisory] == ["c", "d"]
    assert "severity=unknown" in advisory[1]


def test_an_ignored_id_is_not_fatal():
    fatal, advisory = gate.classify(_report(("a", "PYSEC-1", ["GHSA-high"])), _SEVERITY.get, {"GHSA-high"})
    assert fatal == [] and "ignored" in advisory[0]


def test_main_exit_codes(tmp_path, monkeypatch):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(_report(("a", "PYSEC-1", ["GHSA-high"]))))
    monkeypatch.setattr(gate, "osv_severity", _SEVERITY.get)
    assert gate.main(["gate", str(path)]) == 1
    path.write_text(json.dumps({"dependencies": [{"name": "a", "version": "1", "vulns": []}]}))
    assert gate.main(["gate", str(path)]) == 0
    assert gate.main(["gate", str(tmp_path / "missing.json")]) == 2


def test_a_failed_lookup_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(_report(("a", "PYSEC-1", ["GHSA-mod"]))))

    def down(_):
        raise OSError("osv down")

    monkeypatch.setattr(gate, "osv_severity", down)
    assert gate.main(["gate", str(path)]) == 2
