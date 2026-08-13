"""Typed errors exposed by the router API."""


class RouterError(Exception):
    """Base error with an HTTP-compatible status and stable error code."""

    status_code = 500
    code = "router_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_openai_error(self) -> dict:
        return {
            "error": {
                "message": self.message,
                "type": self.code,
                "param": None,
                "code": self.code,
                "details": self.details,
            }
        }


class ConfigurationError(RouterError):
    status_code = 500
    code = "configuration_error"


class InvalidRequestError(RouterError):
    status_code = 400
    code = "invalid_request_error"


class AuthenticationError(RouterError):
    status_code = 401
    code = "authentication_error"


class PolicyDeniedError(RouterError):
    status_code = 403
    code = "policy_denied"


class BudgetExceededError(RouterError):
    status_code = 422
    code = "budget_exceeded"


class NoEligibleModelError(RouterError):
    status_code = 422
    code = "no_eligible_model"


class ProviderError(RouterError):
    status_code = 502
    code = "provider_error"

