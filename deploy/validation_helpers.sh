#!/bin/bash
# validation_helpers.sh
# API Key and Input Validation Functions for USPTO MCP Deployment
#
# Security: Validates API key formats to prevent deployment with invalid/placeholder keys
# Usage: source this file in deployment scripts
#
# Date: 2025-11-18
# Part of: Security fixes for deploy scripts (audit findings)

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Logging functions (if not already defined)
if ! type log_error &>/dev/null; then
    log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
fi

if ! type log_warning &>/dev/null; then
    log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fi

if ! type log_success &>/dev/null; then
    log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
fi

if ! type log_info &>/dev/null; then
    log_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
fi

# ============================================
# API Key Format Validation Functions
# ============================================

# Validate USPTO API Key
# Format: 30 characters, all lowercase letters
# Example: abcdefghijklmnopqrstuvwxyzabcd
validate_uspto_api_key() {
    local key="$1"
    local key_length=${#key}

    # Check if empty
    if [[ -z "$key" ]]; then
        log_error "USPTO API key is empty"
        return 1
    fi

    # Check exact length (30 characters)
    if [[ $key_length -ne 30 ]]; then
        log_error "USPTO API key must be exactly 30 characters (got ${key_length})"
        log_info "Expected format: 30 lowercase letters"
        return 1
    fi

    # Check character set (only lowercase letters)
    if ! [[ "$key" =~ ^[a-z]{30}$ ]]; then
        log_error "USPTO API key must contain only lowercase letters (a-z)"
        log_info "Invalid characters detected in key"
        return 1
    fi

    # Check for placeholder patterns
    if check_placeholder_pattern "$key" "USPTO"; then
        return 1
    fi

    # Check for obvious test patterns
    if [[ "$key" =~ ^(test|demo|sample|example) ]]; then
        log_warning "USPTO API key starts with 'test/demo/sample' - is this a real key?"
        read -p "Continue anyway? (y/N): " -n 1 -r confirm
        echo
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            log_info "Validation cancelled by user"
            return 1
        fi
    fi

    log_success "USPTO API key format validated (30 chars, lowercase)"
    return 0
}

# Validate Mistral API Key
# Format: 32 characters, uppercase/lowercase letters and numbers
# Example: AbCdEfGh1234567890IjKlMnOp1234
validate_mistral_api_key() {
    local key="$1"
    local key_length=${#key}

    # Empty is allowed (Mistral is optional)
    if [[ -z "$key" ]]; then
        log_info "Mistral API key is optional - skipping validation"
        return 0
    fi

    # Check exact length (32 characters)
    if [[ $key_length -ne 32 ]]; then
        log_error "Mistral API key must be exactly 32 characters (got ${key_length})"
        log_info "Expected format: 32 alphanumeric characters (a-z, A-Z, 0-9)"
        return 1
    fi

    # Check character set (letters and numbers only)
    if ! [[ "$key" =~ ^[a-zA-Z0-9]{32}$ ]]; then
        log_error "Mistral API key must contain only letters (a-z, A-Z) and numbers (0-9)"
        log_info "Invalid characters detected in key"
        return 1
    fi

    # Check for placeholder patterns
    if check_placeholder_pattern "$key" "Mistral"; then
        return 1
    fi

    # Check for obvious test patterns
    if [[ "$key" =~ ^(test|demo|sample|example) ]]; then
        log_warning "Mistral API key starts with 'test/demo/sample' - is this a real key?"
        read -p "Continue anyway? (y/N): " -n 1 -r confirm
        echo
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            log_info "Validation cancelled by user"
            return 1
        fi
    fi

    log_success "Mistral API key format validated (32 chars, alphanumeric)"
    return 0
}

# Check for common placeholder patterns
check_placeholder_pattern() {
    local key="$1"
    local key_type="$2"

    # Common placeholder patterns (case-insensitive)
    local placeholder_patterns=(
        "your.*key"
        "your.*api"
        "api.*key.*here"
        "placeholder"
        "insert.*key"
        "insert.*api"
        "replace.*me"
        "replace.*key"
        "changeme"
        "change.*me"
        "put.*key.*here"
        "add.*key.*here"
        "enter.*key"
        "paste.*key"
        "fill.*in"
    )

    # Convert to lowercase for comparison
    local key_lower=$(echo "$key" | tr '[:upper:]' '[:lower:]')

    for pattern in "${placeholder_patterns[@]}"; do
        if echo "$key_lower" | grep -qiE "$pattern"; then
            log_error "Detected placeholder pattern in $key_type API key: '$pattern'"
            log_error "Please use your actual API key, not a placeholder"
            return 0  # 0 = pattern found (error)
        fi
    done

    return 1  # 1 = no pattern found (success)
}

# ============================================
# Path Validation Functions
# ============================================

# Validate directory path for security
validate_path() {
    local path="$1"
    local path_name="$2"

    # Check if empty
    if [[ -z "$path" ]]; then
        log_error "$path_name cannot be empty"
        return 1
    fi

    # Check for path traversal attempts (..)
    if [[ "$path" =~ \.\. ]]; then
        log_error "$path_name contains path traversal (..): $path"
        log_error "This is a security risk - path rejected"
        return 1
    fi

    # Require absolute path
    if [[ ! "$path" =~ ^/ ]]; then
        log_error "$path_name must be an absolute path (starting with /)"
        log_error "Got: $path"
        return 1
    fi

    # Warn about sensitive system directories
    if [[ "$path" =~ ^/(etc|proc|sys|dev|boot)(/|$) ]]; then
        log_warning "$path_name targets sensitive system directory: $path"
        log_warning "This could be dangerous - are you sure?"
        read -p "Continue anyway? (y/N): " -n 1 -r confirm
        echo
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            log_info "Path validation rejected by user"
            return 1
        fi
    fi

    # Warn about /tmp (world-writable)
    if [[ "$path" =~ ^/tmp(/|$) ]]; then
        log_warning "$path_name uses /tmp directory (world-writable)"
        log_warning "Consider using a more secure location"
    fi

    log_success "$path_name validated: $path"
    return 0
}

# ============================================
# Existing Key Detection Functions
# ============================================

# Check if USPTO API key exists in secure storage
check_existing_uspto_key() {
    if [[ -f "$HOME/.uspto_api_key" ]]; then
        return 0  # Exists
    else
        return 1  # Does not exist
    fi
}

# Check if Mistral API key exists in secure storage
check_existing_mistral_key() {
    if [[ -f "$HOME/.mistral_api_key" ]]; then
        return 0  # Exists
    else
        return 1  # Does not exist
    fi
}

# Load existing USPTO key from secure storage (uses Python)
load_existing_uspto_key() {
    # Use Python to load from secure storage
    python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from patent_filewrapper_mcp.shared_secure_storage import get_uspto_api_key
    key = get_uspto_api_key()
    if key:
        print(key)
        sys.exit(0)
    else:
        sys.exit(1)
except Exception as e:
    sys.exit(1)
EOF
}

# Load existing Mistral key from secure storage (uses Python)
load_existing_mistral_key() {
    # Use Python to load from secure storage
    python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))

try:
    from patent_filewrapper_mcp.shared_secure_storage import get_mistral_api_key
    key = get_mistral_api_key()
    if key:
        print(key)
        sys.exit(0)
    else:
        sys.exit(1)
except Exception as e:
    sys.exit(1)
EOF
}

# Prompt user if they want to use existing key
prompt_use_existing_key() {
    local key_type="$1"  # "USPTO" or "Mistral"
    local masked_key="$2"

    echo ""
    log_success "Detected existing $key_type API key in secure storage"
    log_info "Key (masked): $masked_key"
    echo ""
    read -p "Would you like to use this existing key? (Y/n): " USE_EXISTING
    USE_EXISTING=${USE_EXISTING:-Y}

    if [[ "$USE_EXISTING" =~ ^[Yy]$ ]]; then
        return 0  # Use existing
    else
        return 1  # Don't use existing
    fi
}

# ============================================
# User Input Validation Functions
# ============================================

# Securely read API key from user (hidden input)
read_api_key_secure() {
    local prompt="$1"
    local var_name="$2"
    local api_key=""

    # Read with hidden input
    read -r -s -p "$prompt: " api_key
    echo  # New line after hidden input

    # Return via eval (to set caller's variable)
    eval "$var_name='$api_key'"
}

# Prompt for API key with validation loop (with existing key detection)
prompt_and_validate_uspto_key() {
    local key=""
    local max_attempts=3
    local attempt=0

    # STEP 1: Check if key already exists in secure storage
    if check_existing_uspto_key; then
        log_info "Checking existing USPTO API key from another USPTO MCP installation..."

        # Try to load the existing key
        local existing_key=$(load_existing_uspto_key)
        if [[ $? -eq 0 && -n "$existing_key" ]]; then
            # Mask the key for display
            local masked_key=$(mask_api_key "$existing_key")

            # Ask user if they want to use it
            if prompt_use_existing_key "USPTO" "$masked_key"; then
                log_success "Using existing USPTO API key from secure storage"
                echo "$existing_key"
                return 0
            else
                log_info "You chose to enter a new USPTO API key"
                log_warning "This will OVERWRITE the existing key for ALL USPTO MCPs"
                read -p "Are you sure you want to continue? (y/N): " CONFIRM_OVERWRITE
                if [[ ! "$CONFIRM_OVERWRITE" =~ ^[Yy]$ ]]; then
                    log_info "Keeping existing key"
                    echo "$existing_key"
                    return 0
                fi
            fi
        else
            log_warning "Existing key file found but could not load (may be corrupted)"
            log_info "You will need to enter a new key"
        fi
    fi

    # STEP 2: Prompt for new key (either no existing key, or user wants to override)
    while [[ $attempt -lt $max_attempts ]]; do
        ((attempt++))

        read_api_key_secure "Enter your USPTO API key" key

        if [[ -z "$key" ]]; then
            log_error "USPTO API key cannot be empty"
            if [[ $attempt -lt $max_attempts ]]; then
                log_info "Attempt $attempt of $max_attempts"
            fi
            continue
        fi

        if validate_uspto_api_key "$key"; then
            # Success - return key via echo
            echo "$key"
            return 0
        else
            if [[ $attempt -lt $max_attempts ]]; then
                log_warning "Attempt $attempt of $max_attempts - please try again"
                log_info "USPTO API key format: 30 lowercase letters (a-z)"
            fi
        fi
    done

    log_error "Failed to provide valid USPTO API key after $max_attempts attempts"
    return 1
}

# Prompt for Mistral API key with validation loop (optional, with existing key detection)
prompt_and_validate_mistral_key() {
    local key=""
    local max_attempts=3
    local attempt=0

    # STEP 1: Check if key already exists in secure storage
    if check_existing_mistral_key; then
        log_info "Checking existing Mistral API key from another USPTO MCP installation..."

        # Try to load the existing key
        local existing_key=$(load_existing_mistral_key)
        if [[ $? -eq 0 && -n "$existing_key" ]]; then
            # Mask the key for display
            local masked_key=$(mask_api_key "$existing_key")

            # Ask user if they want to use it
            if prompt_use_existing_key "Mistral" "$masked_key"; then
                log_success "Using existing Mistral API key from secure storage"
                echo "$existing_key"
                return 0
            else
                log_info "You chose to enter a new Mistral API key"
                log_warning "This will OVERWRITE the existing key for ALL USPTO MCPs"
                read -p "Are you sure you want to continue? (y/N): " CONFIRM_OVERWRITE
                if [[ ! "$CONFIRM_OVERWRITE" =~ ^[Yy]$ ]]; then
                    log_info "Keeping existing key"
                    echo "$existing_key"
                    return 0
                fi
            fi
        else
            log_warning "Existing key file found but could not load (may be corrupted)"
            log_info "You will need to enter a new key"
        fi
    fi

    # STEP 2: Prompt for new key (either no existing key, or user wants to override)
    log_info "Mistral API key is OPTIONAL (for OCR on scanned documents)"
    log_info "Press Enter to skip, or enter your 32-character Mistral API key"
    echo

    while [[ $attempt -lt $max_attempts ]]; do
        ((attempt++))

        read_api_key_secure "Enter your Mistral API key (or press Enter to skip)" key

        # Empty is OK (optional)
        if [[ -z "$key" ]]; then
            log_info "Skipping Mistral API key (OCR disabled)"
            echo ""  # Return empty string
            return 0
        fi

        if validate_mistral_api_key "$key"; then
            # Success - return key
            echo "$key"
            return 0
        else
            if [[ $attempt -lt $max_attempts ]]; then
                log_warning "Attempt $attempt of $max_attempts - please try again"
                log_info "Mistral API key format: 32 alphanumeric characters (a-z, A-Z, 0-9)"
            fi
        fi
    done

    log_error "Failed to provide valid Mistral API key after $max_attempts attempts"
    return 1
}

# ============================================
# Secret Generation Functions
# ============================================

# Generate a secure random secret (for INTERNAL_AUTH_SECRET)
generate_secure_secret() {
    local length="${1:-32}"  # Default 32 bytes

    # Try multiple methods in order of preference
    if command -v openssl &> /dev/null; then
        # OpenSSL method (most common)
        openssl rand -base64 "$length" | tr -d '\n'
        return 0
    elif command -v python3 &> /dev/null; then
        # Python method
        python3 -c "import secrets; print(secrets.token_urlsafe($length))"
        return 0
    elif [[ -e /dev/urandom ]]; then
        # /dev/urandom method (Linux/Unix)
        head -c "$length" /dev/urandom | base64 | tr -d '\n'
        return 0
    else
        log_error "Cannot generate secure random secret - no suitable method found"
        log_error "Please install openssl or python3"
        return 1
    fi
}

# ============================================
# Utility Functions
# ============================================

# Display API key format requirements
show_api_key_requirements() {
    echo
    echo "API Key Format Requirements:"
    echo "============================="
    echo
    echo "USPTO API Key:"
    echo "  - Required: YES"
    echo "  - Length: Exactly 30 characters"
    echo "  - Format: Lowercase letters only (a-z)"
    echo "  - Example: abcdefghijklmnopqrstuvwxyzabcd"
    echo "  - Get from: https://data.uspto.gov/myodp/"
    echo
    echo "Mistral API Key:"
    echo "  - Required: NO (optional, for OCR)"
    echo "  - Length: Exactly 32 characters"
    echo "  - Format: Letters (a-z, A-Z) and numbers (0-9)"
    echo "  - Example: AbCdEfGh1234567890IjKlMnOp1234"
    echo "  - Get from: https://console.mistral.ai/"
    echo
}

# Mask API key for display (show last 5 characters only)
mask_api_key() {
    local key="$1"
    local visible_chars="${2:-5}"

    if [[ -z "$key" ]]; then
        echo "[Not set]"
    elif [[ ${#key} -le $visible_chars ]]; then
        echo "***"
    else
        local key_length=${#key}
        local masked_length=$((key_length - visible_chars))
        local asterisks=$(printf '*%.0s' $(seq 1 $masked_length))
        echo "${asterisks}${key: -$visible_chars}"
    fi
}

# ============================================
# Export Functions
# ============================================

# Note: In bash, functions are automatically available after sourcing
# No need for explicit exports, but we can document which functions are public API

# Public API functions:
# - validate_uspto_api_key
# - validate_mistral_api_key
# - validate_path
# - prompt_and_validate_uspto_key
# - prompt_and_validate_mistral_key
# - generate_secure_secret
# - show_api_key_requirements
# - mask_api_key
