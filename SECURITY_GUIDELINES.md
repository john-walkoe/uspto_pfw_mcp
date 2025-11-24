# Security Guidelines

## Overview

This document provides security guidelines for developing, deploying, and maintaining the USPTO Patent File Wrapper MCP Server. Following these guidelines helps ensure the security of API keys, user data, and system integrity.

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