from collections.abc import Callable
from functools import wraps
from typing import Any, overload
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse

__all__ = [
    "cors_playable",
    "is_allowed_playable_origin",
    "playable_cors",
    "set_cors_headers",
]


def is_allowed_playable_origin(origin: str | None) -> bool:
    if not origin:
        return False

    base_domain = getattr(settings, "PLAYABLE_BASE_DOMAIN", "").strip().lower()
    parsed = urlparse(origin)
    hostname = (parsed.hostname or "").lower()

    if base_domain and (
        hostname == base_domain or hostname.endswith(f".{base_domain}")
    ):
        return True
    if settings.DEBUG and hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True

    return False


def set_cors_headers(
    request: HttpRequest,
    response: HttpResponse,
    *,
    methods: str = "POST, OPTIONS",
) -> HttpResponse:
    origin = request.META.get("HTTP_ORIGIN")
    if not origin or not is_allowed_playable_origin(origin):
        return response

    response["Access-Control-Allow-Origin"] = origin
    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = methods
    response["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@overload
def cors_playable(
    view_func: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]: ...


@overload
def cors_playable(
    view_func: None = None,
    *,
    methods: str = "GET",
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]: ...


def cors_playable(
    view_func: Callable[..., HttpResponse] | None = None,
    *,
    methods: str = "GET",
) -> (
    Callable[..., HttpResponse]
    | Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]
):
    def decorator(
        fn: Callable[..., HttpResponse],
    ) -> Callable[..., HttpResponse]:
        @wraps(fn)
        def wrapper(
            request: HttpRequest, *args: Any, **kwargs: Any
        ) -> HttpResponse:
            response = fn(request, *args, **kwargs)
            return set_cors_headers(request, response, methods=methods)

        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator


playable_cors = cors_playable
