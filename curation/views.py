from datetime import timedelta

from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now

from .models import (
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameHistoryComment,
    GameSource,
    GameSourceFetch,
)

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


def history_list(request):
    request.perm.Ensure(PERM)

    state = request.GET.get("state") or ""
    auto = request.GET.get("auto") or ""
    sort = request.GET.get("sort") or "priority"

    histories = GameHistory.objects.select_related("game").annotate(
        updated=Coalesce("edit_time", "creation_time")
    )
    if state:
        histories = histories.filter(state=state)
    if auto:
        histories = histories.filter(auto_updates=auto)

    if sort == "updated":
        histories = histories.order_by("-updated")
    else:
        sort = "priority"
        histories = histories.order_by("priority", "-updated")

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
