"""Domain exceptions + fail-closed error semantics.

Every error maps to an HTTP status and a machine-readable `code` so clients can
branch on failure type. The guiding rule is fail-closed: when the system cannot
safely serve a request (no provider, budget exhausted, breaker open), it refuses
rather than fabricating a response.
"""
from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "", *, detail: dict | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)
        self.message = message or self.code
        self.detail = detail or {}

    def to_payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class ScopeError(ForbiddenError):
    code = "insufficient_scope"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


class BudgetExhaustedError(AppError):
    """Fail-closed: tenant token budget spent — refuse rather than bill more."""

    status_code = 402
    code = "budget_exhausted"


class NoProviderAvailableError(AppError):
    """Fail-closed: no healthy provider can serve the request (strict mode)."""

    status_code = 503
    code = "no_provider_available"


class CircuitOpenError(AppError):
    status_code = 503
    code = "circuit_open"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
