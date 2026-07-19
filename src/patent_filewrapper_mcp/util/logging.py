import httpx
import logging

logger = logging.getLogger('logging_transport')

# Custom transport that logs request/response FLOW metadata only.
# Content-minimization posture: no request bodies (they carry user search
# queries — client work-product), no headers, no URL query strings.
class LoggingTransport(httpx.AsyncBaseTransport):

    def __init__(self, transport):
        self.transport = transport

    async def handle_async_request(self, request):
        # Method + path only — the query string can embed search terms
        logger.debug(f"REQUEST: {request.method} {request.url.scheme}://{request.url.host}{request.url.path}")
        if request.content:
            logger.debug(f"REQUEST BODY: {len(request.content)} bytes (content not logged)")

        response = await self.transport.handle_async_request(request)

        logger.debug(
            f"RESPONSE: {response.status_code} from {request.url.host}{request.url.path}"
        )

        return response
