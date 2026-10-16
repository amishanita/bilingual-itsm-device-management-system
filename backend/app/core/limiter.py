"""Rate limiting with slowapi.

The client IP comes from request.client, which Uvicorn only rewrites from
X-Forwarded-For when the request arrives from FORWARDED_ALLOW_IPS. A client
talking to the API directly therefore cannot fake its IP to dodge the limit.

Limits are stored in process memory. That is correct for the single Uvicorn
process this project runs; several processes would each count separately.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

LOGIN_LIMIT = "5/minute"
CHAT_LIMIT = "20/hour"


def user_or_ip_key(request: Request) -> str:
    """Rate-limit key for signed-in endpoints: the user id from a valid token.

    Counting per user (not per IP) means people behind one office NAT do not
    share a single chat allowance. Requests without a valid token fall back to
    the IP; they are refused by authentication anyway.
    """
    from app.core.config import get_settings
    from app.core.security import TokenError, decode_access_token

    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            return f"user:{decode_access_token(token, get_settings())}"
        except TokenError:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=get_remote_address)
