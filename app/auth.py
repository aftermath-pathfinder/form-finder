"""Optional password protection for when the app is hosted somewhere others can reach it.

Set APP_PASSWORD in `.env` and every page and API call asks for it (browser login prompt;
any username). Leave it empty when running only on your own computer.
"""

import base64
import binascii
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp


class PasswordMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, password: str) -> None:
        if not password:
            # An empty password would let anyone in; callers skip the middleware instead.
            raise ValueError("PasswordMiddleware needs a non-empty password.")
        super().__init__(app)
        self.password = password.encode()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._authorized(request.headers.get("authorization", "")):
            return await call_next(request)
        return PlainTextResponse(
            "Password required.", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Form Finder"'}
        )

    def _authorized(self, header: str) -> bool:
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic" or not encoded:
            return False
        try:
            _, _, given = base64.b64decode(encoded).partition(b":")
        except (binascii.Error, ValueError):
            return False
        return secrets.compare_digest(given, self.password)
