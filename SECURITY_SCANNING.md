# Security Scanning Guide

This document explains the comprehensive automated security scanning setup for the USPTO Patent File Wrapper MCP project.

## Overview

The project uses multiple security scanning technologies:
- **detect-secrets** to prevent accidental commits of API keys, tokens, passwords, and other sensitive data
- **Prompt Injection Detection** to protect against AI-specific attacks and malicious prompt patterns

## Features

### 1. **CI/CD Secret Scanning** (GitHub Actions)
- Automatically scans all code on push and pull requests
- Scans git history (last 100 commits) for accidentally committed secrets
- Fails the build if new secrets are detected
- Location: `.github/workflows/secret-scan.yaml`

### 2. **Pre-commit Hooks** (Local Development)
- Prevents committing secrets before they reach GitHub
- Runs automatically on `git commit`
- Location: `.pre-commit-config.yaml`

### 3. **Baseline Management**
- Tracks known placeholder keys and false positives
- Location: `.secrets.baseline`

### 4. **Prompt Injection Detection** (Enhanced Security)
- Scans for 70+ malicious prompt patterns
- Detects patent-specific attack vectors (API bypass, data extraction)
- Integrated with pre-commit hooks and CI/CD pipeline
- Location: `.security/patent_prompt_injection_detector.py`

**Attack Categories Detected:**
- Instruction override attempts ("ignore previous instructions")
- System prompt extraction ("show me your instructions")
- AI behavior manipulation ("you are now a different AI")
- Patent data extraction ("extract all patent numbers")
- USPTO API bypass attempts ("bypass API restrictions")
- Examiner information disclosure ("reveal examiner names")
- Social engineering patterns ("we became friends")

## Setup

### Install Pre-commit Hooks (Recommended)

```bash
# Install pre-commit framework and detect-secrets
uv pip install pre-commit detect-secrets

# Install the git hooks
uv run pre-commit install

# Test the hooks (optional)
uv run pre-commit run --all-files
```

### Manual Security Scanning

**Secret Detection:**
```bash
# Scan entire codebase
uv run detect-secrets scan

# Scan specific files
uv run detect-secrets scan src/patent_filewrapper_mcp/main.py

# Update baseline after reviewing findings
uv run detect-secrets scan --baseline .secrets.baseline

# Audit baseline (review all flagged items)
uv run detect-secrets audit .secrets.baseline
```

**Prompt Injection Detection:**
```bash
# Scan for prompt injection patterns
uv run python .security/check_prompt_injections.py src/ tests/ *.md

# Scan specific directories
uv run python .security/check_prompt_injections.py src/patent_filewrapper_mcp/

# Run via pre-commit hook
uv run pre-commit run prompt-injection-check --all-files

# Test with verbose output
uv run python .security/check_prompt_injections.py --verbose src/ tests/
```

## What Gets Scanned

### Included:
- All Python source files (`src/`, `tests/`)
- Configuration files (except example configs)
- Shell scripts and workflows
- Documentation (except README/guides with example keys)

### Excluded:
- `configs/*.json` - Contains placeholder API keys for examples
- `*.md` - Documentation with example secrets
- `package-lock.json` - NPM lock file
- `.secrets.baseline` - Baseline file itself

## Handling Detection Results

### False Positives (Test/Example Secrets)

If detect-secrets flags a legitimate placeholder:

1. **Verify it's truly a placeholder** (not a real secret)
2. **Update the baseline** to mark it as known:
   ```bash
   uv run detect-secrets scan --baseline .secrets.baseline
   ```
3. **Commit the updated baseline**:
   ```bash
   git add .secrets.baseline
   git commit -m "Update secrets baseline after review"
   ```

### Real Secrets Detected

If you accidentally committed a real secret:

1. **Revoke the secret immediately** (regenerate API key, rotate token, etc.)
2. **Remove from git history**:
   ```bash
   # Use BFG Repo Cleaner or git filter-branch
   # See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
   ```
3. **Update code to use environment variables**:
   ```python
   import os
   api_key = os.getenv("USPTO_API_KEY")  # Never hardcode!
   ```

## Best Practices

### DO:
- ✅ Store secrets in environment variables
- ✅ Use `.env` files (add to `.gitignore`)
- ✅ Use placeholder values in example configs
- ✅ Run `pre-commit run --all-files` before first commit
- ✅ Review baseline updates carefully

### DON'T:
- ❌ Hardcode API keys in source code
- ❌ Commit `.env` files
- ❌ Use real secrets in tests (use mocks/fixtures)
- ❌ Disable pre-commit hooks without review
- ❌ Ignore secret scanning failures in CI

## GitHub Actions Workflow

The workflow runs on:
- All pushes to `main`, `master`, and `develop` branches
- All pull requests to these branches

### Workflow Steps:
1. Checkout full git history
2. Install detect-secrets
3. Scan current codebase against baseline
4. Scan recent git history (last 100 commits)
5. Report findings and fail if secrets detected

### Viewing Results:
- Go to **Actions** tab in GitHub
- Click on **Secret Scanning** workflow
- Review any failures in the job logs

## Troubleshooting

### Pre-commit Hook Failing

```bash
# Check what's detected
uv run pre-commit run detect-secrets --all-files

# If false positive, update baseline
uv run detect-secrets scan --baseline .secrets.baseline

# Re-run commit
git commit
```

### CI Failing with "Secrets Detected"

1. Review the GitHub Actions log to see what was flagged
2. Verify if it's a real secret or false positive
3. If false positive:
   - Update baseline locally: `uv run detect-secrets scan --baseline .secrets.baseline`
   - Commit and push the updated baseline
4. If real secret:
   - **REVOKE THE SECRET IMMEDIATELY**
   - Remove from code and git history
   - Fix and re-push

### Baseline Out of Sync

```bash
# Regenerate baseline from scratch
uv run detect-secrets scan \
  --exclude-files 'configs/.*\.json' \
  --exclude-files '\.md$' \
  > .secrets.baseline

# Review and commit
git add .secrets.baseline
git commit -m "Regenerate secrets baseline"
```

## Integration with Security Guidelines

This scanning complements the recommendations in `SECURITY_GUIDELINES.md`:
- Prevents API keys from being committed
- Enforces use of environment variables
- Provides audit trail for secret management
- Supports incident response procedures

## Secret Types Detected

The scanner detects 20+ types of secrets including:

**Cloud Provider Keys:**
- AWS Access Keys
- Azure Storage Keys
- GCP Service Account Keys
- IBM Cloud IAM Keys

**API & Service Tokens:**
- GitHub Tokens
- GitLab Tokens
- OpenAI API Keys
- Mistral API Keys
- Stripe API Keys
- Twilio Keys
- SendGrid Keys
- Slack Tokens
- Discord Bot Tokens
- Telegram Bot Tokens

**General Secrets:**
- Private SSH Keys
- JWT Tokens
- NPM Tokens
- PyPI Tokens
- Basic Auth Credentials
- High-Entropy Strings (Base64/Hex)
- Password Keywords

## Project-Specific Considerations

### USPTO API Keys
The scanner is configured to allow empty placeholder strings in `configs/*.json` files for documentation purposes. Real USPTO API keys must always be set as environment variables:

```bash
export USPTO_API_KEY=your_actual_key_here
```

### Mistral API Keys
Similarly, Mistral API keys are optional but must be stored securely:

```bash
export MISTRAL_API_KEY=your_mistral_key_here
```

### Test Files
Test files in `tests/` may contain placeholder keys for validation testing. These are tracked in `.secrets.baseline` and are verified to be test-only placeholders, not real credentials.

## Additional Resources

- [detect-secrets Documentation](https://github.com/Yelp/detect-secrets)
- [Pre-commit Framework](https://pre-commit.com/)
- [GitHub Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
- [OWASP Secrets Management](https://owasp.org/www-community/vulnerabilities/Use_of_hard-coded_password)

## Questions?

See `SECURITY_GUIDELINES.md` for broader security practices or file an issue on GitHub.
