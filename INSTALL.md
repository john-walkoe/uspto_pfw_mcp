# Installation Guide - Patent File Wrapper MCP

Complete cross-platform installation guide using modern package managers and automated setup scripts.

## 🚀 Quick Start Windows (Recommended)

**Run PowerShell as Administrator**, then:

```powershell
# Navigate to your user profile
cd $env:USERPROFILE

# If git is installed:
git clone https://github.com/john-walkoe/uspto_pfw_mcp.git
cd uspto_pfw_mcp

# If git is NOT installed:
# Download and extract the repository to C:\Users\YOUR_USERNAME\uspto_pfw_mcp
# Then navigate to the folder:
# cd C:\Users\YOUR_USERNAME\uspto_pfw_mcp

# The script detects if uv is installed and if it is not it will install uv - https://docs.astral.sh/uv

# Run setup script (sets execution policy for this session only):
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process
.\deploy\windows_setup.ps1

# View INSTALL.md for sample script output.
# Close Powershell Window.
# If choose option to "configure Claude Desktop integration" during the script then restart Claude Desktop
```

The PowerShell script will:
- ✅ Check for and auto-install uv (via winget or PowerShell script)
- ✅ Install dependencies and create executable
- ✅ Prompt for USPTO API key (required) and Mistral API key (optional) - See **[API_KEY_GUIDE.md](API_KEY_GUIDE.md)** for detailed API key setup instructions
- 🔒 **Automatically store API keys securely using Windows DPAPI encryption**
- ✅ Ask if you want Claude Desktop integration configured
- 🔒 **Offer secure configuration method (recommended) or traditional method**
- ✅ Automatically merge with existing Claude Desktop config (preserves other MCP servers)
- ✅ Create timestamped backups before modifying existing configs
- ✅ Provide installation summary and next steps

**Example Windows Output:**

```
PS C:\Users\YOUR_USERNAME\uspto_pfw_mcp> .\deploy\windows_setup.ps1
=== Patent File Wrapper MCP - Windows Setup ===
[INFO] Python NOT required - uv will manage Python automatically

[INFO] uv not found. Installing uv...
Found uv [astral-sh.uv] Version 0.9.11
This application is licensed to you by its owner.
Microsoft is not responsible for, nor does it grant any licenses to, third-party packages.
This package requires the following dependencies:
  - Packages
      Microsoft.VCRedist.2015+.x64
Successfully verified installer hash
Extracting archive...
Successfully extracted archive
Starting package install...
Path environment variable modified; restart your shell to use the new value.
Command line alias added: "uvx"
Command line alias added: "uv"
Command line alias added: "uvw"
Successfully installed
[OK] uv installed via winget
[OK] uv is now accessible: uv 0.9.11 (8d8aabb88 2025-11-20)
[INFO] Installing dependencies with uv...
[INFO] Creating virtual environment...
Using CPython 3.12.11
Creating virtual environment at: .venv
Activate with: .venv\Scripts\activate
[OK] Virtual environment created at .venv
[OK] pyvenv.cfg already exists (newer uv version)
[INFO] Installing dependencies with prebuilt wheels (Python 3.12)...
Resolved 34 packages in 1ms
Installed 33 packages in 272ms
 + aiofiles==24.1.0
 + annotated-types==0.7.0
...
 + typing-inspection==0.4.1
 + uvicorn==0.34.3
[OK] Dependencies installed
[INFO] Verifying installation...
[INFO] Testing secure storage system...
[OK] Secure storage system working
[OK] Command available: C:\Users\YOUR_USERNAME\AppData\Roaming\Python\Python312\Scripts\patent-filewrapper-mcp.exe

Unified API Key Configuration

[INFO] Checking for existing API keys in unified storage...
[INFO] No API keys found in unified storage

API Key Format Requirements:
============================

USPTO API Key:
  - Required: YES
  - Length: Exactly 30 characters
  - Format: Lowercase letters only (a-z)
  - Example: abcdefghijklmnopqrstuvwxyzabcd
  - Get from: https://data.uspto.gov/myodp/

Mistral API Key:
  - Required: NO (optional, for OCR)
  - Length: Exactly 32 characters
  - Format: Letters (a-z, A-Z) and numbers (0-9)
  - Example: AbCdEfGh1234567890IjKlMnOp1234
  - Get from: https://console.mistral.ai/

Enter your USPTO API key: ****************************** [your_actual_USPTO_api_key_here]
[OK] USPTO API key format validated (30 chars, lowercase)
[INFO] Mistral API key is OPTIONAL (for OCR on scanned documents)
[INFO] Press Enter to skip, or enter your 32-character Mistral API key

Enter your Mistral API key (or press Enter to skip): ******************************** [your_mistral_api_key_here_OPTIONAL]
[OK] Mistral API key format validated (32 chars, alphanumeric)

[INFO] Storing API keys in unified secure storage...
[OK] USPTO API key stored in unified secure storage
     Location: ~/.uspto_api_key (DPAPI encrypted)
[OK] USPTO API key stored in unified storage
[OK] Mistral API key stored in unified secure storage
     Location: ~/.mistral_api_key (DPAPI encrypted)
[OK] Mistral API key stored in unified storage

[OK] Unified storage benefits:
     - Single-key-per-file architecture
     - DPAPI encryption (user + machine specific)
     - Shared across all USPTO MCPs (FPD/PFW/PTAB/Citations)
     - Files: ~/.uspto_api_key, ~/.mistral_api_key

[INFO] Configuring shared INTERNAL_AUTH_SECRET...
[OK] Using existing INTERNAL_AUTH_SECRET from unified storage
     Location: ~/.uspto_internal_auth_secret (DPAPI encrypted)
     Shared with other installed USPTO MCPs
     This secret authenticates internal MCP communication

Claude Desktop Configuration

Would you like to configure Claude Desktop integration? (Y/n): y

Claude Desktop Configuration Method:
  [1] Secure Python DPAPI (recommended) - API keys loaded from secure storage
  [2] Traditional - API keys stored in Claude Desktop config file

Enter choice (1 or 2, default is 1): 1
[OK] Using unified secure storage (no API keys in config file)
     API keys loaded automatically from ~/.uspto_api_key and ~/.mistral_api_key
     This configuration works with all USPTO MCPs sharing the same keys

[INFO] Claude Desktop config location: C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json
[INFO] Existing Claude Desktop config found
[INFO] Merging Patent File Wrapper MCP configuration with existing config...
[INFO] Backup created: C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json.backup_20251123_203353
[OK] Successfully merged Patent File Wrapper MCP configuration!
[OK] Your existing MCP servers have been preserved
[INFO] Configuration backup saved at: C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json.backup_20251123_203353
[OK] Claude Desktop configuration complete!

Windows setup complete!
Please restart Claude Desktop to load the MCP server

Configuration Summary:
  [OK] USPTO API Key: Stored in unified secure storage
       Location: ~/.uspto_api_key (DPAPI encrypted)
  [OK] Mistral API Key: Stored in unified secure storage
       Location: ~/.mistral_api_key (DPAPI encrypted)
  [OK] Storage Architecture: Single-key-per-file (shared across USPTO MCPs)
  [OK] Proxy Port: 8080 (centralized proxy server)
  [OK] Installation Directory: C:/Users/YOUR_USERNAME/uspto_pfw_mcp

Available Tools (12):
  - pfw_search_applications_minimal (ultra-fast discovery)
  - pfw_search_applications_balanced (detailed analysis)
  - pfw_search_by_assignee (patent portfolio analysis)
  - pfw_search_by_inventor (inventor analysis)
  - pfw_search_by_art_unit (art unit quality)
  - pfw_search_by_application_type (type analysis)
  - pfw_get_application_details (full details)
  - pfw_get_application_documents (document access)
  - pfw_get_transaction_history (prosecution history)
  - pfw_get_document_download (PDF downloads)
  - pfw_get_enhanced_search (multi-field advanced search)
  - pfw_get_tool_reflections (workflow guidance)

Centralized Proxy Server:
  Start with: uv run pfw-proxy
  Port: 8080 (provides enhanced features for all USPTO MCPs)

Key Management:
  Manage keys: ./deploy/manage_api_keys.ps1
  Test keys:   uv run python tests/test_unified_key_management.py
  Cross-MCP:   Keys shared with FPD, PTAB, and Citations MCPs

Test with: pfw_search_applications_minimal
Learn workflows: pfw_get_tool_reflections
PS C:\Users\YOUR_USERNAME\uspto_pfw_mcp>
```

## 🔒 Windows Secure Configuration Options

During the Windows setup, you'll be presented with two configuration methods:

### Method 1: Secure Python DPAPI (Recommended)

- 🔒 **API keys encrypted with Windows DPAPI**
- 🔒 **API keys not stored in Claude Desktop config file**
- ⚡ **Direct Python execution with built-in secure storage**
- ✅ **No PowerShell execution policy requirements**

**Example Configuration Generated:**

```json
{
  "mcpServers": {
    "uspto_pfw": {
      "command": "C:/Users/YOUR_USERNAME/uspto_pfw_mcp/.venv/Scripts/python.exe",
      "args": ["-m", "patent_filewrapper_mcp.main"],
      "cwd": "C:/Users/YOUR_USERNAME/uspto_pfw_mcp",
      "env": {
        "PROXY_PORT": "8080"
      }
    }
  }
}
```

### Method 2: Traditional

- 📄 **API keys stored in Claude Desktop config file**
- 🔓 **Less secure - keys visible in config**
- ⚡ **Direct Python execution**
- ✅ **Simpler setup**

**Example Configuration Generated:**

```json
{
  "mcpServers": {
    "uspto_pfw": {
      "command": "uv",
      "args": ["--directory", "C:/Users/YOUR_USERNAME/uspto_pfw_mcp", "run", "patent-filewrapper-mcp"],
      "env": {
        "USPTO_API_KEY": "your_actual_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_key_here",
        "PROXY_PORT": "8080"
      }
    }
  }
}
```

### Windows DPAPI Secure Storage API Key Management

If you want to manage your Secure Storage API keys manually:

```bash
# Navigate to your user profile
cd $env:USERPROFILE

# Navigate to the Project Folder
cd uspto_pfw_mcp

.\deploy\manage_api_keys.ps1

OUTPUT

USPTO MCP API Key Management
============================
MCP Type: PFW (Patent File Wrapper)

Current API Keys:
  USPTO API Key:   **************************seto
  Mistral API Key: ****************************D4c2

Actions:
  [1] Update USPTO API key
  [2] Update Mistral API key
  [3] Remove API key(s)
  [4] Test API key functionality
  [5] View INTERNAL_AUTH_SECRET (for manual config)
  [6] Show key requirements
  [7] Exit

Enter choice (1-7):

```

## :penguin: Quick Start Linux (Claude Code)

**Open terminal**, then:

```bash
# Navigate to your home directory
cd ~

# Clone the repository (if git is installed):
git clone https://github.com/john-walkoe/uspto_pfw_mcp.git
cd uspto_pfw_mcp

# If git is NOT installed:
# Download and extract the repository to ~/uspto_pfw_mcp
# Then navigate to the folder:
# cd ~/uspto_pfw_mcp

# Make script executable and run
chmod +x deploy/linux_setup.sh
./deploy/linux_setup.sh

# Restart Claude Code if you configured integration
```

**Note**: Claude Desktop is not available on Linux. The script configures Claude Code integration instead.

The Linux script will:

- ✅ Check for and auto-install uv package manager
- ✅ Install dependencies and create executable
- ✅ Prompt for USPTO API key (required) and Mistral API key (optional) - See **[API_KEY_GUIDE.md](API_KEY_GUIDE.md)** for detailed API key setup instructions
- ✅ Ask if you want Claude Code integration configured
- ✅ Automatically merge with existing Claude Code config (preserves other MCP servers)
- ✅ Create timestamped backups before modifying existing configs
- ✅ Provide installation summary and next steps

**Example Linux Output:**

```
USER@debian:~/uspto_pfw_mcp# ./deploy/linux_setup.sh
=== Patent File Wrapper MCP - Linux Setup ===

[INFO] UV will handle Python installation automatically
[INFO] uv found: uv 0.7.10
[INFO] Installing project dependencies with uv...
Using CPython 3.13.3
Creating virtual environment at: .venv
Resolved 34 packages in 0.60ms
      Built patent-filewrapper-mcp @ file:///USER/uspto_pfw_mcp
Prepared 1 package in 189ms
░░░░░░░░░░░░░░░░░░░░ [0/32] Installing wheels...                                                                                                                                  warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.[*]
Installed 32 packages in 4.53s
 + aiofiles==24.1.0
 + annotated-types==0.7.0
...
 + typing-inspection==0.4.1
 + uvicorn==0.34.3
[OK] Dependencies installed successfully
[INFO] Installing Patent File Wrapper MCP package...
Resolved 32 packages in 20ms
      Built patent-filewrapper-mcp @ file:///USER/uspto_pfw_mcp
Prepared 1 package in 180ms
Uninstalled 1 package in 33ms
░░░░░░░░░░░░░░░░░░░░ [0/1] Installing wheels...                                                                                                                                   warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.[*]
Installed 1 package in 133ms
 ~ patent-filewrapper-mcp==0.1.0 (from file:///USER/uspto_pfw_mcp)
[OK] Package installed successfully
[INFO] Verifying installation...
[OK] Command available: /USER/.pyenv/shims/patent-filewrapper-mcp

[INFO] API Key Configuration


API Key Format Requirements:
=============================

USPTO API Key:
  - Required: YES
  - Length: Exactly 30 characters
  - Format: Lowercase letters only (a-z)
  - Example: abcdefghijklmnopqrstuvwxyzabcd
  - Get from: https://data.uspto.gov/myodp/

Mistral API Key:
  - Required: NO (optional, for OCR)
  - Length: Exactly 32 characters
  - Format: Letters (a-z, A-Z) and numbers (0-9)
  - Example: AbCdEfGh1234567890IjKlMnOp1234
  - Get from: https://console.mistral.ai/

Enter your USPTO API key: [your_actual_USPTO_api_key_here[**]] [OK] USPTO API key validated and configured

Enter your Mistral API key (or press Enter to skip): [your_mistral_api_key_here_OPTIONAL[**]] [OK] Mistral API key validated and configured (OCR enabled)

[INFO] Claude Code Configuration

Would you like to configure Claude Code integration? (Y/n): y
[INFO] Claude Code config location: /USER/.claude.json
[INFO] Existing Claude Code config found
[INFO] Merging Patent File Wrapper configuration with existing config...
[INFO] Backup created: /USER/.claude.json.backup_20251123_212702
SUCCESS
[OK] Successfully merged Patent File Wrapper configuration!
[OK] Your existing MCP servers have been preserved
[OK] Secured config file permissions (chmod 600)
[OK] Claude Code configuration complete!

[OK] Linux setup complete!
[WARN] Please restart Claude Code to load the MCP server

[INFO] Configuration Summary:
[OK] USPTO API Key: Configured
[OK] Mistral API Key: Configured (OCR enabled)
[OK] Installation Directory: /USER/uspto_pfw_mcp

[INFO] Test the server:
  uv run patent-filewrapper-mcp --help

[INFO] Test with Claude Code:
  Ask Claude: 'Use uspto_pfw:pfw_search_applications_minimal to search for patents'

```

*The warnings are just uv being verbose about filesystem optimization.  This is similar to seeing compiler warnings that don't affect the final program - informational but not problematic.

** When typing in the API keys no output is displayed as a security feature.

**Test Claude Code's MCP**

```
USER@debian:~/uspto_pfw_mcp# claude mcp list
Checking MCP server health...

uspto_pfw: uv --directory /USER/uspto_pfw_mcp run patent-filewrapper-mcp - ✓ Connected
```

**Example Configuration Generated:**

```json
{
  "mcpServers": {
    "uspto_pfw": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/USER/uspto_pfw_mcp",
        "run",
        "patent-filewrapper-mcp"
      ],
      "env": {
        "USPTO_API_KEY": "your_actual_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL",
        "PROXY_PORT": "8080"
      }
    }
  }
```

## 🔀 n8n Integration (Linux)

For workflow automation with **locally hosted n8n instances**, you can integrate the USPTO PFW MCP as a node using nerding-io's community MCP client connector.

**Requirements:**
- ✅ **Self-hosted n8n instance** (local or server deployment)
- ✅ **n8n version 1.0.0+** (required for community nodes)
- ✅ **nerding-io's Community MPC Client node**: [n8n-nodes-mcp](https://github.com/nerding-io/n8n-nodes-mcp)
- ❌ **Cannot be used with n8n Cloud** (requires local filesystem access to MCP executables)

**For AI Agent Integration:**

- Must set `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true` environment variable

### Setup Steps

1. **Install n8n** (if not already installed):
   ```bash
   npm install -g n8n

   # Or using Docker with required environment variable
   docker run -it --rm --name n8n -p 5678:5678 \
     -e N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true \
     n8nio/n8n
   ```

2. **Install nerding-io's Community MPC Client  Node:**

   Follow the [n8n community nodes installation guide](https://docs.n8n.io/integrations/community-nodes/installation/):

   ```bash
   # Method 1: Via n8n UI
   # Go to Settings > Community Nodes > Install
   # Enter: n8n-nodes-mcp

   # Method 2: Via npm (for self-hosted)
   npm install n8n-nodes-mcp

   # Method 3: Via Docker environment
   # Add to docker-compose.yml:
   # environment:
   #   - N8N_NODES_INCLUDE=[n8n-nodes-mcp]
   ```

3. **Configure Credentials:**

   n8n MCP Configuration Example

   ![n8n Patent File Wrapper Interface](documentation_photos/n8n_PFW.jpg)

   - **Connection Type**: `Command-line Based Transport (STDIO)`
   - **Command**: `/home/YOUR_USERNAME/uspto_pfw_mcp/.venv/bin/patent-filewrapper-mcp` (see below step 4 on how to get)
   - **Arguments**: (leave empty)
   - **Environment Variables** (Entered in as Expression):

     ```
     USPTO_API_KEY=your_actual_USPTO_api_key_here
     MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL
     PROXY_PORT=8080
     ```

4. **Find MCP Executable Path:**
   Navigate to your PFW directory and run:
   ```bash
   cd /path/to/uspto_pfw_mcp
   uv run python -c "import sys; print(sys.executable)"
   ```

   This will return something like:
   ```
   /home/YOUR_USERNAME/uspto_pfw_mcp/.venv/bin/python3
   ```

   Take the directory path and append `patent-filewrapper-mcp` to get your command:
   ```
   /home/YOUR_USERNAME/uspto_pfw_mcp/.venv/bin/patent-filewrapper-mcp
   ```

   Use this full path as your command in the n8n MCP configuration.

5. **Add MCP Client Node:**
   - In n8n workflow editor, add "MCP Client (STDIO) API" node
   - Select your configured credentials
   - Choose operation (List Tools, Execute Tool, etc.)

6. **Test Connection:**
   - Use "List Tools" operation to see available USPTO PFW functions
   - Use "Execute Tool" operation with `pfw_search_applications_minimal`
   - Parameters example: `{"query": "artificial intelligence", "limit": 5}`

### Example n8n Workflow Use Cases

- **Automated Patent Monitoring:** Schedule searches for new patents in specific technology areas
- **Portfolio Management:** Regular analysis of competitor filings and prosecution status
- **Due Diligence Workflows:** Automated patent research for M&A activities
- **Citation Analysis:** Batch processing of patent citations and examiner patterns

The n8n integration enables powerful automation workflows combining USPTO patent data with other business systems.

## 🔧 Configuration

### Environment Variables

**Required:**
- `USPTO_API_KEY`: Your USPTO Open Data Portal API key (required, free from [USPTO Open Data Portal](https://data.uspto.gov/myodp/)) - See **[API_KEY_GUIDE.md](API_KEY_GUIDE.md)** for step-by-step setup instructions

**Optional with defaults:**
- `MISTRAL_API_KEY`: For OCR on scanned documents (Default: none - uses free PyPDF2 extraction)
- `PROXY_PORT`: HTTP proxy server port (Default: "8080")
- `ENABLE_ALWAYS_ON_PROXY`: Start proxy immediately vs on-demand (Default: "true")
- `ENABLE_PROXY_SERVER`: Enable/disable proxy functionality (Default: "true")

**Advanced (for development/testing):**
- `USPTO_TIMEOUT`: API request timeout in seconds (Default: "30.0")
- `USPTO_DOWNLOAD_TIMEOUT`: Document download timeout in seconds (Default: "60.0")

**Proxy Configuration:**

- **Default**: Proxy starts automatically when MCP server starts (`ENABLE_ALWAYS_ON_PROXY="true"`)
- **Disable**: Set `ENABLE_ALWAYS_ON_PROXY="false"` to start proxy only on first document download
- **Example of setting Custom Port**: Set `PROXY_PORT="8989"` to avoid conflicts with other services

### Claude Code MCP Configuration (Recommended)

**Method 1: Using Claude Code CLI**

```powershell
# Windows Powershell - uv installation (Claude Code)
claude mcp add uspto_pfw -s user `
  -e USPTO_API_KEY=your_actual_api_key_here `
  -e MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL `
  -e PROXY_PORT=8080 `
  -- uv --directory C:\Users\YOUR_USERNAME\uspto_pfw_mcp run patent-filewrapper-mcp

# Linux - uv installation (Claude Code)
claude mcp add uspto_pfw -s user \
  -e USPTO_API_KEY=your_actual_api_key_here \
  -e MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL \
  -e PROXY_PORT=8080 \
  -- uv --directory /home/YOUR_USERNAME/uspto_pfw_mcp run patent-filewrapper-mcp
```

### Claude Desktop Configuration

**For uv installations (recommended to use the deploy scripts so don't have to set this):**

```json
{
  "mcpServers": {
    "uspto_pfw": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/Users/YOUR_USERNAME/uspto_pfw_mcp",
        "run",
        "patent-filewrapper-mcp"
      ],
      "env": {
        "USPTO_API_KEY": "your_actual_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL",
        "PROXY_PORT": "8080"
      }
    }
  }
}
```

**For traditional pip installations:**
```json
{
  "mcpServers": {
    "uspto_pfw": {
      "command": "python",
      "args": [
        "-m",
        "patent_filewrapper_mcp"
      ],
      "cwd": "C:/Users/YOUR_USERNAME/uspto_pfw_mcp",
      "env": {
        "USPTO_API_KEY": "your_actual_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL",
        "PROXY_PORT": "8080"
      }
    }
  }
}
```

## 📋 Manual Installation

### Prerequisites

- **uv Package Manager** - Handles Python installation automatically
- **USPTO API Key** (required) - Free from [USPTO Open Data Portal](https://data.uspto.gov/myodp/) - See **[API_KEY_GUIDE.md](API_KEY_GUIDE.md)** for step-by-step setup instructions
- **Mistral API Key** (optional) - For OCR functionality from [Mistral AI](https://mistral.ai/solutions/document-ai) - See **[API_KEY_GUIDE.md](API_KEY_GUIDE.md)** for setup instructions
- **Claude Desktop or Claude Code** - For MCP integration

> **Note:** The Mistral API key is optional. Without it, document extraction uses free PyPDF2 (works for text-based PDFs). With it, OCR is available for scanned documents (~$0.001/page).

### 1. Install uv (if not already installed)

**Windows:**
```powershell
# Direct installation (no admin rights needed)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or using winget
winget install --id=astral-sh.uv -e
```

**Linux:**
```bash
# Direct installation
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to PATH (add to ~/.bashrc for persistence)
export PATH="$HOME/.local/bin:$PATH"
```

### 2. Clone & Install

```bash
# Clone repository
git clone <repository-url>
cd uspto_pfw_mcp

# Install dependencies (uv handles Python automatically)
uv sync

# Install in development mode
uv pip install -e .

# Verify installation
uv run patent-filewrapper-mcp --help
```

### 3. Set API Keys

```bash
# Set environment variables
export USPTO_API_KEY=your_actual_api_key_here     # Linux
export MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL  # Linux

# Optional: Configure API timeouts (defaults: USPTO_TIMEOUT=30.0, USPTO_DOWNLOAD_TIMEOUT=60.0)
export USPTO_TIMEOUT=30.0                         # API request timeout in seconds
export USPTO_DOWNLOAD_TIMEOUT=60.0                # Document download timeout in seconds

set USPTO_API_KEY=your_actual_api_key_here        # Windows Command
set MISTRAL_API_KEY=your_mistral_api_key_here_OPTIONAL     # Windows Command

$env:USPTO_API_KEY="your_actual_api_key_here"     # PowerShell
$env:MISTRAL_API_KEY="your_mistral_api_key_here_OPTIONAL"  # PowerShell

# Optional: Configure API timeouts (PowerShell)
$env:USPTO_TIMEOUT="30.0"                         # API request timeout in seconds
$env:USPTO_DOWNLOAD_TIMEOUT="60.0"                # Document download timeout in seconds
```

## 🧪 Test Installation

```bash
# Direct test
uv run python test_fields_fix.py

# Test specific functionality
uv run python -c "
import asyncio
from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

async def test():
    client = EnhancedPatentClient()
    result = await client.search_applications('test', limit=1)
    print('✅' if result.get('success') else '❌', 'API test result:', result.get('success', 'Failed'))

asyncio.run(test())
"

# Test in Claude Desktop/Code:
patent-filewrapper:pfw_search_applications_minimal {"query": "artificial intelligence", "limit": 1}
```

## 🗂️ Platform-Specific Notes

### Windows
- **Config Location:** `%APPDATA%\Claude\claude_desktop_config.json`
- **PowerShell:** Use forward slashes `/` in JSON paths even on Windows
- **Spaces in paths:** Use quotes in config files:
  ```json
  "args": ["--directory", "C:/Users/John Smith/uspto_pfw_mcp", "run", "patent-filewrapper-mcp"]
  ```

### Linux
- **Claude Code Config Location:** `~/.claude.json`
- **Environment:** Add exports to `~/.bashrc`
- **Note:** Claude Desktop is not available on Linux - use Claude Code instead

## 🔧 Alternative Installation Methods

### Using pip (fallback if uv unavailable)

```bash
# Requires Python 3.10+ already installed
python -m pip install -e .
```

Then use this Claude Desktop config:
```json
{
  "mcpServers": {
    "uspto_pfw": {
      "command": "python",
      "args": [
        "-m",
        "patent_filewrapper_mcp"
      ],
      "env": {
        "USPTO_API_KEY": "your_actual_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL"
      }
    }
  }
}
```

## 🔍 Troubleshooting

### Common Issues

**Virtual Environment Issues (Windows Setup):**

If you encounter virtual environment creation issues:

1. **Close Claude Desktop completely** before running the setup script
2. Claude Desktop locks `.venv` files when running, preventing proper virtual environment creation
3. Run cleanup commands before setup:
   ```powershell
   # Close Claude Desktop first, then run:
   Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue
   .\deploy\windows_setup.ps1
   ```

**API Key Issues:**
- **Windows**: Keys stored securely using DPAPI (no environment variables needed)
- **Linux/macOS**: Keys stored in environment variables
```bash
# Check environment variable (Linux/macOS only)
echo $USPTO_API_KEY
echo $MISTRAL_API_KEY
```
- **Test secure storage (Windows):**
  - Use the dedicated API key management script: `.\deploy\manage_api_keys.ps1`
  - See **Windows DPAPI Secure Storage API Key Management** section below for full details

**uv Not Found:**

```bash
# Reinstall uv
# Windows: winget install --id=astral-sh.uv -e
# Linux/macOS: curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Import Errors:**

```bash
# Reinstall dependencies
cd uspto_pfw_mcp
uv sync --reinstall
```

**Claude Desktop Config Issues:**
- Check JSON syntax with validator
- Verify file paths are correct
- Ensure API keys are set in environment or config

**Permission denied errors (Linux):**
```bash
# Fix ownership for project directory
sudo chown -R $(whoami):$(id -gn) ~/uspto_pfw_mcp

# Fix executable permissions (adjust path as needed)
chmod +x ~/.pyenv/shims/patent-filewrapper-mcp
# OR if using system Python:
# sudo chmod +x /usr/local/bin/patent-filewrapper-mcp
```

### Resetting MCP Installation

**If you need to completely reset the MCP installation to run the installer again:**

**Windows Reset:**
```powershell
# Navigate to the project directory
cd C:\Users\YOUR_USERNAME\uspto_pfw_mcp

# Remove Python cache directories
Get-ChildItem -Path ./src -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue
}

# Remove database files
Remove-Item ./proxy_link_cache.db -Force -ErrorAction SilentlyContinue
Remove-Item ./fpd_documents.db -Force -ErrorAction SilentlyContinue
Remove-Item ./ptab_documents.db -Force -ErrorAction SilentlyContinue

# Now you can run the setup script again
.\deploy\windows_setup.ps1
```

**Linux/macOS Reset:**
```bash
# Navigate to the project directory
cd ~/uspto_pfw_mcp

# Remove Python cache directories
find ./src -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Remove virtual environment and database files
rm -rf .venv
rm -f proxy_link_cache.db fpd_documents.db ptab_documents.db

# Run setup script again
./deploy/linux_setup.sh
```

### Installation Verification

**1. Test Core Functionality:**
```bash
# Test field mapping and core systems
uv run python tests/test_fields_fix.py

# Test MCP server startup
uv run patent-filewrapper-mcp --help
```

**2. Test MCP Integration (requires Claude Code or MCP client):**

In Claude Code, try these commands:
```
# Test inventor search
uspto_pfw:pfw_search_inventor {"name": "Smith", "limit": 2}

# Test application search
uspto_pfw:pfw_search_applications_minimal {"query": "artificial intelligence", "limit": 1}
```

**3. Verify MCP Connection:**
```bash
# If you have Claude Code CLI
claude mcp list

# Should show: uspto_pfw: ... - ✓ Connected
```

Expected response format:
```json
{
  "success": true,
  "total": 31511,
  "applications": [...],
  "context_info": {
    "context_reduction_achieved": "95-99% vs full response"
  }
}
```

## 📊 Performance Considerations

- **Memory**: Allocate at least 512MB RAM for the MCP server
- **CPU**: Single core sufficient for most use cases
- **Storage**: Ensure /tmp has enough space for PDF downloads
- **Network**: Good connectivity to api.uspto.gov

## 🛡️ Security

- Keep the USPTO and Mistral API keys secure
- Use HTTPS for external connections
- Consider firewall rules for the MCP server port
- Regular updates of dependencies

## 📈 Success Checklist

- [ ] Python 3.10+ installed
- [ ] uv package manager installed
- [ ] Patent MCP package installed
- [ ] System executable created and working
- [ ] USPTO API key configured
- [ ] Mistral API key configured (for OCR)
- [ ] Claude Desktop/Code config updated
- [ ] Claude Desktop/Code restarted
- [ ] MCP server responding to test queries
- [ ] Search functions returning expected results

## 🚀 Next Steps

Once setup is complete:

1. **Test thoroughly:** Run the test suite to verify all functions
2. **Optional Customize:** Modify field configurations in `field_configs.yaml`
3. **Monitor:** Set up logging and monitoring for production use

---

**Need help?** Check the main README troubleshooting section or examine the test scripts for working examples.
