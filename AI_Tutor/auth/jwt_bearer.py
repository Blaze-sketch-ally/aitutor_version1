import os
from functools import lru_cache

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
# Only required if this project actually uses the legacy HS256 shared
# secret (see _decode() below) — projects on the newer asymmetric
# signing keys never need this, so it's not a hard startup requirement
# the way SUPABASE_URL is.
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

if not SUPABASE_URL:

    raise ValueError(
        "SUPABASE_URL not found in .env"
    )

# auto_error=False so a missing Authorization header falls through to our
# own check below and returns 401 — HTTPBearer's default (auto_error=True)
# would raise 403 for a missing header, which would be inconsistent with
# every other rejection reason (expired/invalid/malformed token) below,
# all of which are 401.
security = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """
    The authenticated identity, derived entirely from a verified Supabase
    JWT — never from anything the client sends in a request body/query
    param. `id` is the Supabase Auth user UUID (`sub` claim) and is the
    only user identifier the rest of the backend should trust.
    """

    id: str
    email: str | None = None


@lru_cache
def _jwks_client() -> "jwt.PyJWKClient":
    """
    Built once per process and reused — PyJWKClient itself caches the
    fetched public keys internally too, so after the first token this
    costs no network round trip, only an in-memory lookup.
    """

    return jwt.PyJWKClient(
        f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    )


def _decode(token: str) -> dict:
    """
    Supabase projects sign auth JWTs one of two ways depending on when/
    how the project was set up:
      - legacy: a single shared HS256 secret (SUPABASE_JWT_SECRET)
      - newer: rotatable asymmetric keys (ES256/RS256), verified against
        a public JWKS endpoint instead of a shared secret

    Rather than hardcoding one and guessing wrong, this reads the `alg`
    the token itself declares (from its unverified header — this does
    NOT trust the header's claims, only which verification path to use)
    and verifies accordingly. Works correctly regardless of which mode
    a given Supabase project is actually in.
    """

    alg = jwt.get_unverified_header(token).get("alg")

    if alg == "HS256":

        if not SUPABASE_JWT_SECRET:

            raise HTTPException(
                status_code=500,
                detail=(
                    "This Supabase project signs tokens with HS256 but "
                    "SUPABASE_JWT_SECRET is not configured."
                )
            )

        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )

    signing_key = _jwks_client().get_signing_key_from_jwt(token)

    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[alg],
        audience="authenticated"
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> CurrentUser:
    """
    Reusable FastAPI dependency: extracts the Bearer token, verifies its
    signature/expiry/audience (see _decode() for how the signing mode is
    resolved), and returns the authenticated user. Raises 401 for
    anything short of a valid, unexpired, correctly-signed token —
    missing header, malformed token, bad signature, and expired token
    are all indistinguishable to the caller (401), so this never
    confirms/denies whether a token merely expired vs. was never valid.

    Usage: `current_user: CurrentUser = Depends(get_current_user)` in any
    route that needs the caller's identity — this is the only place JWT
    verification happens; no route should duplicate this logic.
    """

    if credentials is None:

        raise HTTPException(
            status_code=401,
            detail="Not authenticated"
        )

    try:

        payload = _decode(credentials.credentials)

    except HTTPException:

        raise

    except jwt.PyJWTError:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    user_id = payload.get("sub")

    if not user_id:

        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

    return CurrentUser(
        id=user_id,
        email=payload.get("email")
    )
