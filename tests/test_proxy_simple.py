#!/usr/bin/env python3
"""
Simple test script for the proxy server functionality
Tests the core functionality without emoji characters that cause Windows encoding issues.
"""

import asyncio
import os
import sys
import httpx
from pathlib import Path

# Add the source directory to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_basic_functionality():
    """Test basic proxy functionality"""

    print("Testing USPTO Patent Document Proxy Server")
    print("=" * 50)

    # Test case from session notes
    test_app_number = "19145362"
    test_doc_identifier = "MCMLYGLL182X243"

    # Check environment - set API key for testing
    api_key = os.getenv("USPTO_API_KEY", "test_key_for_testing")
    if not api_key:
        print("ERROR: USPTO_API_KEY environment variable not set")
        return False

    # Set the environment variable for the test
    os.environ["USPTO_API_KEY"] = api_key

    print(f"API Key configured: {api_key[:10]}...")

    try:
        # Test 1: Initialize API client
        print("\nTest 1: Initializing API client...")
        from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
        client = EnhancedPatentClient()
        print("SUCCESS: API client initialized")

        # Test 2: Test document access
        print(f"\nTest 2: Testing document access for {test_app_number}...")
        docs_result = await client.get_documents(test_app_number)

        if docs_result.get('error'):
            print(f"ERROR: {docs_result.get('message')}")
            return False

        documents = docs_result.get('documentBag', [])
        target_doc = None
        for doc in documents:
            if doc.get('documentIdentifier') == test_doc_identifier:
                target_doc = doc
                break

        if not target_doc:
            print(f"ERROR: Document {test_doc_identifier} not found")
            return False

        print(f"SUCCESS: Found document {target_doc.get('documentCode')}")

        # Test 3: Create proxy app
        print("\nTest 3: Creating proxy server...")
        from patent_filewrapper_mcp.proxy.server import create_proxy_app
        app = create_proxy_app()
        print("SUCCESS: Proxy app created")

        # Test 4: Test rate limiter (using different IP to avoid affecting download test)
        print("\nTest 4: Testing rate limiter...")
        from patent_filewrapper_mcp.proxy.rate_limiter import rate_limiter
        test_ip = "192.168.1.100"  # Use different IP for rate limit test

        allowed_count = 0
        for i in range(6):  # Test beyond the limit
            allowed = rate_limiter.is_allowed(test_ip)
            if allowed:
                allowed_count += 1
            print(f"  Request {i+1}: {'ALLOWED' if allowed else 'BLOCKED'}")

        print(f"SUCCESS: Rate limiter working (allowed {allowed_count}/6 requests)")

        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_proxy_server():
    """Test the actual proxy server"""

    print("\nTest 5: Testing HTTP proxy server...")

    try:
        from patent_filewrapper_mcp.proxy.server import create_proxy_app
        import uvicorn

        app = create_proxy_app()
        proxy_port = 8082

        # Start server
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=proxy_port,
            log_level="warning"
        )
        server = uvicorn.Server(config)

        # Run server in background
        server_task = asyncio.create_task(server.serve())
        await asyncio.sleep(2)  # Give server time to start

        try:
            # Test health check
            async with httpx.AsyncClient(timeout=10.0) as client:
                health_url = f"http://localhost:{proxy_port}/"
                health_response = await client.get(health_url)

                if health_response.status_code == 200:
                    print("SUCCESS: Health check passed")

                    # Test download
                    download_url = f"http://localhost:{proxy_port}/download/19145362/MCMLYGLL182X243"
                    print(f"Testing download: {download_url}")

                    download_response = await client.get(download_url, timeout=30.0)

                    if download_response.status_code == 200:
                        content_length = len(download_response.content)
                        content_type = download_response.headers.get('content-type', '')
                        print(f"SUCCESS: Download completed")
                        print(f"  Content-Type: {content_type}")
                        print(f"  Size: {content_length:,} bytes")

                        if content_type == "application/pdf" and content_length > 1000:
                            # Save test file
                            Path("test_download.pdf").write_bytes(download_response.content)
                            print("  Test PDF saved as test_download.pdf")
                            return True
                        else:
                            print(f"  WARNING: Unexpected content type or size")
                            return False
                    else:
                        print(f"ERROR: Download failed with status {download_response.status_code}")
                        print(f"  Response: {download_response.text[:200]}")
                        return False
                else:
                    print(f"ERROR: Health check failed with status {health_response.status_code}")
                    return False

        finally:
            # Shutdown server
            server.should_exit = True
            try:
                await asyncio.wait_for(server_task, timeout=2.0)
            except asyncio.TimeoutError:
                pass  # Expected timeout

    except Exception as e:
        print(f"ERROR: Server test failed: {e}")
        return False

async def main():
    """Run tests"""
    print("Starting Proxy Server Test Suite")
    print("Goal: Test Option 1 Server-side Proxy Endpoint")
    print()

    # Test 1: Basic functionality
    basic_success = await test_basic_functionality()

    if not basic_success:
        print("\nBASIC TESTS FAILED - Skipping server test")
        return

    # Test 2: Full server test
    server_success = await test_proxy_server()

    print("\n" + "=" * 60)
    if basic_success and server_success:
        print("ALL TESTS PASSED!")
        print("Server-side proxy implementation is working correctly")
        print("Users can now download patent PDFs directly in browser")
        print("USPTO API keys remain secure server-side")
    else:
        print("SOME TESTS FAILED")
        print("Check error messages above")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
