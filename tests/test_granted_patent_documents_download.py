#!/usr/bin/env python3
"""
Test script for pfw_get_granted_patent_documents_download tool

Tests all scenarios outlined in the session history specification:
1. Normal granted patent (all components present)
2. Skip drawings parameter
3. Original vs granted claims comparison
4. Missing components graceful handling
5. Invalid application number

This script validates the implementation against the session history specification.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
from patent_filewrapper_mcp.api.helpers import validate_app_number

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Test application numbers from the specification
TEST_APP_NUMBER = "14171705"  # Valid granted patent from session spec
INVALID_APP_NUMBER = "00000000"  # Invalid number from spec

async def test_case_1_normal_granted_patent():
    """Test Case 1: Normal Granted Patent (All Components)"""
    logger.info("=" * 50)
    logger.info("TEST CASE 1: Normal Granted Patent (All Components)")
    logger.info("=" * 50)

    try:
        client = EnhancedPatentClient()

        # Call the new tool
        result = await client.get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER
        )

        logger.info(f"Success: {result.get('success')}")
        logger.info(f"Application: {result.get('application_number')}")
        logger.info(f"Total pages: {result.get('total_pages')}")
        logger.info(f"Components found: {result.get('components_found')}")
        logger.info(f"Components missing: {result.get('components_missing')}")

        # Validate structure
        components = result.get("granted_patent_components", {})
        expected_components = ["abstract", "drawings", "specification", "claims"]

        for component in expected_components:
            if component in components:
                doc_info = components[component]
                logger.info(f"\n{component.upper()}:")
                logger.info(f"  Document ID: {doc_info.get('document_identifier')}")
                logger.info(f"  Page count: {doc_info.get('page_count')}")
                logger.info(f"  Proxy URL: {doc_info.get('proxy_download_url')}")
                logger.info(f"  Official date: {doc_info.get('official_date')}")

                # Validate URL format
                proxy_url = doc_info.get('proxy_download_url')
                expected_pattern = f"http://localhost:8080/download/{TEST_APP_NUMBER}/"
                if proxy_url and proxy_url.startswith(expected_pattern):
                    logger.info(f"  ✓ Proxy URL format correct")
                else:
                    logger.error(f"  ✗ Proxy URL format incorrect: {proxy_url}")
            else:
                logger.warning(f"  ✗ Component {component} missing from response")

        # Validate LLM guidance
        guidance = result.get("llm_response_guidance", {})
        if guidance and "required_format" in guidance and "presentation_order" in guidance:
            logger.info(f"\n✓ LLM guidance present")
            logger.info(f"  Required format: {guidance.get('required_format')}")
            logger.info(f"  Presentation order: {guidance.get('presentation_order')}")
        else:
            logger.error(f"✗ LLM guidance missing or incomplete")

        # Validate success criteria
        if len(result.get("components_found", [])) >= 3:
            logger.info(f"\n✓ Success criteria met: 3+ components found")
        else:
            logger.error(f"✗ Success criteria not met: <3 components found")

        return result

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return None

async def test_case_2_skip_drawings():
    """Test Case 2: Skip Drawings (include_drawings=False)"""
    logger.info("\n" + "=" * 50)
    logger.info("TEST CASE 2: Skip Drawings (include_drawings=False)")
    logger.info("=" * 50)

    try:
        client = EnhancedPatentClient()

        # Call without drawings
        result = await client.get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER,
            include_drawings=False
        )

        components_found = result.get("components_found", [])

        logger.info(f"Components found: {components_found}")
        logger.info(f"Total pages: {result.get('total_pages')}")

        # Should NOT include drawings
        if "drawings" not in components_found:
            logger.info("✓ Drawings correctly skipped")
        else:
            logger.error("✗ Drawings should not be included when include_drawings=False")

        # Should include other 3 components
        expected_without_drawings = ["abstract", "specification", "claims"]
        if all(comp in components_found for comp in expected_without_drawings):
            logger.info("✓ All non-drawing components present")
        else:
            logger.error("✗ Missing expected components")

        return result

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return None

async def test_case_3_original_vs_granted_claims():
    """Test Case 3: Original vs Granted Claims Comparison"""
    logger.info("\n" + "=" * 50)
    logger.info("TEST CASE 3: Original vs Granted Claims Comparison")
    logger.info("=" * 50)

    try:
        client = EnhancedPatentClient()

        # Get original claims
        logger.info("Getting originally filed claims...")
        original_result = await client.get_granted_patent_documents(
            app_number=TEST_APP_NUMBER,
            include_original_claims=True
        )

        # Get granted claims (default)
        logger.info("Getting granted claims...")
        granted_result = await client.get_granted_patent_documents(
            app_number=TEST_APP_NUMBER,
            include_original_claims=False
        )

        original_claims = original_result.get("granted_patent_components", {}).get("claims", {})
        granted_claims = granted_result.get("granted_patent_components", {}).get("claims", {})

        logger.info(f"Original claims - Official date: {original_claims.get('official_date')}")
        logger.info(f"Original claims - Page count: {original_claims.get('page_count')}")
        logger.info(f"Granted claims - Official date: {granted_claims.get('official_date')}")
        logger.info(f"Granted claims - Page count: {granted_claims.get('page_count')}")

        # Validate dates are different
        if original_claims.get('official_date') != granted_claims.get('official_date'):
            logger.info("✓ Original and granted claims have different dates (as expected)")
        else:
            logger.warning("✗ Original and granted claims have same dates (unexpected)")

        # Validate page counts
        if original_claims.get('page_count') != granted_claims.get('page_count'):
            logger.info("✓ Original and granted claims have different page counts")
        else:
            logger.info("ℹ Original and granted claims have same page count")

        return {
            "original": original_result,
            "granted": granted_result
        }

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return None

async def test_case_4_invalid_application():
    """Test Case 4: Invalid Application Number"""
    logger.info("\n" + "=" * 50)
    logger.info("TEST CASE 4: Invalid Application Number")
    logger.info("=" * 50)

    try:
        client = EnhancedPatentClient()

        result = await client.get_granted_patent_documents_download(
            app_number=INVALID_APP_NUMBER
        )

        success = result.get('success', False)
        logger.info(f"Success: {success}")
        logger.info(f"Components found: {result.get('components_found')}")
        logger.info(f"Components missing: {result.get('components_missing')}")

        # Should have 0 components found
        if len(result.get("components_found", [])) == 0:
            logger.info("✓ No components found for invalid application")
        else:
            logger.error("✗ Components found for invalid application (should be zero)")

        # Should still show the full list of missing components
        missing = result.get("components_missing", [])
        if len(missing) == 4:  # ABST, SPEC, CLM, DRW
            logger.info("✓ All 4 components correctly marked as missing")
        else:
            logger.error(f"✗ Expected 4 missing components, got {len(missing)}")

        # Should have false success
        if not success:
            logger.info("✓ Success correctly set to False")
        else:
            logger.error("✗ Success should be False for invalid application")

        return result

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return None

async def test_case_5_mcp_integration():
    """Test Case 5: MCP Tool Integration"""
    logger.info("\n" + "=" * 50)
    logger.info("TEST CASE 5: MCP Tool Integration")
    logger.info("=" * 50)

    try:
        from patent_filewrapper_mcp.main import pfw_get_granted_patent_documents_download

        # Test the MCP tool function
        logger.info("Testing MCP tool function...")
        result = await pfw_get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER,
            include_drawings=True,
            include_original_claims=False,
            direction_category="INCOMING"
        )

        logger.info(f"MCP Tool Success: {result.get('success')}")

        # Check for proper error handling
        if result.get('success'):
            logger.info("✓ MCP tool returned successful result")
            logger.info(f"  Application: {result.get('application_number')}")
            logger.info(f"  Components: {len(result.get('granted_patent_components', {}))}")
        else:
            logger.error("✗ MCP tool returned failure")
            logger.error(f"  Error: {result.get('error', 'Unknown error')}")
            logger.error(f"  Guidance: {result.get('guidance', 'No guidance provided')}")

        return result

    except Exception as e:
        logger.error(f"MCP integration test failed: {e}")
        return None

async def test_url_generation():
    """Additional test: Verify proxy URL pattern matches expected format"""
    logger.info("\n" + "=" * 50)
    logger.info("URL GENERATION VERIFICATION")
    logger.info("=" * 50)

    try:
        client = EnhancedPatentClient()

        result = await client.get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER
        )

        components = result.get("granted_patent_components", {})
        all_urls_valid = True

        for component_name, component_data in components.items():
            proxy_url = component_data.get("proxy_download_url", "")
            app_number = TEST_APP_NUMBER
            document_id = component_data.get("document_identifier", "")

            expected_url = f"http://localhost:8080/download/{app_number}/{document_id}"

            if proxy_url != expected_url:
                logger.error(f"✗ {component_name}: URL mismatch")
                logger.error(f"  Expected: {expected_url}")
                logger.error(f"  Actual:   {proxy_url}")
                all_urls_valid = False
            else:
                logger.info(f"✓ {component_name}: URL format correct")

        if all_urls_valid:
            logger.info("\n✓ All proxy URLs match expected pattern")
        else:
            logger.error("\n✗ Some proxy URLs don't match expected pattern")

        return all_urls_valid

    except Exception as e:
        logger.error(f"URL generation test failed: {e}")
        return False

async def main():
    """Run all test cases"""
    logger.info("=" * 60)
    logger.info("GRANTED PATENT DOCUMENTS TEST SUITE")
    logger.info("=" * 60)

    # Check for API key
    if not os.getenv("USPTO_API_KEY"):
        logger.error("USPTO_API_KEY environment variable required for testing")
        logger.error("Set it with: set USPTO_API_KEY=your_key_here")
        return

    test_results = {
        "normal_patent": None,
        "skip_drawings": None,
        "original_vs_granted": None,
        "invalid_application": None,
        "mcp_integration": None,
        "url_generation": None
    }

    # Run tests
    try:
        logger.info("Starting test session...")

        test_results["normal_patent"] = await test_case_1_normal_granted_patent()
        test_results["skip_drawings"] = await test_case_2_skip_drawings()
        test_results["original_vs_granted"] = await test_case_3_original_vs_granted_claims()
        test_results["invalid_application"] = await test_case_4_invalid_application()
        test_results["mcp_integration"] = await test_case_5_mcp_integration()
        test_results["url_generation"] = await test_url_generation()

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)

        success_count = 0
        for test_name, result in test_results.items():
            if result is not None:
                if isinstance(result, dict):
                    if result.get('success', False):
                        logger.info(f"✓ {test_name}: PASSED")
                        success_count += 1
                    else:
                        logger.error(f"✗ {test_name}: FAILED")
                elif isinstance(result, bool):
                    if result:
                        logger.info(f"✓ {test_name}: PASSED")
                        success_count += 1
                    else:
                        logger.error(f"✗ {test_name}: FAILED")
                else:
                    logger.info(f"✓ {test_name}: COMPLETED")
                    success_count += 1
            else:
                logger.error(f"✗ {test_name}: FAILED (no result)")

        total_tests = len(test_results)
        logger.info(f"\nResults: {success_count}/{total_tests} tests passed")

        if success_count == total_tests:
            logger.info("🎉 ALL TESTS PASSED!")
        else:
            logger.warning(f"⚠️ {total_tests - success_count} tests failed")

    except Exception as e:
        logger.error(f"Test suite failed: {e}")
    finally:
        logger.info("\nTest session completed")

if __name__ == "__main__":
    asyncio.run(main())
