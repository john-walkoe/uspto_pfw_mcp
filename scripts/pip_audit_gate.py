"""Fail CI on a High or Critical advisory in a pip-audit JSON report.

pip-audit reports advisories but not their severity, and its exit code fails
on any advisory at all. This gate reads the report (`pip-audit -f json -o
<file>`), looks each advisory's GHSA alias up in OSV (api.osv.dev; GitHub's
`database_specific.severity`), and exits 1 when any is HIGH or CRITICAL.
MODERATE, LOW and advisories with no GHSA severity are printed, not fatal.
An OSV lookup that fails is fatal (exit 2): a gate that passes because it
could not look is no gate.

Advisories assessed as unreachable go in `.pip-audit-ignore` at the repo
root, one id per line (`GHSA-...  # why`); stdlib only, so CI runs it with
any Python.

Usage: python scripts/pip_audit_gate.py <report.json>
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.request
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

FATAL = {"HIGH", "CRITICAL"}
OSV_URL = "https://api.osv.dev/v1/vulns/{}"


def osv_severity(advisory_id: str) -> Optional[str]:
    with urllib.request.urlopen(OSV_URL.format(advisory_id), timeout=20) as response:
        record = json.load(response)
    severity = (record.get("database_specific") or {}).get("severity")
    return str(severity).upper() if severity else None


def load_ignores(path: pathlib.Path) -> Set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            ids.add(token)
    return ids


def classify(report: Dict, lookup: Callable[[str], Optional[str]],
             ignores: Iterable[str] = ()) -> Tuple[List[str], List[str]]:
    """(fatal lines, advisory lines) for every advisory in the report."""
    ignored = set(ignores)
    fatal: List[str] = []
    advisory: List[str] = []
    seen: Set[Tuple[str, str]] = set()
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            ids = [vuln["id"], *vuln.get("aliases", [])]
            key = (dep["name"], vuln["id"])
            if key in seen:
                continue
            seen.add(key)
            ghsa = next((i for i in ids if i.startswith("GHSA-")), None)
            severity = lookup(ghsa) if ghsa else None
            line = (f"{dep['name']} {dep['version']} {vuln['id']} ({ghsa or 'no GHSA'}) "
                    f"severity={severity or 'unknown'} fix={','.join(vuln.get('fix_versions') or []) or 'none'}")
            if ignored.intersection(ids):
                advisory.append(line + " [ignored: .pip-audit-ignore]")
            elif severity in FATAL:
                fatal.append(line)
            else:
                advisory.append(line)
    return fatal, advisory


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    report_path = pathlib.Path(argv[1])
    if not report_path.exists():
        print(f"pip-audit report {report_path} is missing: pip-audit did not run")
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ignores = load_ignores(pathlib.Path(__file__).resolve().parent.parent / ".pip-audit-ignore")
    try:
        fatal, advisory = classify(report, osv_severity, ignores)
    except Exception as exc:  # noqa: BLE001 - any lookup failure fails the gate
        print(f"OSV severity lookup failed ({type(exc).__name__}); failing closed")
        return 2
    for line in advisory:
        print(f"advisory  {line}")
    for line in fatal:
        print(f"FATAL     {line}")
    if fatal:
        print(f"{len(fatal)} High or Critical advisories: upgrade (uv lock --upgrade-package <name>) "
              "or record an assessed-unreachable id in .pip-audit-ignore")
        return 1
    print(f"No High or Critical advisories ({len(advisory)} lower or unrated)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
