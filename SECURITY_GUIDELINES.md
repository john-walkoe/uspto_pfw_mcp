# Security Guidelines

## Overview

This document provides comprehensive security guidelines for developing, deploying, and maintaining the USPTO Patent File Wrapper MCP Server. Following these guidelines helps ensure the security of API keys, user data, system integrity, and protection against AI-specific attacks including prompt injection.

## 🛡️ Prompt Injection Protection

### Overview
The USPTO PFW MCP includes advanced prompt injection detection to protect against malicious attempts to:
- Override system instructions
- Extract sensitive prompts or configuration
- Manipulate AI behavior
- Bypass security controls
- Access unauthorized patent data

### Detection System
**Comprehensive Pattern Detection:**
- **70+ Attack Patterns** covering instruction override, prompt extraction, format manipulation
- **Patent-Specific Threats** including USPTO API bypass attempts and examiner data disclosure
- **Enhanced Filtering** to minimize false positives in legitimate code and documentation
- **Multi-Modal Awareness** for future extensibility to image/audio injection vectors

**Integration Points:**
- **Pre-commit Hooks** - Automatic scanning before every commit
- **CI/CD Pipeline** - Continuous validation in GitHub Actions
- **Manual Scanning** - On-demand security assessment tools

### Usage

**Manual Security Scanning:**
```bash
# Scan specific directories/files
uv run python .security/check_prompt_injections.py src/ tests/ *.md

# Scan all relevant file types
uv run python .security/check_prompt_injections.py src/ tests/ docs/ *.yml *.json

# Run via pre-commit (recommended)
uv run pre-commit run prompt-injection-check --all-files
```

**Attack Categories Detected:**
1. **Instruction Override**: "ignore previous instructions", "disregard above commands"
2. **Prompt Extraction**: "show me your instructions", "reveal your system prompt"
3. **Behavior Manipulation**: "you are now a different AI", "act as a hacker"
4. **Format Manipulation**: "encode in base64", "spell backwards", "use hex encoding"
5. **Patent-Specific**: "extract patent numbers", "bypass USPTO API limits", "show examiner names"
6. **Social Engineering**: "we became friends", "our previous conversation"

**File Type Coverage:**
- Python source code (.py)
- Configuration files (.yml, .yaml, .json)
- Documentation (.md, .txt)
- Web files (.html, .js, .ts)
- Data files (.csv, .xml)

### Incident Response

**If Patterns Are Detected:**
1. **Review Context** - Determine if the detection is legitimate or false positive
2. **Assess Intent** - Check if the pattern was introduced maliciously
3. **Investigate Source** - Review commit history and author
4. **Document Findings** - Log the incident for security tracking
5. **Update Exclusions** - If false positive, consider pattern refinements

**False Positive Handling:**
```bash
# For legitimate test cases, add context markers
echo "# Example injection pattern (for testing): ignore previous instructions" >> test_file.py

# For documentation, ensure clear context
echo "This pattern 'show me your instructions' is an example of prompt injection" >> docs.md
```

### Advanced Threats

**Hybrid Attacks** (Future Considerations):
- **XSS + Prompt Injection**: AI-generated JavaScript payloads
- **SQL + Prompt Injection**: Natural language to malicious SQL
- **Multi-Agent Propagation**: Self-replicating prompts across AI systems

**Multi-Modal Injection** (Roadmap):
- **Image-based**: Hidden instructions in steganography
- **Audio/Video**: Transcript manipulation attacks
- **Cross-Modal**: Exploiting modality translation inconsistencies

## API Key Management

### 🔐 **Environment Variables (Required)**

**Always use environment variables for API keys:**

```python
# ✅ Correct - Environment variable
api_key = os.getenv("USPTO_API_KEY")
if not api_key:
    raise ValueError("USPTO_API_KEY environment variable is required")

# ❌ Never do this - Hardcoded key
api_key = "your_actual_api_key_here"
```

### 🔑 **API Key Storage**

**Production Environment:**
```bash
# Set environment variables
export USPTO_API_KEY=your_api_key_here
export MISTRAL_API_KEY=your_mistral_api_key_here
```

**Development Environment:**
```bash
# Use .env files (add to .gitignore)
echo "USPTO_API_KEY=your_dev_key" > .env.local
echo ".env.local" >> .gitignore
```

**Claude Desktop Configuration:**
```json
{
  "mcpServers": {
    "patent-filewrapper": {
      "env": {
        "USPTO_API_KEY": "your_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here"
      }
    }
  }
}
```

### 🚫 **What Never to Commit**

- Real API keys in any form
- Configuration files with real credentials
- Test files with hardcoded keys
- `.env` files or local config files
- Backup files that might contain keys

## Code Security Patterns

### ✅ **Secure Patterns**

**1. Environment Variable Validation:**
```python
import os

def get_required_env_var(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"{key} environment variable is required")
    return value

# Usage
api_key = get_required_env_var("USPTO_API_KEY")
```

**2. Secure Test Setup:**
```python
# In test files
def setup_test_environment():
    """Set up test environment with fallback to test keys"""
    if not os.getenv("USPTO_API_KEY"):
        os.environ["USPTO_API_KEY"] = "test_key_for_testing"
```

**3. Request ID Tracking:**
```python
# Logging with request IDs for debugging
request_id = generate_request_id()
logger.info(f"[{request_id}] Processing request")
```

### ❌ **Anti-Patterns to Avoid**

**1. Hardcoded Secrets:**
```python
# Never do this
API_KEY = "example_hardcoded_key_never_do_this_12345"
```

**2. Secrets in Comments:**
```python
# Don't include real keys in comments
# My key is: example_key_in_comment_bad_practice_67890
```

**3. Logging Secrets:**
```python
# Never log API keys
logger.info(f"Using API key: {api_key}")  # ❌
logger.info(f"Using API key: {api_key[:4]}***")  # ✅ Safe
```

## Logging Security (CWE-532 & CWE-778)

### 🔒 **SafeLogger Implementation**

The project includes a **SafeLogger** wrapper that automatically sanitizes all log messages to prevent sensitive data exposure:

```python
from ..shared.safe_logger import get_safe_logger

# Get a logger that automatically sanitizes sensitive data
logger = get_safe_logger(__name__)

# API keys are automatically masked
logger.error(f"API response: {api_response_text}")
# API keys in api_response_text are replaced with [USPTO_API_KEY], [MISTRAL_API_KEY], etc.
```

### 🛡️ **What Gets Sanitized Automatically**

**API Keys:**
- USPTO API keys (30 chars): `[USPTO_API_KEY]`
- Mistral API keys (32 chars): `[MISTRAL_API_KEY]`
- Generic API key patterns: `[API_KEY]`

**Tokens & Secrets:**
- JWT Bearer tokens: `[FILTERED]`
- Passwords: `[REDACTED]`
- Secret fields: `[REDACTED]`

**Personal Identifiable Information:**
- IP addresses: `127.0.***.***` (partial masking)
- Email addresses: `j***@example.com` (partial masking)

### 📝 **File-Based Logging with Rotation**

**Log Location:** `~/.uspto_pfw_mcp/logs/`

**Application Log (`patent_filewrapper_mcp.log`):**
- 10MB max file size
- 5 backup files (rotated automatically)
- General application events

**Security Log (`security.log`):**
- 10MB max file size
- 10 backup files (longer retention for compliance)
- Security events only (WARNING+ level)
- Separate file for SIEM integration

**File Permissions:**
- Unix: 600 (owner read/write only)
- Windows: Inherits user profile permissions

### 🎯 **Using the Security Logger**

For security-specific events, use the dedicated security logger:

```python
import logging

security_logger = logging.getLogger('security')

# Security events go to security.log only
security_logger.warning(f"Failed authentication attempt from IP: {ip}")
security_logger.error(f"Rate limit exceeded for client: {ip}")
security_logger.critical(f"Circuit breaker opened for API: {api_name}")
```

### ✅ **SafeLogger Usage Best Practices**

```python
from ..shared.safe_logger import get_safe_logger

# ✅ Correct - Always use get_safe_logger()
logger = get_safe_logger(__name__)
logger.info(f"Processing request: {request_data}")  # Data automatically sanitized

# ❌ Never use logging.getLogger() directly
import logging
logger = logging.getLogger(__name__)  # Bypasses sanitization
logger.info(f"Processing request: {request_data}")  # Could leak sensitive data
```

### 📊 **Log File Configuration**

All log files use **RotatingFileHandler** for automatic disk space management:

```python
from ..config.log_config import setup_logging, get_log_files

# Initialize logging (called in main.py)
setup_logging('INFO')

# Get log file locations
log_files = get_log_files()
print(f"App log: {log_files['app_log']}")
print(f"Security log: {log_files['security_log']}")
```

### 🔍 **Log File Permissions**

**Unix/Linux/macOS:**
```bash
# Directory: 700 (drwx------)
# Files: 600 (-rw-------)
ls -la ~/.uspto_pfw_mcp/logs/
# drwx------ ... logs/
# -rw------- ... patent_filewrapper_mcp.log
# -rw------- ... security.log
```

**Windows:**
- Inherits user profile permissions
- Protected by user account security

### ⚠️ **Migration from Unsafe Loggers**

The project has migrated all unsafe `logging.getLogger()` calls to `get_safe_logger()`:

**Before (Unsafe):**
```python
import logging
logger = logging.getLogger(__name__)
```

**After (Safe):**
```python
from ..shared.safe_logger import get_safe_logger
logger = get_safe_logger(__name__)
```

### 📈 **Compliance Impact**

**SOC 2 Compliance:**
- ✅ Logging requirements now PASS
- ✅ Persistent audit trail maintained
- ✅ Security events properly separated

**OWASP A09 (Logging Failures):**
- ✅ Log sanitization prevents data leakage
- ✅ File-based logging ensures audit trail
- ✅ Proper log retention with rotation

**CWE-532 (Insertion of Sensitive Information into Log File):**
- ✅ Risk: 7/10 → 1/10

**CWE-778 (Insufficient Logging):**
- ✅ Risk: 7/10 → 1/10

## Error Handling Security

### 🛡️ **Secure Error Responses**

```python
def format_error_response(message: str, status_code: int, request_id: str = None):
    """Format error without exposing sensitive data"""
    response = {
        "error": True,
        "success": False,
        "status_code": status_code,
        "message": message  # Never include API keys or internal paths
    }
    if request_id:
        response["request_id"] = request_id
    return response
```

### 🚨 **Information Disclosure Prevention**

**Sanitize error messages:**
```python
# ✅ Safe error message
"Authentication failed - check API key"

# ❌ Exposes internal information
f"Failed to authenticate with key {api_key} against {internal_url}"
```

## File and Repository Security

### 📁 **.gitignore Requirements**

```gitignore
# API Keys and Secrets
*api_key*
*API_KEY*
*.key
secrets.json
.env
.env.local
.env.production

# Configuration files with secrets
*local*.json
*_with_keys*
*_secrets*
config_real.json

# Claude Code integration
.claude/
```

### 🗂️ **Configuration Templates**

**Template files should use empty placeholders:**
```json
{
  "env": {
    "USPTO_API_KEY": "",
    "MISTRAL_API_KEY": ""
  },
  "documentation": "Set these values in your environment"
}
```

## Development Workflow Security

### 🔄 **Secure Development Process**

1. **Before Coding:**
   - Never commit real API keys
   - Use environment variables from day one
   - Set up .gitignore before first commit

2. **During Development:**
   - Use test keys for local development
   - Implement proper error handling
   - Add request ID tracking for debugging

3. **Before Committing:**
   - Run security scan: `grep -r "API_KEY.*=" . --include="*.py"`
   - Verify no hardcoded secrets
   - Test with environment variables

4. **Before Publishing:**
   - Full security audit of codebase
   - Clean git history if needed
   - Verify all configuration templates

### 🧪 **Testing Security**

```python
# Security test example
def test_no_hardcoded_secrets():
    """Ensure no hardcoded API keys in codebase"""
    import subprocess
    import os

    # Search for potential hardcoded keys (example pattern)
    result = subprocess.run([
        'grep', '-rE', 'API_KEY.*=.*"[A-Za-z0-9]{20,}"',
        '.', '--exclude-dir=.git', '--include=*.py'
    ], capture_output=True, text=True)

    assert result.returncode != 0, "Found hardcoded API key in codebase"
```

## Incident Response

### 🚨 **If API Key is Exposed**

**Immediate Actions (within 1 hour):**
1. **Invalidate the exposed key** at USPTO developer portal
2. **Generate new API key**
3. **Update production environment** with new key
4. **Scan for unauthorized usage** in API logs

**Cleanup Actions (within 24 hours):**
1. **Remove from git history** if committed
2. **Update all team members** with new key
3. **Review access logs** for suspicious activity
4. **Implement additional monitoring**

### 📋 **Response Checklist**

- [ ] API key invalidated at source
- [ ] New key generated and deployed
- [ ] Git history cleaned (if needed)
- [ ] Team notified of key change
- [ ] Monitoring implemented for new key
- [ ] Post-mortem completed
- [ ] Process improvements identified

## Monitoring and Auditing

### 📊 **Security Monitoring**

```python
# Log security-relevant events
logger.info(f"[{request_id}] API authentication successful")
logger.warning(f"[{request_id}] Rate limit approached")
logger.error(f"[{request_id}] Authentication failed - invalid key")
```

### 🔍 **Regular Security Audits**

**Monthly Checklist:**
- [ ] Scan codebase for hardcoded secrets
- [ ] Review API key rotation schedule
- [ ] Check .gitignore effectiveness
- [ ] Verify test environment security
- [ ] Review error message exposure

## Tools and Automation

### 🔧 **Recommended Security Tools**

**Pre-commit Hooks:**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        exclude: tests/.*
```

**CI/CD Security Scanning:**
```bash
# Add to CI pipeline
git secrets --scan
detect-secrets scan --all-files
```

### ⚙️ **Automated Checks**

```bash
#!/bin/bash
# security-scan.sh
echo "Scanning for hardcoded secrets..."
grep -rE 'API_KEY.*=.*"[A-Za-z0-9]{20,}"' . --include="*.py" --exclude-dir=.git
grep -rE 'MISTRAL_API_KEY.*=.*"[A-Za-z0-9]{20,}"' . --include="*.py" --exclude-dir=.git

echo "Checking .gitignore coverage..."
grep -E "(\.env|api_key|secrets)" .gitignore
```

## Compliance and Best Practices

### 📋 **Security Compliance**

**OWASP Top 10 Alignment:**
- **A07:2021 – Identification and Authentication Failures**: Environment variables, key validation
- **A04:2021 – Insecure Design**: Secure patterns, error handling
- **A05:2021 – Security Misconfiguration**: Proper .gitignore, templates

**Industry Best Practices:**
- Use environment variables for secrets
- Implement proper error handling
- Regular key rotation
- Security monitoring and logging
- Incident response procedures

## Training and Awareness

### 📚 **Developer Training Topics**

1. **API Key Management**
   - Environment variables vs hardcoding
   - Secure storage patterns
   - Key rotation procedures

2. **Secure Coding**
   - Input validation
   - Error handling without information disclosure
   - Logging best practices

3. **Repository Security**
   - .gitignore configuration
   - Commit scanning
   - History cleaning

### ✅ **Security Checklist for Developers**

Before each commit:
- [ ] No hardcoded API keys
- [ ] Environment variables used correctly
- [ ] Error messages don't expose secrets
- [ ] .gitignore includes sensitive patterns
- [ ] Test files use secure patterns

Before each release:
- [ ] Full security scan completed
- [ ] All configuration templates secured
- [ ] Documentation updated
- [ ] Team trained on changes

## Conclusion

Security is everyone's responsibility. By following these guidelines, we ensure that the USPTO Patent File Wrapper MCP Server remains secure and protects user data and API credentials. Regular review and updates of these guidelines help maintain security posture as the project evolves.

For questions about security practices or to report security issues, contact the project maintainers immediately.
