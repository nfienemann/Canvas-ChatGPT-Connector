"""Reserved boundary; no speculative upstream API, authentication or terms grant."""

from canvas_bridge.academic.gateway import denied
from canvas_bridge.domain import utcnow
from canvas_bridge.providers.base import AcademicProvider


class FutureApprovedMCPProvider(AcademicProvider):
    provider_id = "future-approved-mcp"
    api_version = "1.0.0"

    def __init__(self, *, clock=utcnow):
        super().__init__(clock=clock)

    def require(self, request, *, phase):
        denied()

    def verify_record(self, record, request):
        denied()

    async def retrieve(self, operation, request):
        denied()
