#!/usr/bin/env python3
"""
Standalone script for checking files for prompt injection patterns with baseline support.

Uses a baseline system to track known findings and only flag NEW patterns that are not
in the baseline. This solves the problem of false positives from legitimate code and
documentation while maintaining protection against malicious prompt injection attacks.

Usage:
    # First run - Create baseline
    python check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json

    # Normal run - Check against baseline (only NEW findings fail)
    python check_prompt_injections.py --baseline src/ tests/ *.yml *.yaml *.json

    # Update baseline to include new legitimate findings
    python check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json

    # Force new baseline (overwrite existing)
    python check_prompt_injections.py --force-baseline src/ tests/ *.md *.yml *.yaml *.json

Exit codes:
    0 - No NEW findings (all findings in baseline)
    1 - NEW findings detected (not in baseline)
    2 - Error occurred
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from patent_prompt_injection_detector import PatentPromptInjectionDetector


BASELINE_FILE = ".prompt_injections.baseline"


def create_fingerprint(filepath: str, line_number: int, match: str) -> str:
    """
    Create a unique SHA256 hash fingerprint for a finding.

    Args:
        filepath: Path to the file (relative to project root)
        line_number: Line number where finding was found
        match: The matched text

    Returns:
        SHA256 hash as hexadecimal string
    """
    # Use relative path for portability across different machines
    relative_path = Path(filepath).as_posix()
    fingerprint_data = f"{relative_path}:{line_number}:{match}"
    return hashlib.sha256(fingerprint_data.encode('utf-8')).hexdigest()


def load_baseline() -> Dict[str, Dict[str, Dict]]:
    """
    Load the baseline file.

    Returns:
        Dictionary mapping file paths to findings
    """
    if not Path(BASELINE_FILE).exists():
        return {}

    try:
        with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load baseline file: {e}", file=sys.stderr)
        return {}


def save_baseline(baseline: Dict[str, Dict[str, Dict]]) -> bool:
    """
    Save the baseline file.

    Args:
        baseline: Baseline dictionary to save

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(BASELINE_FILE, 'w', encoding='utf-8') as f:
            json.dump(baseline, f, indent=2, sort_keys=True)
        return True
    except IOError as e:
        print(f"Error: Could not save baseline file: {e}", file=sys.stderr)
        return False


def check_file(
    filepath: Path,
    detector: PatentPromptInjectionDetector,
    baseline: Optional[Dict[str, Dict[str, Dict]]] = None,
    use_baseline: bool = False
) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]], List[Tuple[int, str]]]:
    """
    Check a single file for prompt injection patterns.

    Args:
        filepath: Path to file to check
        detector: Prompt injection detector instance
        baseline: Existing baseline (if checking against baseline)
        use_baseline: Whether to check against baseline

    Returns:
        Tuple of (all_findings, baseline_findings, new_findings)
    """
    try:
        # Skip binary files
        if not filepath.is_file():
            return [], [], []

        # Only check text-based files
        text_extensions = {'.py', '.txt', '.md', '.yml', '.yaml', '.json', '.js', '.ts', '.html', '.xml', '.csv'}
        if filepath.suffix.lower() not in text_extensions and filepath.suffix:
            return [], [], []

        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Analyze content
        all_findings = []
        baseline_findings = []
        new_findings = []

        lines = content.split('\n')
        relative_path = filepath.as_posix()

        # Get baseline for this file
        file_baseline = baseline.get(relative_path, {}) if baseline else {}

        for line_number, line in enumerate(lines, 1):
            matches = list(detector.analyze_line(line, line_number, str(filepath)))
            for match in matches:
                finding = (line_number, match)
                all_findings.append(finding)

                if use_baseline:
                    fingerprint = create_fingerprint(relative_path, line_number, match)
                    if fingerprint in file_baseline:
                        baseline_findings.append(finding)
                    else:
                        new_findings.append(finding)
                else:
                    # No baseline mode - all findings are considered new
                    new_findings.append(finding)

        return all_findings, baseline_findings, new_findings

    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return [], [], []


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Check files for prompt injection patterns with baseline support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First run - Create baseline (will NOT fail if findings exist)
  python check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json

  # Normal run - Check against baseline (only NEW findings fail)
  python check_prompt_injections.py --baseline src/ tests/ *.yml *.yaml *.json

  # Update baseline to include new legitimate findings
  python check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json

  # Force new baseline (overwrite existing)
  python check_prompt_injections.py --force-baseline src/ tests/ *.md *.yml *.yaml *.json

Baseline File Format (.prompt_injections.baseline):
  {
    "src/patent_filewrapper_mcp/file.py": {
      "abc123def456": {"line": 2, "match": "prompt"},
      "def789ghi012": {"line": 4, "match": "system"}
    }
  }

Common prompt injection patterns detected:
- Instruction override attempts ("ignore previous instructions")
- Prompt extraction ("show me your instructions")
- Persona switching ("you are now a different AI")
- Output format manipulation ("encode in hex")
- Social engineering ("we became friends")
- Unicode steganography (emoji variation selectors)
"""
    )

    parser.add_argument(
        'files',
        nargs='*',
        help='Files to check for prompt injections'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Only show summary (suppress individual findings)'
    )

    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        '--baseline',
        action='store_true',
        help='Check against existing baseline (only NEW findings cause failure)'
    )
    baseline_group.add_argument(
        '--update-baseline',
        action='store_true',
        help='Add new findings to existing baseline'
    )
    baseline_group.add_argument(
        '--force-baseline',
        action='store_true',
        help='Create new baseline (overwrite existing)'
    )

    parser.add_argument(
        '--include-security-files',
        action='store_true',
        help='Include security documentation files in scan'
    )

    args = parser.parse_args()

    if not args.files:
        print("No files specified. Use --help for usage.", file=sys.stderr)
        return 2

    def safe_print(text):
        """Print text with Unicode character handling for Windows console"""
        try:
            print(text)
        except UnicodeEncodeError:
            # Replace problematic Unicode characters with their representation
            safe_text = text.encode('ascii', errors='replace').decode('ascii')
            print(safe_text)

    # Determine mode
    use_baseline = args.baseline or args.update_baseline
    update_baseline = args.update_baseline or args.force_baseline
    force_baseline = args.force_baseline

    # Load baseline if needed
    baseline = load_baseline() if use_baseline and not force_baseline else {}

    detector = PatentPromptInjectionDetector()
    total_files_checked = 0
    total_findings = 0
    baseline_findings = 0
    new_findings = 0
    files_with_findings = []
    files_with_new_findings = []

    # New baseline to write (for update/force modes)
    new_baseline = {} if update_baseline else None

    for file_pattern in args.files:
        filepath = Path(file_pattern)

        if filepath.is_file():
            files_to_check = [filepath]
        else:
            # Handle glob patterns - get all matching files
            files_to_check = []
            # Expand glob patterns
            import glob
            for match in glob.glob(file_pattern, recursive=True):
                match_path = Path(match)
                if match_path.is_file():
                    files_to_check.append(match_path)

        for file_path in files_to_check:
            if not file_path.is_file():
                continue

            total_files_checked += 1
            all_finds, base_finds, new_finds = check_file(
                file_path, detector, baseline, use_baseline
            )

            if all_finds:
                files_with_findings.append(str(file_path))
                total_findings += len(all_finds)

            if new_finds:
                new_findings += len(new_finds)
                files_with_new_findings.append(str(file_path))

            if base_finds:
                baseline_findings += len(base_finds)

            # Update baseline data structure
            if update_baseline:
                relative_path = file_path.as_posix()
                new_baseline[relative_path] = {}

                for line_num, match in all_finds:
                    fingerprint = create_fingerprint(relative_path, line_num, match)
                    new_baseline[relative_path][fingerprint] = {
                        "line": line_num,
                        "match": match
                    }

            # Print findings
            if not args.quiet and (all_finds or new_finds):
                file_label = f"[!] Prompt injection patterns found in {file_path}:"
                safe_print(f"\n{file_label}")

                # Print baseline findings first (if checking against baseline)
                if use_baseline and base_finds:
                    for line_num, match in base_finds:
                        display_match = match[:80] + "..." if len(match) > 80 else match
                        safe_print(f"  Line {line_num:4d}: {display_match} [BASELINE]")

                # Print new findings
                if new_finds:
                    for line_num, match in new_finds:
                        display_match = match[:80] + "..." if len(match) > 80 else match
                        safe_print(f"  Line {line_num:4d}: {display_match} [NEW]")

    # Save baseline if updating
    if update_baseline:
        if save_baseline(new_baseline):
            safe_print(f"\nBaseline updated: {BASELINE_FILE}")
            safe_print(f"Total tracked findings: {sum(len(f) for f in new_baseline.values())}")

    # Summary
    print(f"\n{'='*65}")
    print("USPTO Patent File Wrapper MCP Security Scan Results:")
    print(f"{'-'*65}")
    print(f"Files checked:       {total_files_checked}")
    print(f"Total findings:      {total_findings}")

    if use_baseline:
        print(f"Baseline findings:   {baseline_findings}")
        print(f"NEW findings:        {new_findings}  <== Only NEW findings cause failure")
        print(f"Files with findings: {len(files_with_findings)}")
        print(f"Files with NEW findings: {len(files_with_new_findings)}")

        if new_findings == 0:
            print(f"\n[OK] No NEW prompt injection patterns detected.")
            print("All findings match baseline (existing known findings).")
            return 0
        else:
            print(f"\n[!] NEW prompt injection patterns detected!")
            print("These findings are NOT in the baseline and require review.")
            return 1
    else:
        print(f"Files with findings: {len(files_with_findings)}")

        if total_findings > 0:
            print(f"\n[!] Prompt injection patterns found!")
            print("These patterns may indicate attempts to:")
            print("- Override system instructions")
            print("- Extract sensitive prompts")
            print("- Change AI behavior")
            print("- Bypass security controls")
            print("\nReview these findings to ensure they are not malicious.")
            return 0 if update_baseline else 1
        else:
            print("[OK] No prompt injection patterns detected.")
            return 0


if __name__ == '__main__':
    sys.exit(main())