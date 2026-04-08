from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

security = HTTPBearer()


async def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    if credentials.credentials != settings.collector_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials
