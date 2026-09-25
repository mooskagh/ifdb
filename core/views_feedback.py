import json
import logging
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)


def _is_allowed_origin(origin: str, request: HttpRequest) -> bool:
    if not origin:
        return False
    parsed = urlparse(origin)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    base_domain = getattr(settings, "PLAYABLE_BASE_DOMAIN", "").strip().lower()
    if base_domain and (
        hostname == base_domain or hostname.endswith(f".{base_domain}")
    ):
        return True

    req_host = request.get_host().split(":")[0].lower()
    if hostname == req_host:
        return True

    trusted_origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
    for trusted in trusted_origins:
        parsed_trusted = urlparse(trusted)
        if (parsed_trusted.hostname or "").lower() == hostname:
            return True

    if settings.DEBUG and hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True

    return False


def _set_cors_headers(
    request: HttpRequest, response: HttpResponse
) -> HttpResponse:
    origin = request.META.get("HTTP_ORIGIN")
    if origin and _is_allowed_origin(origin, request):
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Credentials"] = "true"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
    return response


@csrf_exempt
def feedback_view(request: HttpRequest) -> HttpResponse:
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        return _set_cors_headers(request, response)

    origin = request.META.get("HTTP_ORIGIN")
    if origin and not _is_allowed_origin(origin, request):
        response = JsonResponse({"error": "Forbidden"}, status=403)
        return _set_cors_headers(request, response)

    if request.method == "GET":
        if request.user.is_authenticated:
            user = request.user
            data = {
                "authenticated": True,
                "user": {
                    "username": getattr(user, "username", "") or "",
                    "email": getattr(user, "email", "") or "",
                },
            }
        else:
            login_url = request.build_absolute_uri(reverse("login"))
            data = {
                "authenticated": False,
                "login_url": login_url,
            }
        response = JsonResponse(data)
        return _set_cors_headers(request, response)

    if request.method != "POST":
        response = JsonResponse({"error": "Method not allowed"}, status=405)
        return _set_cors_headers(request, response)

    if not request.user.is_authenticated:
        response = JsonResponse(
            {"error": "Authentication required"}, status=401
        )
        return _set_cors_headers(request, response)

    payload: dict[str, Any] = {}
    if request.body:
        try:
            parsed_json = json.loads(request.body)
            if isinstance(parsed_json, dict):
                payload = parsed_json
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if not payload and request.POST:
        payload = dict(request.POST.items())

    text = str(payload.get("text", "")).strip()
    if not text:
        response = JsonResponse(
            {"error": "Message text is required"}, status=400
        )
        return _set_cors_headers(request, response)

    url = str(payload.get("url", "")).strip()
    if not url:
        url = request.build_absolute_uri()

    clean_url = "".join(ch for ch in url if ch not in "\r\n").strip()

    player_name = str(payload.get("player_name", "")).strip()
    player_url = str(payload.get("player_url", "")).strip()
    game_name = str(payload.get("game_name", "")).strip()
    game_url = str(payload.get("game_url", "")).strip()
    user_agent = request.META.get("HTTP_USER_AGENT", "").strip()

    user = request.user
    user_email = getattr(user, "email", "")
    username = getattr(user, "username", "") or user_email

    context = {
        "text": text,
        "url": clean_url,
        "username": username,
        "email": user_email,
        "player_name": player_name,
        "player_url": player_url,
        "game_name": game_name,
        "game_url": game_url,
        "user_agent": user_agent,
    }

    subject_raw = render_to_string(
        "core/email/feedback_subject.txt", context
    ).strip()
    subject = "".join(ch for ch in subject_raw if ch not in "\r\n")

    body = render_to_string("core/email/feedback_body.txt", context)

    bcc_recipients: list[str] = []
    curation_email = getattr(settings, "CURATION_NOTIFICATION_EMAIL", None)
    if curation_email:
        bcc_recipients.append(curation_email)
    else:
        for admin in getattr(settings, "ADMINS", []):
            if isinstance(admin, (tuple, list)) and len(admin) >= 2:
                bcc_recipients.append(str(admin[1]))
            elif isinstance(admin, str):
                bcc_recipients.append(admin)

    try:
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user_email],
            bcc=bcc_recipients,
            reply_to=[user_email],
        )
        email.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send feedback email")
        response = JsonResponse({"error": "Failed to send email"}, status=500)
        return _set_cors_headers(request, response)

    response = JsonResponse({"status": "ok"})
    return _set_cors_headers(request, response)
