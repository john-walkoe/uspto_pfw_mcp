import httpx
import logging
import json

logger = logging.getLogger('logging_transport')

# Define custom transport that logs all requests and responses
class LoggingTransport(httpx.AsyncBaseTransport):

    def __init__(self, transport):
        self.transport = transport

    async def handle_async_request(self, request):
        # Log the request
        logger.debug(f"REQUEST: {request.method} {request.url}")
        
        # Sanitize headers to prevent API key exposure
        headers_copy = dict(request.headers)
        headers_copy.pop('X-API-KEY', None)
        headers_copy.pop('Authorization', None)
        headers_copy.pop('x-api-key', None)  # Case insensitive backup
        headers_copy.pop('authorization', None)  # Case insensitive backup
        logger.debug(f"REQUEST HEADERS: {headers_copy}")
        
        try:
            # For body logging, convert to string if possible
            if request.content:
                body = request.content
                try:
                    if isinstance(body, bytes):
                        body = body.decode('utf-8')
                    # Try to parse and pretty-print JSON
                    try:
                        json_body = json.loads(body)
                        logger.debug(f"REQUEST BODY: \n{json.dumps(json_body, indent=2)}")
                    except:
                        logger.debug(f"REQUEST BODY: {body}")
                except:
                    logger.debug(f"REQUEST BODY: {body}")
        except Exception as e:
            logger.debug(f"Error logging request body: {e}")

        # Get the response
        response = await self.transport.handle_async_request(request)
        
        # Log the response
        logger.debug(f"RESPONSE: {response.status_code} from {request.url}")
        
        # Sanitize response headers as well (in case API returns sensitive data)
        response_headers_copy = dict(response.headers)
        response_headers_copy.pop('X-API-KEY', None)
        response_headers_copy.pop('Authorization', None)
        response_headers_copy.pop('x-api-key', None)
        response_headers_copy.pop('authorization', None)
        logger.debug(f"RESPONSE HEADERS: {response_headers_copy}")
        
        return response