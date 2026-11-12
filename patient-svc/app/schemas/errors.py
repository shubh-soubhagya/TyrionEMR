"""Error envelope model, used only to document error responses in OpenAPI."""
from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]]
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
