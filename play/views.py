import json
import uuid
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core.models import User
from games.models import Game, GameAuthor

from .models import Playable, PlaySegment, PlaySession

INACTIVITY_THRESHOLD_SECONDS = 300


def _get_ip_addr(request: HttpRequest) -> str | None:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if isinstance(x_forwarded_for, str):
        ip = x_forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    remote_addr = request.META.get("REMOTE_ADDR")
    if isinstance(remote_addr, str):
        addr = remote_addr.strip()
        if addr:
            return addr
    return None


def _set_cors_headers(
    request: HttpRequest, response: HttpResponse
) -> HttpResponse:
    origin = request.META.get("HTTP_ORIGIN")
    if not origin:
        return response

    base_domain = getattr(settings, "PLAYABLE_BASE_DOMAIN", "").strip().lower()
    parsed = urlparse(origin)
    hostname = (parsed.hostname or "").lower()

    allowed = False
    if base_domain and (
        hostname == base_domain or hostname.endswith(f".{base_domain}")
    ):
        allowed = True
    elif settings.DEBUG and hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        allowed = True

    if allowed:
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Credentials"] = "true"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"

    return response


def _parse_payload(request: HttpRequest) -> dict[str, Any]:
    if request.body:
        try:
            data = json.loads(request.body)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if request.POST:
        return dict(request.POST.items())
    return {}


@csrf_exempt
def telemetry(request: HttpRequest) -> HttpResponse:
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        return _set_cors_headers(request, response)

    if request.method != "POST":
        response = JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )
        return _set_cors_headers(request, response)

    data = _parse_payload(request)
    event = data.get("event")
    if not event:
        response = JsonResponse(
            {"error": "Missing event parameter"}, status=400
        )
        return _set_cors_headers(request, response)

    if event == "game_loaded":
        return _set_cors_headers(request, _handle_game_loaded(request, data))
    elif event == "ping":
        return _set_cors_headers(request, _handle_ping(request, data))
    else:
        response = JsonResponse(
            {"error": f"Unknown event: {event}"}, status=400
        )
        return _set_cors_headers(request, response)


def _find_playable(playable_id_raw: Any) -> Playable | None:
    if not playable_id_raw:
        return None

    if isinstance(playable_id_raw, int) or (
        isinstance(playable_id_raw, str) and playable_id_raw.isdigit()
    ):
        playable = Playable.objects.filter(pk=int(playable_id_raw)).first()
        if playable:
            return playable

    if not isinstance(playable_id_raw, str):
        return None

    raw_val = playable_id_raw.strip()
    if not raw_val:
        return None

    # Direct slug match
    playable = Playable.objects.filter(slug=raw_val).first()
    if playable:
        return playable

    # Parse as URL with all parts optional, using server name / hostname
    url_candidate = raw_val
    if "://" not in url_candidate and not url_candidate.startswith("//"):
        url_candidate = f"//{url_candidate}"

    parsed = urlparse(url_candidate)
    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        return None

    # Full hostname match
    playable = Playable.objects.filter(slug=hostname).first()
    if playable:
        return playable

    # Subdomain before .<PLAYABLE_BASE_DOMAIN>
    base_domain = getattr(settings, "PLAYABLE_BASE_DOMAIN", "").strip().lower()
    if base_domain and hostname.endswith(f".{base_domain}"):
        subdomain = hostname[: -len(base_domain) - 1]
        if subdomain:
            playable = Playable.objects.filter(slug=subdomain).first()
            if playable:
                return playable

    # First subdomain component (e.g. slug in slug.localhost)
    first_part = hostname.split(".")[0]
    if first_part and first_part != hostname:
        playable = Playable.objects.filter(slug=first_part).first()
        if playable:
            return playable

    return None


def _get_game_authors(game: Game) -> str:
    authors = list(
        GameAuthor.objects
        .filter(game=game, role__symbolic_id="author")
        .select_related("author")
        .order_by("id")
    )
    if not authors:
        authors = list(
            GameAuthor.objects
            .filter(game=game)
            .select_related("author")
            .order_by("id")
        )
    names: list[str] = []
    for a in authors:
        if a.author and a.author.name and a.author.name not in names:
            names.append(a.author.name)
    return ", ".join(names)


def _handle_game_loaded(
    request: HttpRequest, data: dict[str, Any]
) -> HttpResponse:
    session_id_raw = data.get("play_session_id")
    if not session_id_raw:
        return JsonResponse(
            {"error": "Missing play_session_id parameter"}, status=400
        )
    try:
        session_uuid = uuid.UUID(str(session_id_raw))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid play_session_id"}, status=400)

    playable_id_raw = data.get("playable_id")
    if not playable_id_raw:
        return JsonResponse(
            {"error": "Missing playable_id parameter"}, status=400
        )

    playable = _find_playable(playable_id_raw)
    if not playable:
        return JsonResponse({"error": "Playable not found"}, status=404)

    state_raw = str(data.get("state", PlaySegment.State.ACTIVE)).lower()
    state = (
        state_raw
        if state_raw in PlaySegment.State.values
        else PlaySegment.State.ACTIVE
    )

    now = timezone.now()
    user = request.user if isinstance(request.user, User) else None
    session_key = request.session.session_key if request.session else None
    ip_addr = _get_ip_addr(request)

    with transaction.atomic():
        session, created = PlaySession.objects.get_or_create(
            play_session_id=session_uuid,
            defaults={
                "playable": playable,
                "started_at": now,
                "last_seen_at": now,
            },
        )
        if not created:
            session.last_seen_at = now
            session.save(update_fields=["last_seen_at"])

        existing_segment = (
            PlaySegment.objects
            .filter(play_session=session)
            .order_by("-started_at", "-id")
            .first()
        )
        if not existing_segment:
            PlaySegment.objects.create(
                play_session=session,
                user=user,
                django_session_key=session_key,
                ip_addr=ip_addr,
                state=state,
                started_at=now,
                last_seen_at=now,
                active_seconds=0,
            )

    game_authors = _get_game_authors(playable.game)
    game_page_url = request.build_absolute_uri(
        reverse("show_game", args=[playable.game.pk])
    )

    return JsonResponse({
        "status": "ok",
        "play_session_id": str(session.play_session_id),
        "playable_id": playable.pk,
        "game_name": playable.game.title,
        "authors": game_authors,
        "game_url": game_page_url,
        "player_name": playable.player_name,
        "player_url": playable.player_url,
    })


def _handle_ping(request: HttpRequest, data: dict[str, Any]) -> HttpResponse:
    session_id_raw = data.get("play_session_id")
    if not session_id_raw:
        return JsonResponse(
            {"error": "Missing play_session_id parameter"}, status=400
        )
    try:
        session_uuid = uuid.UUID(str(session_id_raw))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid play_session_id"}, status=400)

    session = PlaySession.objects.filter(play_session_id=session_uuid).first()
    if not session:
        return JsonResponse({"error": "Play session not found"}, status=404)

    state_raw = data.get("state")
    if not state_raw or str(state_raw).lower() not in PlaySegment.State.values:
        valid_states = ", ".join(PlaySegment.State.values)
        return JsonResponse(
            {"error": f"Invalid state. Must be one of: {valid_states}"},
            status=400,
        )
    current_state = str(state_raw).lower()

    raw_seconds = data.get("seconds_since_last_ping")
    if raw_seconds is None:
        raw_seconds = data.get("elapsed_seconds")
    if raw_seconds is None:
        return JsonResponse(
            {"error": "Missing seconds_since_last_ping parameter"}, status=400
        )

    try:
        seconds_since_last_ping = int(raw_seconds)
        if seconds_since_last_ping < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return JsonResponse(
            {"error": "seconds_since_last_ping must be an int >= 0"},
            status=400,
        )

    now = timezone.now()
    current_user = request.user if isinstance(request.user, User) else None
    current_session_key = (
        request.session.session_key if request.session else None
    )
    current_ip = _get_ip_addr(request)

    with transaction.atomic():
        last_segment = (
            PlaySegment.objects
            .filter(play_session=session)
            .order_by("-started_at", "-id")
            .first()
        )

        if not last_segment:
            PlaySegment.objects.create(
                play_session=session,
                user=current_user,
                django_session_key=current_session_key,
                ip_addr=current_ip,
                state=current_state,
                started_at=now,
                last_seen_at=now,
                active_seconds=(
                    seconds_since_last_ping
                    if current_state == PlaySegment.State.ACTIVE
                    else 0
                ),
            )
        else:
            gap_seconds = (now - last_segment.last_seen_at).total_seconds()
            last_user_pk = last_segment.user.pk if last_segment.user else None
            current_user_pk = current_user.pk if current_user else None
            params_match = (
                last_segment.state == current_state
                and last_user_pk == current_user_pk
                and last_segment.django_session_key == current_session_key
                and last_segment.ip_addr == current_ip
            )

            if params_match and gap_seconds <= INACTIVITY_THRESHOLD_SECONDS:
                if last_segment.state == PlaySegment.State.ACTIVE:
                    last_segment.active_seconds += seconds_since_last_ping
                last_segment.last_seen_at = now
                last_segment.save(
                    update_fields=["last_seen_at", "active_seconds"]
                )
            elif gap_seconds <= INACTIVITY_THRESHOLD_SECONDS:
                # Params changed: attribute elapsed time to prior segment
                if last_segment.state == PlaySegment.State.ACTIVE:
                    last_segment.active_seconds += seconds_since_last_ping
                last_segment.last_seen_at = now
                last_segment.save(
                    update_fields=["last_seen_at", "active_seconds"]
                )

                # Create new segment with 0 active seconds for new state
                PlaySegment.objects.create(
                    play_session=session,
                    user=current_user,
                    django_session_key=current_session_key,
                    ip_addr=current_ip,
                    state=current_state,
                    started_at=now,
                    last_seen_at=now,
                    active_seconds=0,
                )
            else:
                # Inactivity gap exceeded: prior segment ended in the past
                PlaySegment.objects.create(
                    play_session=session,
                    user=current_user,
                    django_session_key=current_session_key,
                    ip_addr=current_ip,
                    state=current_state,
                    started_at=now,
                    last_seen_at=now,
                    active_seconds=(
                        seconds_since_last_ping
                        if current_state == PlaySegment.State.ACTIVE
                        else 0
                    ),
                )

        session.last_seen_at = now
        session.save(update_fields=["last_seen_at"])

    return JsonResponse({"status": "ok"})
