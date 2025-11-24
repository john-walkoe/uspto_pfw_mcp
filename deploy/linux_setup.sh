#!/bin/bash
# Linux Deployment Script for Patent File Wrapper MCP

set -e  # Exit on error

echo "=== Patent File Wrapper MCP - Linux Setup ==="
echo ""

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper functions
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source validation helpers for API key validation
source "$SCRIPT_DIR/validation_helpers.sh"

# Check if Python is installed
# Check if Python is needed (uv will handle it)
log_info "UV will handle Python installation automatically"

# Step 1: Check/Install uv
if ! command -v uv &> /dev/null; then
    log_info "uv not found. Installing uv package manager..."

    # Install uv using the official installer
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        # Add uv to PATH for current session
        export PATH="$HOME/.cargo/bin:$PATH"

        # Verify installation
        if command -v uv &> /dev/null; then
            log_success "uv installed successfully"
        else
            log_error "Failed to install uv. Please install manually:"
            echo -e "${YELLOW}   curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
            exit 1
        fi
    else
        log_error "Failed to install uv automatically"
        exit 1
    fi
else
    UV_VERSION=$(uv --version)
    log_info "uv found: $UV_VERSION"
fi

# Step 2: Install dependencies
log_info "Installing project dependencies with uv..."
cd "$PROJECT_DIR"

if uv sync; then
    log_success "Dependencies installed successfully"
else
    log_error "Failed to install dependencies"
    exit 1
fi

# Step 3: Install package in editable mode
log_info "Installing Patent File Wrapper MCP package..."
if uv pip install -e .; then
    log_success "Package installed successfully"
else
    log_error "Failed to install package"
    exit 1
fi

# Step 4: Verify installation
log_info "Verifying installation..."
if command -v patent-filewrapper-mcp &> /dev/null; then
    log_success "Command available: $(which patent-filewrapper-mcp)"
elif uv run python -c "import src.patent_filewrapper_mcp; print('Import successful')" &> /dev/null; then
    log_success "Package import successful - can run with: uv run patent-filewrapper-mcp"
else
    log_warning "Installation verification failed"
    log_info "You can run the server with: uv run patent-filewrapper-mcp"
fi

# Step 5: API Key Configuration
echo ""
log_info "API Key Configuration"
echo ""

# Show API key requirements
show_api_key_requirements

# Prompt for USPTO API key with validation
USPTO_API_KEY=$(prompt_and_validate_uspto_key)
if [[ -z "$USPTO_API_KEY" ]]; then
    log_error "Failed to obtain valid USPTO API key"
    exit 1
fi

log_success "USPTO API key validated and configured"

echo ""
# Prompt for Mistral API key with validation (optional)
MISTRAL_API_KEY=$(prompt_and_validate_mistral_key)
if [[ $? -ne 0 ]]; then
    log_error "Failed to obtain valid Mistral API key"
    exit 1
fi

if [[ -n "$MISTRAL_API_KEY" ]]; then
    log_success "Mistral API key validated and configured (OCR enabled)"
else
    log_info "Skipping Mistral API key (OCR disabled)"
fi

# Step 6: Claude Code Configuration
echo ""
log_info "Claude Code Configuration"
echo ""

read -p "Would you like to configure Claude Code integration? (Y/n): " CONFIGURE_CLAUDE
CONFIGURE_CLAUDE=${CONFIGURE_CLAUDE:-Y}

if [[ "$CONFIGURE_CLAUDE" =~ ^[Yy]$ ]]; then
    # Claude Code config location (Linux)
    CLAUDE_CONFIG_FILE="$HOME/.claude.json"

    log_info "Claude Code config location: $CLAUDE_CONFIG_FILE"

    if [ -f "$CLAUDE_CONFIG_FILE" ]; then
        log_info "Existing Claude Code config found"
        log_info "Merging Patent File Wrapper configuration with existing config..."

        # Backup the original file
        BACKUP_FILE="${CLAUDE_CONFIG_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
        cp "$CLAUDE_CONFIG_FILE" "$BACKUP_FILE"
        chmod 600 "$BACKUP_FILE"  # Secure backup file permissions
        log_info "Backup created: $BACKUP_FILE"

        # Use Python to merge JSON configuration with proper variable handling
        MERGE_SCRIPT="
import json
import sys
import os

try:
    # Read existing config
    with open('$CLAUDE_CONFIG_FILE', 'r') as f:
        config = json.load(f)

    # Ensure mcpServers exists
    if 'mcpServers' not in config:
        config['mcpServers'] = {}

    # Get API keys from environment (safer than string interpolation)
    uspto_key = os.environ.get('MERGE_USPTO_API_KEY', '')
    mistral_key = os.environ.get('MERGE_MISTRAL_API_KEY', '')

    # Add or update uspto_pfw server
    server_config = {
        'command': 'uv',
        'args': [
            '--directory',
            '$PROJECT_DIR',
            'run',
            'patent-filewrapper-mcp'
        ],
        'env': {
            'USPTO_API_KEY': uspto_key
        }
    }

    # Add Mistral API key if provided
    if mistral_key:
        server_config['env']['MISTRAL_API_KEY'] = mistral_key

    config['mcpServers']['uspto_pfw'] = server_config

    # Write merged config
    with open('$CLAUDE_CONFIG_FILE', 'w') as f:
        json.dump(config, f, indent=2)

    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

        if MERGE_USPTO_API_KEY="$USPTO_API_KEY" MERGE_MISTRAL_API_KEY="$MISTRAL_API_KEY" echo "$MERGE_SCRIPT" | python3; then
            # Secure the configuration file and directory
            chmod 600 "$CLAUDE_CONFIG_FILE"
            chmod 700 "$(dirname "$CLAUDE_CONFIG_FILE")"
            log_success "Successfully merged Patent File Wrapper configuration!"
            log_success "Your existing MCP servers have been preserved"
            log_success "Secured config file permissions (chmod 600)"
        else
            log_error "Failed to merge config"
            log_info "Please manually add the configuration to $CLAUDE_CONFIG_FILE"
            exit 1
        fi

    else
        # Create new config file
        log_info "Creating new Claude Code config..."

        # Use Python to create new config safely
        CREATE_SCRIPT="
import json
import sys
import os

try:
    # Get API keys from environment
    uspto_key = os.environ.get('CREATE_USPTO_API_KEY', '')
    mistral_key = os.environ.get('CREATE_MISTRAL_API_KEY', '')

    # Create new config
    config = {
        'mcpServers': {
            'uspto_pfw': {
                'command': 'uv',
                'args': [
                    '--directory',
                    '$PROJECT_DIR',
                    'run',
                    'patent-filewrapper-mcp'
                ],
                'env': {
                    'USPTO_API_KEY': uspto_key
                }
            }
        }
    }

    # Add Mistral API key if provided
    if mistral_key:
        config['mcpServers']['uspto_pfw']['env']['MISTRAL_API_KEY'] = mistral_key

    # Write config
    with open('$CLAUDE_CONFIG_FILE', 'w') as f:
        json.dump(config, f, indent=2)

    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

        if CREATE_USPTO_API_KEY="$USPTO_API_KEY" CREATE_MISTRAL_API_KEY="$MISTRAL_API_KEY" echo "$CREATE_SCRIPT" | python3; then
            # Secure the configuration file and directory
            chmod 600 "$CLAUDE_CONFIG_FILE"
            chmod 700 "$(dirname "$CLAUDE_CONFIG_FILE")"
            log_success "Created new Claude Code config"
            log_success "Secured config file permissions (chmod 600)"
        else
            log_error "Failed to create config"
            return 1
        fi
    fi

    log_success "Claude Code configuration complete!"
else
    log_info "Skipping Claude Code configuration"
    log_info "You can manually configure later by adding to ~/.claude.json"
fi

echo ""
log_success "Linux setup complete!"
log_warning "Please restart Claude Code to load the MCP server"
echo ""

log_info "Configuration Summary:"
log_success "USPTO API Key: Configured"
if [[ -n "$MISTRAL_API_KEY" ]]; then
    log_success "Mistral API Key: Configured (OCR enabled)"
else
    log_info "Mistral API Key: Not configured (OCR disabled)"
fi
log_success "Installation Directory: $PROJECT_DIR"
echo ""

log_info "Test the server:"
echo "  uv run patent-filewrapper-mcp --help"
echo ""

log_info "Test with Claude Code:"
echo "  Ask Claude: 'Use patent-filewrapper:pfw_search_applications_minimal to search for patents'"
echo ""
