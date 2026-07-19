#!/usr/bin/env python3
"""Pre-commit guard for .env* files.

Fails if any .env* file (except .env.example) is either tracked by git or
sitting on disk with group/other permission bits set. Real keys live in
these files; they must stay untracked and 0600.
"""

import stat
import subprocess
import sys
from pathlib import Path

ALLOWED_TRACKED = {".env.example"}


def main() -> int:
    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=repo_root,
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
    )

    failures = []
    for env_file in repo_root.glob(".env*"):
        rel = env_file.name
        if rel in ALLOWED_TRACKED:
            continue
        if rel in tracked:
            failures.append(f"{rel}: is tracked by git — must stay untracked (contains real keys)")
        mode = stat.S_IMODE(env_file.stat().st_mode)
        if mode & 0o077:
            failures.append(f"{rel}: mode {oct(mode)} — group/other readable; run: chmod 600 {rel}")

    if failures:
        print("env-file permission check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
