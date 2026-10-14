"""Rate limiting with slowapi.

The client IP comes from request.client, which Uvicorn only rewrites from
X-Forwarded-For when the request arrives from FORWARDED_ALLOW_IPS. A client
talking to the API directly therefore cannot fake its IP to dodge the limit.

Limits are stored in process memory. That is correct for the single Uvicorn
process this project runs; several processes would each count separately.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

LOGIN_LIMIT = "5/minute"

limiter = Limiter(key_func=get_remote_address)
