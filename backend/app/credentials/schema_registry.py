"""CredentialSchemaRegistry — maps credential type → Pydantic schema for validation."""
from __future__ import annotations

from typing import Any, Dict, Type

from pydantic import BaseModel

from .registry import CREDENTIAL_TYPES  # existing

# Import generic schemas - we define lightweight schemas for new generic types
from pydantic import Field


class BasicAuthSchema(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(default="")


class BearerAuthSchema(BaseModel):
    token: str = Field(min_length=1)


class HeaderAuthSchema(BaseModel):
    header_name: str = Field(min_length=1, default="X-API-Key")
    header_value: str = Field(min_length=1)


class QueryAuthSchema(BaseModel):
    query_name: str = Field(min_length=1, default="api_key")
    query_value: str = Field(min_length=1)


class DigestAuthSchema(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    realm: str = Field(default="")
    nonce: str = Field(default="")


class CustomAuthSchema(BaseModel):
    headers: Dict[str, str] = Field(default_factory=dict)
    query: Dict[str, str] = Field(default_factory=dict)
    body: Dict[str, Any] = Field(default_factory=dict)


class OAuth2GenericSchema(BaseModel):
    client_id: str = Field(default="")
    client_secret: str = Field(default="")
    access_token: str = Field(default="")
    refresh_token: str = Field(default="")
    token_url: str = Field(default="")
    authorization_url: str = Field(default="")
    scopes: str = Field(default="")
    expires_at: float = Field(default=0)


class OAuth1GenericSchema(BaseModel):
    consumer_key: str = Field(min_length=1)
    consumer_secret: str = Field(min_length=1)
    token: str = Field(min_length=1)
    token_secret: str = Field(min_length=1)
    signature_method: str = Field(default="HMAC-SHA1")


_GENERIC_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "basic_auth": BasicAuthSchema,
    "bearer_auth": BearerAuthSchema,
    "header_auth": HeaderAuthSchema,
    "query_auth": QueryAuthSchema,
    "digest_auth": DigestAuthSchema,
    "custom_auth": CustomAuthSchema,
    "oauth2": OAuth2GenericSchema,
    "oauth1": OAuth1GenericSchema,
}


class CredentialSchemaRegistry:
    def __init__(self) -> None:
        self._schemas: Dict[str, Type[BaseModel]] = {}
        # Seed from existing CREDENTIAL_TYPES
        for type_id, schema in CREDENTIAL_TYPES.items():
            self._schemas[type_id] = schema
        # Add generic
        for type_id, schema in _GENERIC_SCHEMAS.items():
            self._schemas[type_id] = schema

    def get(self, type_id: str) -> Type[BaseModel] | None:
        return self._schemas.get(type_id)

    def validate(self, type_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        schema = self.get(type_id)
        if schema is None:
            raise ValueError(f"Unknown credential type '{type_id}'.")
        return schema.model_validate(data).model_dump(mode="json")

    def list(self) -> Dict[str, Type[BaseModel]]:
        return dict(self._schemas)


_schema_registry = CredentialSchemaRegistry()


def get_schema_registry() -> CredentialSchemaRegistry:
    return _schema_registry
