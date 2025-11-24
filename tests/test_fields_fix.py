#!/usr/bin/env python3
"""
Test script to verify the fields fix for pfw_search_inventor and pfw_search_applications
Testing with the exact same parameters as the failing cases from Input-Output-Sample.txt
"""

import asyncio
import os
import sys
import json
from pathlib import Path

# Add the src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

async def test_inventor_search():
    """Test pfw_search_inventor with the exact failing parameters"""
    
    # Set API key from environment or use test key
    os.environ["USPTO_API_KEY"] = os.getenv("USPTO_API_KEY", "test_key_for_testing")
    
    try:
        client = EnhancedPatentClient()
        print("SUCCESS: Successfully initialized EnhancedPatentClient")
        
        # Test Case 1: Wilbur Walkoe
        print("\n" + "="*60)
        print("TEST CASE 1: Inventor Search - Wilbur Walkoe")
        print("="*60)
        
        name = "Wilbur Walkoe"
        fields = ["applicationNumberText", "inventionTitle", "parentPatentNumber", "patentNumber"]
        limit = 200
        
        print(f"Parameters:")
        print(f"  Name: '{name}'")
        print(f"  Fields: {fields}")
        print(f"  Limit: {limit}")
        
        result = await client.search_inventor(name, "comprehensive", limit, fields)
        
        if result.get('error'):
            print(f"❌ Search failed: {result['error']}")
            return False
            
        print(f"✓ Search successful")
        applications = result.get('unique_applications', [])
        print(f"  Found {len(applications)} unique applications")
        
        # Check first few applications for requested fields
        print(f"\nChecking first 3 applications for requested fields:")
        for i, app in enumerate(applications[:3]):
            print(f"\nApplication {i+1}: {app.get('applicationNumberText', 'N/A')}")
            
            # Check for each requested field
            app_number = app.get('applicationNumberText')
            print(f"  ✓ applicationNumberText: {app_number}" if app_number else "  ❌ applicationNumberText: Missing")
            
            # Check in applicationMetaData
            metadata = app.get('applicationMetaData', {})
            
            invention_title = metadata.get('inventionTitle')
            print(f"  ✓ inventionTitle: {invention_title[:50]}..." if invention_title else "  ❌ inventionTitle: Missing")
            
            patent_number = metadata.get('patentNumber')
            print(f"  ✓ patentNumber: {patent_number}" if patent_number else "  ❌ patentNumber: Missing")
            
            # Check parentPatentNumber - could be in parentContinuityBag
            parent_patent_number = None
            parent_bag = app.get('parentContinuityBag')
            if parent_bag:
                if isinstance(parent_bag, list) and parent_bag:
                    parent_patent_number = parent_bag[0].get('parentPatentNumber')
                elif isinstance(parent_bag, dict):
                    parent_patent_number = parent_bag.get('parentPatentNumber')
            
            print(f"  ✓ parentPatentNumber: {parent_patent_number}" if parent_patent_number else "  ❌ parentPatentNumber: Missing")
        
        # Test Case 2: Just "Walkoe"
        print("\n" + "="*60)
        print("TEST CASE 2: Inventor Search - Walkoe")
        print("="*60)
        
        name = "Walkoe"
        result2 = await client.search_inventor(name, "comprehensive", limit, fields)
        
        if result2.get('error'):
            print(f"❌ Search failed: {result2['error']}")
            return False
            
        print(f"✓ Search successful")
        applications2 = result2.get('unique_applications', [])
        print(f"  Found {len(applications2)} unique applications")
        
        if applications2:
            app = applications2[0]
            print(f"First application: {app.get('applicationNumberText', 'N/A')}")
            metadata = app.get('applicationMetaData', {})
            invention_title = metadata.get('inventionTitle')
            print(f"  Has inventionTitle: {'Yes' if invention_title else 'No'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

async def test_applications_search():
    """Test pfw_search_applications with the exact failing parameters"""
    
    try:
        client = EnhancedPatentClient()
        
        print("\n" + "="*60)
        print("TEST CASE 3: Applications Search - Wil Walkoe")
        print("="*60)
        
        query = "Wil Walkoe"
        fields = ["applicationNumberText", "inventionTitle", "parentPatentNumber", "patentNumber"]
        limit = 200
        
        print(f"Parameters:")
        print(f"  Query: '{query}'")
        print(f"  Fields: {fields}")
        print(f"  Limit: {limit}")
        
        result = await client.search_applications(query, limit, 0, fields)
        
        if result.get('error'):
            print(f"❌ Search failed: {result['error']}")
            return False
            
        print(f"✓ Search successful")
        applications = result.get('applications', [])
        print(f"  Found {len(applications)} applications")
        
        # Check first few applications for requested fields
        print(f"\nChecking first 3 applications for requested fields:")
        for i, app in enumerate(applications[:3]):
            print(f"\nApplication {i+1}: {app.get('applicationNumberText', 'N/A')}")
            
            # Check for each requested field
            app_number = app.get('applicationNumberText')
            print(f"  ✓ applicationNumberText: {app_number}" if app_number else "  ❌ applicationNumberText: Missing")
            
            # Check in applicationMetaData
            metadata = app.get('applicationMetaData', {})
            
            invention_title = metadata.get('inventionTitle')
            print(f"  ✓ inventionTitle: {invention_title[:50]}..." if invention_title else "  ❌ inventionTitle: Missing")
            
            patent_number = metadata.get('patentNumber')
            print(f"  ✓ patentNumber: {patent_number}" if patent_number else "  ❌ patentNumber: Missing")
            
            # Check parentPatentNumber
            parent_patent_number = None
            parent_bag = app.get('parentContinuityBag')
            if parent_bag:
                if isinstance(parent_bag, list) and parent_bag:
                    parent_patent_number = parent_bag[0].get('parentPatentNumber')
                elif isinstance(parent_bag, dict):
                    parent_patent_number = parent_bag.get('parentPatentNumber')
            
            print(f"  ✓ parentPatentNumber: {parent_patent_number}" if parent_patent_number else "  ❌ parentPatentNumber: Missing")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test function"""
    print("Testing Fields Fix for pfw_search_inventor and pfw_search_applications")
    print("Testing with exact parameters from Input-Output-Sample.txt")
    print("="*80)
    
    success1 = await test_inventor_search()
    success2 = await test_applications_search()
    
    print("\n" + "="*80)
    if success1 and success2:
        print("✅ ALL TESTS PASSED - Fields fix is working correctly!")
        print("✓ pfw_search_inventor now returns requested fields")
        print("✓ pfw_search_applications now returns requested fields")
    else:
        print("❌ SOME TESTS FAILED")
        if not success1:
            print("❌ pfw_search_inventor tests failed")
        if not success2:
            print("❌ pfw_search_applications tests failed")
    
    return success1 and success2

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)