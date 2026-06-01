from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, OuterRef, Q, Subquery, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now

from .diff import build_diff
from .gameinfo import GameInfo
from .models import (
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameHistoryComment,
    GameSource,
    GameSourceFetch,
    SourceDiscoveryStatus,
)
from .providers import REGISTERED_PROVIDERS

PERM = "(alias curation_admin)"

GROUP_WINDOW = timedelta(minutes=1)


def _group_timeline(timeline):
    """Collapse consecutive same-kind entries within GROUP_WINDOW."""
    groups = []
    for entry in timeline:  # timeline is already sorted by ts
        last = groups[-1] if groups else None
        if (
            last
            and last["kind"] == entry["kind"]
            and entry["ts"] - last["ts_start"] <= GROUP_WINDOW
        ):
            last["entries"].append(entry)
            last["ts_end"] = entry["ts"]
        else:
            groups.append({
                "kind": entry["kind"],
                "color": entry["color"],
                "ts_start": entry["ts"],
                "ts_end": entry["ts"],
                "who": entry["who"],
                "entries": [entry],
            })
    return groups


# Card colour per comment type, so the timeline distinguishes them visually.
COMMENT_TYPE_COLORS = {
    GameHistoryComment.CommentType.USER_FEEDBACK: "yellow",
    GameHistoryComment.CommentType.MODS_COMMENT: "blue",
    GameHistoryComment.CommentType.NOTE_FOR_AI: "purple",
    GameHistoryComment.CommentType.STATUS_MESSAGE: "salad",
    GameHistoryComment.CommentType.EMAIL_RESPONSE: "orange",
}

# Fields editable from the detail view, mapped to their model choices.
EDITABLE_FIELDS = {
    "auto_updates": (
        GameHistory.AutoUpdate,
        GameHistoryAuditLog.AuditField.AUTO_UPDATES,
    ),
    "state": (GameHistory.State, GameHistoryAuditLog.AuditField.STATE),
}

HISTORY_STATE_SHORT = {
    GameHistory.State.SETTLED: "готово",
    GameHistory.State.IN_PROGRESS: "в работе",
    GameHistory.State.NEEDS_ATTENTION: "внимание",
}
HISTORY_AUTO_SHORT = {
    GameHistory.AutoUpdate.REJECT: "откл.",
    GameHistory.AutoUpdate.PROPOSE: "предл.",
    GameHistory.AutoUpdate.ACCEPT: "авто",
}


def history_list(request):
    request.perm.Ensure(PERM)

    state = request.GET.get("state") or ""
    auto = request.GET.get("auto") or ""
    sort = request.GET.get("sort") or "relevance"

    histories = GameHistory.objects.select_related("game").annotate(
        updated=Coalesce("edit_time", "creation_time")
    )
    if state:
        histories = histories.filter(state=state)
    if auto:
        histories = histories.filter(auto_updates=auto)

    if sort == "updated":
        histories = histories.order_by("-updated")
    elif sort == "priority":
        histories = histories.annotate(
            state_rank=Case(
                When(state=GameHistory.State.NEEDS_ATTENTION, then=0),
                When(state=GameHistory.State.IN_PROGRESS, then=1),
                When(state=GameHistory.State.SETTLED, then=2),
                default=3,
                output_field=IntegerField(),
            )
        ).order_by("state_rank", "priority", "-updated")
    else:
        sort = "relevance"
        histories = histories.annotate(
            attention_rank=Case(
                When(state=GameHistory.State.NEEDS_ATTENTION, then=0),
                default=1,
                output_field=IntegerField(),
            ),
            attention_priority=Case(
                When(
                    state=GameHistory.State.NEEDS_ATTENTION,
                    then="priority",
                ),
                default=0,
                output_field=IntegerField(),
            ),
        ).order_by("attention_rank", "attention_priority", "-updated")

    for history in histories:
        history.state_short = HISTORY_STATE_SHORT.get(
            history.state, history.state
        )
        history.auto_short = HISTORY_AUTO_SHORT.get(
            history.auto_updates, history.auto_updates
        )

    return render(
        request,
        "curation/history_list.html",
        {
            "histories": histories,
            "state": state,
            "auto": auto,
            "sort": sort,
            "state_choices": GameHistory.State.choices,
            "auto_choices": GameHistory.AutoUpdate.choices,
        },
    )


def discovery_status(request):
    request.perm.Ensure(PERM)

    current = [
        latest
        for provider in REGISTERED_PROVIDERS
        if (
            latest := SourceDiscoveryStatus.objects
            .filter(source_type=provider.source_type)
            .order_by("-last_seen")
            .first()
        )
    ]
    history = SourceDiscoveryStatus.objects.order_by("-last_seen")[:1000]

    return render(
        request,
        "curation/discovery_status.html",
        {"current": current, "history": history},
    )


def source_list(request):
    request.perm.Ensure(PERM)

    q = request.GET.get("q", "").strip()
    source_type = request.GET.get("type", "")
    state = request.GET.get("state", "")
    latest_fetch = GameSourceFetch.objects.filter(
        source=OuterRef("pk")
    ).order_by("-last_fetch", "-pk")
    sources = GameSource.objects.select_related("history__game").annotate(
        latest_fetch_id=Subquery(latest_fetch.values("pk")[:1]),
        latest_fetch_at=Subquery(latest_fetch.values("last_fetch")[:1]),
    )

    if q:
        sources = sources.filter(
            Q(url__icontains=q) | Q(history__game__title__icontains=q)
        )
    if source_type in GameSource.SourceType.values:
        sources = sources.filter(type=source_type)
    else:
        source_type = ""
    if state == "failed":
        sources = sources.filter(
            Q(failing_since__isnull=False) | Q(last_error__gt="")
        )
    elif state == "missing":
        sources = sources.filter(missing_since__isnull=False)
    else:
        state = ""

    sources = sources.order_by("type", "url", "pk")
    page = Paginator(sources, 100).get_page(request.GET.get("page"))

    return render(
        request,
        "curation/source_list.html",
        {
            "page": page,
            "sources": page.object_list,
            "q": q,
            "source_type": source_type,
            "state": state,
            "source_type_choices": GameSource.SourceType.choices,
        },
    )


def source_detail(request, source_id):
    request.perm.Ensure(PERM)

    source = get_object_or_404(
        GameSource.objects.select_related("history__game"), pk=source_id
    )
    fetches = source.gamesourcefetch_set.order_by("-last_fetch", "-pk")

    return render(
        request,
        "curation/source_detail.html",
        {"source": source, "fetches": fetches},
    )


def source_fetch_content(request, fetch_id, kind):
    request.perm.Ensure(PERM)

    fetch = get_object_or_404(GameSourceFetch, pk=fetch_id)
    if kind == "raw":
        content = fetch.raw_content
    else:
        content = fetch.canonical_text

    return HttpResponse(content, content_type="text/plain; charset=utf-8")


def _sources_by_ids(ids):
    sources = GameSource.objects.filter(id__in=ids).select_related(
        "history__game"
    )
    by_id = {source.id: source for source in sources}
    return [by_id[id_] for id_ in ids if id_ in by_id]


def _source_clusters(clusters):
    return [_sources_by_ids(cluster) for cluster in clusters]


def discovery_detail(request, status_id):
    request.perm.Ensure(PERM)

    status = get_object_or_404(SourceDiscoveryStatus, pk=status_id)
    panels = [
        {
            "id": "new",
            "title": "Новые источники",
            "color": "green",
            "sources": _sources_by_ids(status.new_ids),
            "empty": "Новых источников нет.",
        },
        {
            "id": "newly-missing",
            "title": "Пропавшие",
            "color": "red",
            "sources": _sources_by_ids(status.newly_missing_ids),
            "empty": "Пропавших источников нет.",
        },
        {
            "id": "absent",
            "title": "Отсутствующие",
            "color": "yellow",
            "sources": _sources_by_ids(status.absent_ids),
            "empty": "Отсутствующих источников нет.",
        },
        {
            "id": "unused",
            "title": "Неиспользуемые",
            "color": "brown",
            "sources": _sources_by_ids(status.unused_ids),
            "empty": "Неиспользуемых источников нет.",
        },
        {
            "id": "existing",
            "title": "Существующие",
            "color": "purple",
            "sources": _sources_by_ids(status.existing_ids),
            "empty": "Существующих источников нет.",
        },
    ]

    return render(
        request,
        "curation/discovery_detail.html",
        {
            "status": status,
            "panels": panels,
            "duplicate_clusters": _source_clusters(
                status.duplicate_id_clusters
            ),
        },
    )


def history_detail(request, history_id):
    request.perm.Ensure(PERM)

    history = get_object_or_404(
        GameHistory.objects.select_related("game"), pk=history_id
    )
    sources = list(GameSource.objects.filter(history=history))

    timeline = []
    for source in sources:
        if source.created_at:
            timeline.append({
                "ts": source.created_at,
                "kind": "source",
                "color": "brown",
                "obj": source,
                "who": None,
            })

    fetches = GameSourceFetch.objects.filter(
        source__history=history
    ).select_related("source")
    for fetch in fetches:
        timeline.append({
            "ts": fetch.first_fetch,
            "kind": "fetch",
            "color": "salad",
            "obj": fetch,
            "who": None,
            "label": "Первая загрузка",
        })
        if fetch.last_fetch != fetch.first_fetch:
            timeline.append({
                "ts": fetch.last_fetch,
                "kind": "fetch",
                "color": "salad",
                "obj": fetch,
                "who": None,
                "label": "Последняя загрузка",
            })

    for edit in GameEdit.objects.filter(history=history).select_related(
        "approver"
    ):
        timeline.append({
            "ts": edit.proposed_at,
            "kind": "edit",
            "color": "green",
            "obj": edit,
            "who": edit.approver,
        })

    for comment in GameHistoryComment.objects.filter(
        history=history
    ).select_related("user"):
        timeline.append({
            "ts": comment.creation_time,
            "kind": "comment",
            "color": COMMENT_TYPE_COLORS.get(comment.type, "blue"),
            "obj": comment,
            "who": comment.user,
        })

    for log in GameHistoryAuditLog.objects.filter(
        history=history
    ).select_related("actor"):
        timeline.append({
            "ts": log.created_at,
            "kind": "audit",
            "color": "yellow",
            "obj": log,
            "who": log.actor,
        })

    timeline.sort(key=lambda e: e["ts"])

    return render(
        request,
        "curation/history_detail.html",
        {
            "history": history,
            "game": history.game,
            "sources": sources,
            "groups": _group_timeline(timeline),
            "auto_choices": GameHistory.AutoUpdate.choices,
            "state_choices": GameHistory.State.choices,
        },
    )


def edit_diff(request, edit_id):
    request.perm.Ensure(PERM)

    edit = get_object_or_404(
        GameEdit.objects.select_related("history__game"), pk=edit_id
    )
    history = edit.history
    before = ""
    if history.game is not None:
        before = GameInfo.from_game(history.game).to_canonical()

    return render(
        request,
        "curation/edit_diff.html",
        {
            "edit": edit,
            "game": history.game,
            "history": history,
            "rows": build_diff(before, edit.canonical_text),
        },
    )


def history_edit(request, history_id):
    request.perm.Ensure(PERM)

    history = get_object_or_404(GameHistory, pk=history_id)
    if request.method == "POST":
        changed = False
        for field, (choices, audit_field) in EDITABLE_FIELDS.items():
            value = request.POST.get(field)
            old = getattr(history, field)
            if value in choices.values and old != value:
                GameHistoryAuditLog.record_change(
                    history, request.user, audit_field, old, value
                )
                setattr(history, field, value)
                changed = True
        if changed:
            history.edit_time = now()
            history.save()

    return redirect("curation_history_detail", history_id=history.pk)
