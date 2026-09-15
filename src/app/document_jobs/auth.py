"""Cognito access-token verification: issuer, signature, expiry, client and token use."""

from typing import Any

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.document_jobs.contracts import JobError


class AccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sub: str = Field(min_length=1)
    token_use: str
    client_id: str
    exp: int
    iss: str


class CognitoAuth:
    def __init__(self, region: str, pool_id: str, client_id: str) -> None:
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
        self.client_id = client_id
        self.keys = PyJWKClient(
            self.issuer + "/.well-known/jwks.json", timeout=5, cache_jwk_set=True, lifespan=300
        )

    def verify(self, token: str) -> str:
        if len(token) > 16384:
            raise JobError("UNAUTHORIZED", 401)
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            payload: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={
                    "verify_aud": False,
                    "require": ["exp", "iat", "iss", "sub", "token_use", "client_id"],
                },
            )
            claims = AccessClaims.model_validate(payload)
            if claims.token_use != "access" or claims.client_id != self.client_id:
                raise JobError("UNAUTHORIZED", 401)
            return claims.sub
        except (jwt.PyJWTError, ValidationError, OSError):
            raise JobError("UNAUTHORIZED", 401) from None
