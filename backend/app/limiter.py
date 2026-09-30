from app.config import get_settings
from slowapi import Limiter
from slowapi.util import get_remote_address

settings = get_settings()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300/hour"],
    storage_uri=settings.rate_limit_storage_uri,
)
