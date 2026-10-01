"""Request id for the HTTP call that is currently running."""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("energyflow_request_id", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()
