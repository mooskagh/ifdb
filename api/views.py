import json
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

from games import gameinfo
from games.models import (
    URL,
    Game,
    GameRevision,
    GameURL,
    GameURLCategory,
)

from .auth import api_auth
from .openapi import get_openapi_spec


def _extract_canonical_text(
    request: HttpRequest,
) -> tuple[str, dict[str, Any]]:
    content_type = request.content_type or ""
    if "application/json" in content_type:
        try:
            data = json.loads(request.body)
            if not isinstance(data, dict):
                return "", {}
            return data.get("canonical_text", ""), data
        except json.JSONDecodeError:
            return "", {}
    return request.body.decode("utf-8", errors="replace"), {}


def _game_response_data(game: Game) -> dict[str, Any]:
    rev = (
        game.published_revision
        if game.state == Game.State.PUBLISHED and game.published_revision
        else GameRevision.objects.filter(game=game).order_by("-id").first()
    )
    canonical_text = rev.canonical_text if rev else ""

    return {
        "id": game.id,
        "title": game.title,
        "state": game.state.lower(),
        "revision_id": rev.id if rev else None,
        "canonical_text": canonical_text,
        "created_at": (
            game.creation_time.isoformat() if game.creation_time else None
        ),
        "updated_at": (game.edit_time.isoformat() if game.edit_time else None),
    }


@require_http_methods(["GET"])
def openapi_spec(request: HttpRequest) -> HttpResponse:
    return JsonResponse(get_openapi_spec())


@require_http_methods(["GET"])
def api_docs(request: HttpRequest) -> HttpResponse:
    html = """<!DOCTYPE html>
<html>
  <head>
    <title>IFDB API Documentation</title>
    <meta charset="utf-8"/>
    <style>body { margin: 0; padding: 0; }</style>
  </head>
  <body>
    <redoc spec-url="/api/openapi.json"></redoc>
    <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
  </body>
</html>"""
    return HttpResponse(html, content_type="text/html")


@csrf_exempt
@require_http_methods(["POST"])
@api_auth(perm="games:write")
def game_create(request: HttpRequest) -> HttpResponse:
    canonical_text, payload = _extract_canonical_text(request)
    if not canonical_text.strip():
        return JsonResponse(
            {"error": "Bad Request", "detail": "Missing canonical_text"},
            status=400,
        )

    requested_state = str(payload.get("state", "draft")).lower()
    if requested_state not in {"draft", "published"}:
        return JsonResponse(
            {
                "error": "Bad Request",
                "detail": "state must be 'draft' or 'published'",
            },
            status=400,
        )

    target_state = (
        Game.State.PUBLISHED
        if requested_state == "published"
        else Game.State.DRAFT
    )

    token = getattr(request, "api_token", None)
    if (
        target_state == Game.State.PUBLISHED
        and token
        and not token.has_perm("games:publish")
    ):
        return JsonResponse(
            {
                "error": "Forbidden",
                "detail": "Publishing requires 'games:publish' scope",
            },
            status=403,
        )

    try:
        info = gameinfo.parse(canonical_text)
    except Exception as exc:
        return JsonResponse(
            {
                "error": "Bad Request",
                "detail": f"Failed to parse canonical text: {exc}",
            },
            status=400,
        )

    now = timezone.now()
    with transaction.atomic():
        game, backfilled_text = info.save(None, state=target_state)
        game.added_by = request.user
        game.save(update_fields=["added_by"])

        is_pub = target_state == Game.State.PUBLISHED
        revision = GameRevision.objects.create(
            game=game,
            created_at=now,
            created_by=request.user,
            origin=GameRevision.Origin.API,
            status=(
                GameRevision.Status.ACCEPTED
                if is_pub
                else GameRevision.Status.PROPOSED
            ),
            published_at=now if is_pub else None,
            published_by=request.user if is_pub else None,
            previous_canonical_text="" if is_pub else None,
            canonical_text=backfilled_text,
        )

        if is_pub:
            game.published_revision = revision
            game.published_revision_id = revision.pk
            game.save(update_fields=["published_revision"])

    return JsonResponse(_game_response_data(game), status=201)


@csrf_exempt
@require_http_methods(["GET", "PUT", "PATCH"])
def game_detail_router(request: HttpRequest, game_id: int) -> HttpResponse:
    if request.method == "GET":
        return _game_get(request, game_id)
    return _game_update(request, game_id)


@api_auth(perm="games:read")
def _game_get(request: HttpRequest, game_id: int) -> HttpResponse:
    try:
        game = Game.objects.select_related("published_revision").get(
            pk=game_id
        )
    except Game.DoesNotExist:
        return JsonResponse(
            {"error": "Not Found", "detail": f"Game {game_id} does not exist"},
            status=404,
        )
    return JsonResponse(_game_response_data(game))


@api_auth(perm="games:write")
def _game_update(request: HttpRequest, game_id: int) -> HttpResponse:
    try:
        game = Game.objects.select_related("published_revision").get(
            pk=game_id
        )
    except Game.DoesNotExist:
        return JsonResponse(
            {"error": "Not Found", "detail": f"Game {game_id} does not exist"},
            status=404,
        )

    canonical_text, _ = _extract_canonical_text(request)
    if not canonical_text.strip():
        return JsonResponse(
            {"error": "Bad Request", "detail": "Missing canonical_text"},
            status=400,
        )

    try:
        info = gameinfo.parse(canonical_text)
    except Exception as exc:
        return JsonResponse(
            {
                "error": "Bad Request",
                "detail": f"Failed to parse canonical text: {exc}",
            },
            status=400,
        )

    now = timezone.now()
    with transaction.atomic():
        prev_rev = (
            game.published_revision
            if game.state == Game.State.PUBLISHED and game.published_revision
            else GameRevision.objects.filter(game=game).order_by("-id").first()
        )
        prev_text = prev_rev.canonical_text if prev_rev else ""

        _, backfilled_text = info.save(game)

        is_pub = game.state == Game.State.PUBLISHED
        revision = GameRevision.objects.create(
            game=game,
            created_at=now,
            created_by=request.user,
            origin=GameRevision.Origin.API,
            status=(
                GameRevision.Status.ACCEPTED
                if is_pub
                else GameRevision.Status.PROPOSED
            ),
            published_at=now if is_pub else None,
            published_by=request.user if is_pub else None,
            previous_canonical_text=prev_text,
            canonical_text=backfilled_text,
        )

        if is_pub:
            game.published_revision = revision
            game.published_revision_id = revision.pk
            game.save(update_fields=["published_revision"])

    return JsonResponse(_game_response_data(game))


@csrf_exempt
@require_http_methods(["POST"])
@api_auth(perm="games:publish")
def game_publish(request: HttpRequest, game_id: int) -> HttpResponse:
    try:
        game = Game.objects.select_related("published_revision").get(
            pk=game_id
        )
    except Game.DoesNotExist:
        return JsonResponse(
            {"error": "Not Found", "detail": f"Game {game_id} does not exist"},
            status=404,
        )

    if game.state == Game.State.PUBLISHED:
        return JsonResponse({"id": game.id, "state": game.state.lower()})

    with transaction.atomic():
        latest_rev = (
            GameRevision.objects.filter(game=game).order_by("-id").first()
        )
        if latest_rev is None:
            now = timezone.now()
            info = (
                gameinfo.GameInfo.from_game(game)
                if game.published_revision_id
                else gameinfo.GameInfo(
                    name=game.title, description=game.description
                )
            )
            latest_rev = GameRevision.objects.create(
                game=game,
                created_at=now,
                created_by=request.user,
                origin=GameRevision.Origin.API,
                status=GameRevision.Status.PROPOSED,
                canonical_text=info.to_canonical(),
            )
        game.publish_revision(latest_rev, actor=request.user)

    return JsonResponse({"id": game.id, "state": game.state.lower()})


@csrf_exempt
@require_http_methods(["POST"])
@api_auth(perm="games:publish")
def game_unpublish(request: HttpRequest, game_id: int) -> HttpResponse:
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return JsonResponse(
            {"error": "Not Found", "detail": f"Game {game_id} does not exist"},
            status=404,
        )

    if game.state == Game.State.DRAFT:
        return JsonResponse({"id": game.id, "state": game.state.lower()})

    game.state = Game.State.DRAFT
    game.edit_time = timezone.now()
    game.save(update_fields=["state", "edit_time"])

    return JsonResponse({"id": game.id, "state": game.state.lower()})


@csrf_exempt
@require_http_methods(["POST"])
@api_auth(perm="files:upload")
def file_upload(
    request: HttpRequest, game_id: int | None = None
) -> HttpResponse:
    if "file" not in request.FILES:
        return JsonResponse(
            {
                "error": "Bad Request",
                "detail": "No file provided in 'file' field",
            },
            status=400,
        )

    target_game_id = game_id or request.POST.get("game_id")
    game: Game | None = None
    if target_game_id is not None:
        try:
            game = Game.objects.get(pk=int(target_game_id))
        except (ValueError, Game.DoesNotExist):
            return JsonResponse(
                {
                    "error": "Not Found",
                    "detail": f"Game {target_game_id} does not exist",
                },
                status=404,
            )

    uploaded = cast("UploadedFile[Any]", request.FILES["file"])
    fs = settings.UPLOADS_FS

    save_path = f"games/{game.id}/{uploaded.name}" if game else uploaded.name
    filename = fs.save(save_path, uploaded, max_length=128)
    file_url = fs.url(filename)
    url_full = request.build_absolute_uri(file_url)

    url = URL.objects.create(
        local_url=file_url,
        original_url=url_full,
        original_filename=uploaded.name,
        local_filename=filename,
        content_type=uploaded.content_type or "",
        ok_to_clone=True,
        is_uploaded=True,
        creation_date=timezone.now(),
        file_size=fs.size(filename),
        creator=request.user,
    )

    category_slug = request.POST.get("category", "download_direct")
    description = request.POST.get("description", "").strip()

    cat, _ = GameURLCategory.objects.get_or_create(
        symbolic_id=category_slug,
        defaults={"title": category_slug, "allow_cloning": True},
    )

    if game is None:
        return JsonResponse(
            {
                "url_id": url.id,
                "url": url_full,
                "filename": uploaded.name,
                "canonical_snippet": [cat.symbolic_id, description, url.id],
            },
            status=201,
        )

    with transaction.atomic():
        GameURL.objects.update_or_create(
            game=game,
            url=url,
            defaults={"category": cat, "description": description or None},
        )

        prev_rev = (
            game.published_revision
            if game.state == Game.State.PUBLISHED and game.published_revision
            else GameRevision.objects.filter(game=game).order_by("-id").first()
        )
        prev_text = prev_rev.canonical_text if prev_rev else ""

        current_info = (
            gameinfo.parse(prev_text)
            if prev_text
            else gameinfo.GameInfo(
                name=game.title, description=game.description
            )
        )
        current_info.urls.append(
            gameinfo.GameUrl(
                category=cat.symbolic_id,
                url_id=url.id,
                description=description or None,
                url=url_full,
            )
        )
        _, fresh_canonical = current_info.save(game)

        now = timezone.now()
        is_pub = game.state == Game.State.PUBLISHED
        rev = GameRevision.objects.create(
            game=game,
            created_at=now,
            created_by=request.user,
            origin=GameRevision.Origin.API,
            status=(
                GameRevision.Status.ACCEPTED
                if is_pub
                else GameRevision.Status.PROPOSED
            ),
            published_at=now if is_pub else None,
            published_by=request.user if is_pub else None,
            previous_canonical_text=prev_text,
            canonical_text=fresh_canonical,
        )
        if is_pub:
            game.published_revision = rev
            game.published_revision_id = rev.pk
            game.save(update_fields=["published_revision"])

    return JsonResponse(
        {
            "game_id": game.id,
            "url_id": url.id,
            "url": url_full,
            "filename": uploaded.name,
            "category": cat.symbolic_id,
            "description": description,
            "canonical_snippet": [cat.symbolic_id, description, url.id],
            "canonical_text": fresh_canonical,
        },
        status=201,
    )
