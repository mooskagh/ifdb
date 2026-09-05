from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from ifdb.permissioner import Permissioner

from .models import APIToken


def get_token_from_request(request: HttpRequest) -> str | None:
    auth_header = request.META.get("HTTP_AUTHORIZATION", "").strip()
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() in {"bearer", "token"}:
        return str(parts[1])
    return None


def api_auth(
    perm: str | None = None,
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    def decorator(
        view_func: Callable[..., HttpResponse],
    ) -> Callable[..., HttpResponse]:
        @wraps(view_func)
        def wrapped_view(
            request: HttpRequest, *args: Any, **kwargs: Any
        ) -> HttpResponse:
            token_key = get_token_from_request(request)
            if not token_key:
                return JsonResponse(
                    {
                        "error": "Unauthorized",
                        "detail": "Missing Authorization header",
                    },
                    status=401,
                )

            token = (
                APIToken.objects
                .select_related("user")
                .filter(key=token_key, is_active=True)
                .first()
            )
            if token is None:
                return JsonResponse(
                    {
                        "error": "Unauthorized",
                        "detail": "Invalid or inactive token",
                    },
                    status=401,
                )

            APIToken.objects.filter(pk=token.pk).update(
                last_used_at=timezone.now()
            )

            if perm and not token.has_perm(perm):
                return JsonResponse(
                    {
                        "error": "Forbidden",
                        "detail": f"Token lacks required scope '{perm}'",
                    },
                    status=403,
                )

            request.user = token.user
            setattr(request, "api_token", token)
            setattr(request, "perm", Permissioner(request))

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator
