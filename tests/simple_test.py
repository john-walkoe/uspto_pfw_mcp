import asyncio
from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
import os

# Set a dummy API key for testing
os.environ['USPTO_API_KEY'] = os.getenv('TEST_USPTO_API_KEY', 'test_fallback_key')

async def test():
    try:
        client = EnhancedPatentClient()
        print('Client initialized')
        
        # Test with documentBag field
        result = await client.search_applications(
            'applicationNumberText:11752072', 
            1, 0, 
            ['applicationNumberText', 'documentBag']
        )
        
        print(f'Result keys: {list(result.keys())}')
        print(f'Applications count: {len(result.get("applications", []))}')
        
        apps = result.get('applications', [])
        if apps:
            print(f'First app keys: {list(apps[0].keys())}')
            print(f'documentBag in first app: {"documentBag" in apps[0]}')
            
            # Check if documentBag field exists
            if 'documentBag' in apps[0]:
                print(f'documentBag content: {apps[0]["documentBag"]}')
            else:
                print('documentBag field not found in response')
                
        return result
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test())