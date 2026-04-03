"""JWT authentication helpers for ForaGo backend."""

import os
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, ExpiredSignatureError, jwt


bearer_scheme = HTTPBearer(auto_error=False)
_JWKS_CACHE: Dict[str, Any] = {"url": None, "expires_at": 0.0, "keys": []}
_JWKS_CACHE_TTL_SECONDS = 300


@dataclass
class AuthUser:
    user_id: str
    claims: Dict[str, Any]


def _parse_algorithms(raw: str) -> List[str]:
    algorithms = [item.strip() for item in raw.split(",") if item.strip()]
    return algorithms or ["HS256"]


def _jwt_secret() -> str:
    # Support both new and legacy env naming.
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY", "")
    return secret


def _jwt_public_key() -> str:
    raw_key = os.getenv("JWT_PUBLIC_KEY", "").strip()
    if raw_key:
        # Keep escaped newlines usable for .env style values.
        return raw_key.replace("\\n", "\n")

    key_file = os.getenv("JWT_PUBLIC_KEY_FILE", "").strip()
    if key_file:
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _jwt_issuer() -> Optional[str]:
    configured = os.getenv("JWT_ISSUER")
    if configured:
        return configured

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if supabase_url:
        return f"{supabase_url}/auth/v1"
    return None


def _jwt_audience() -> Optional[str]:
    configured = os.getenv("JWT_AUDIENCE")
    if configured:
        return configured

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    if supabase_url:
        return os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    return None


def _jwt_algorithms() -> List[str]:
    return _parse_algorithms(os.getenv("JWT_ALGORITHMS", os.getenv("JWT_ALGORITHM", "HS256")))


def _jwt_jwks_url() -> str:
    configured = os.getenv("JWT_JWKS_URL", "").strip()
    if configured:
        return configured

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if supabase_url:
        return f"{supabase_url}/auth/v1/.well-known/jwks.json"
    return ""


def _uses_symmetric_signing(algorithms: List[str]) -> bool:
    return any(alg.upper().startswith("HS") for alg in algorithms)


def _verification_key(algorithms: List[str]) -> str:
    if _uses_symmetric_signing(algorithms):
        return _jwt_secret()
    return _jwt_public_key()


def _fetch_jwks(jwks_url: str) -> List[Dict[str, Any]]:
    now = time.time()
    if _JWKS_CACHE["url"] == jwks_url and _JWKS_CACHE["expires_at"] > now:
        return _JWKS_CACHE["keys"]

    with urllib.request.urlopen(jwks_url, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    keys = payload.get("keys", [])
    if not isinstance(keys, list):
        raise RuntimeError("Invalid JWKS payload: keys must be a list")

    _JWKS_CACHE["url"] = jwks_url
    _JWKS_CACHE["expires_at"] = now + _JWKS_CACHE_TTL_SECONDS
    _JWKS_CACHE["keys"] = keys
    return keys


def _pick_jwk_for_token(token: str, algorithms: List[str]) -> Dict[str, Any]:
    header = jwt.get_unverified_header(token)
    token_kid = header.get("kid")
    token_alg = header.get("alg")

    if token_alg and token_alg not in algorithms:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported token algorithm",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwks_url = _jwt_jwks_url()
    if not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT JWKS URL is not configured",
        )

    try:
        keys = _fetch_jwks(jwks_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch JWKS keys",
        ) from exc

    for key in keys:
        if token_kid and key.get("kid") != token_kid:
            continue
        if token_alg and key.get("alg") and key.get("alg") != token_alg:
            continue
        return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No matching signing key found for token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_auth_configuration(is_production: bool) -> None:
    algorithms = _jwt_algorithms()
    if is_production and not algorithms:
        raise RuntimeError("Production requires JWT_ALGORITHMS")

    key = _verification_key(algorithms)
    jwks_url = _jwt_jwks_url()
    if is_production and not key and not jwks_url:
        if _uses_symmetric_signing(algorithms):
            raise RuntimeError("Production requires JWT_SECRET_KEY for HS* algorithms")
        raise RuntimeError("Production requires JWT_PUBLIC_KEY/JWT_PUBLIC_KEY_FILE or JWT_JWKS_URL")


def _decode_token(token: str) -> Dict[str, Any]:
    algorithms = _jwt_algorithms()
    key = _verification_key(algorithms)
    if not key and not _uses_symmetric_signing(algorithms):
        key = _pick_jwk_for_token(token, algorithms)

    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT verification key is not configured",
        )

    kwargs: Dict[str, Any] = {
        "key": key,
        "algorithms": algorithms,
    }

    issuer = _jwt_issuer()
    audience = _jwt_audience()
    if issuer:
        kwargs["issuer"] = issuer
    if audience:
        kwargs["audience"] = audience

    try:
        return jwt.decode(token, **kwargs)
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _extract_user_id(claims: Dict[str, Any]) -> str:
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject (sub) is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject (sub) must be a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return sub


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AuthUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    claims = _decode_token(token)
    user_id = _extract_user_id(claims)
    return AuthUser(user_id=user_id, claims=claims)
