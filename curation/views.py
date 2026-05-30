from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now

from .models import (
    GameReconciliation,
    GameSource,
    GameSourceFetch,
    GameTicket,
    GameTicketAuditLog,
    GameTicketComment,
)

PERM = "(alias curation_admin)"

# Card colour per comment type, so the timeline distinguishes them visually.
COMMENT_TYPE_COLORS = {
    GameTicketComment.CommentType.USER_FEEDBACK: "yellow",
    GameTicketComment.CommentType.MODS_COMMENT: "blue",
    GameTicketComment.CommentType.NOTE_FOR_AI: "purple",
    GameTicketComment.CommentType.STATUS_MESSAGE: "salad",
    GameTicketComment.CommentType.EMAIL_RESPONSE: "orange",
}

# Fields editable from the detail view, mapped to their model choices.
EDITABLE_FIELDS = {
    "auto_updates": (
        GameTicket.AutoUpdate,
        GameTicketAuditLog.AuditField.AUTO_UPDATES,
    ),
    "state": (GameTicket.State, GameTicketAuditLog.AuditField.STATE),
}


def ticket_list(request):
    request.perm.Ensure(PERM)

    state = request.GET.get("state") or ""
    auto = request.GET.get("auto") or ""
    sort = request.GET.get("sort") or "priority"

    tickets = GameTicket.objects.select_related("game").annotate(
        updated=Coalesce("edit_time", "creation_time")
    )
    if state:
        tickets = tickets.filter(state=state)
    if auto:
        tickets = tickets.filter(auto_updates=auto)

    if sort == "updated":
        tickets = tickets.order_by("-updated")
    else:
        sort = "priority"
        tickets = tickets.order_by("priority", "-updated")

    return render(
        request,
        "curation/ticket_list.html",
        {
            "tickets": tickets,
            "state": state,
            "auto": auto,
            "sort": sort,
            "state_choices": GameTicket.State.choices,
            "auto_choices": GameTicket.AutoUpdate.choices,
        },
    )


def ticket_detail(request, ticket_id):
    request.perm.Ensure(PERM)

    ticket = get_object_or_404(
        GameTicket.objects.select_related("game"), pk=ticket_id
    )
    sources = list(GameSource.objects.filter(ticket=ticket))

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
        source__ticket=ticket
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

    for rec in GameReconciliation.objects.filter(ticket=ticket).select_related(
        "approver"
    ):
        timeline.append({
            "ts": rec.proposed_at,
            "kind": "reconciliation",
            "color": "green",
            "obj": rec,
            "who": rec.approver,
        })

    for comment in GameTicketComment.objects.filter(
        ticket=ticket
    ).select_related("user"):
        timeline.append({
            "ts": comment.creation_time,
            "kind": "comment",
            "color": COMMENT_TYPE_COLORS.get(comment.type, "blue"),
            "obj": comment,
            "who": comment.user,
        })

    for log in GameTicketAuditLog.objects.filter(ticket=ticket).select_related(
        "actor"
    ):
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
        "curation/ticket_detail.html",
        {
            "ticket": ticket,
            "game": ticket.game,
            "sources": sources,
            "timeline": timeline,
            "auto_choices": GameTicket.AutoUpdate.choices,
            "state_choices": GameTicket.State.choices,
        },
    )


def ticket_edit(request, ticket_id):
    request.perm.Ensure(PERM)

    ticket = get_object_or_404(GameTicket, pk=ticket_id)
    if request.method == "POST":
        changed = False
        for field, (choices, audit_field) in EDITABLE_FIELDS.items():
            value = request.POST.get(field)
            old = getattr(ticket, field)
            if value in choices.values and old != value:
                GameTicketAuditLog.record_change(
                    ticket, request.user, audit_field, old, value
                )
                setattr(ticket, field, value)
                changed = True
        if changed:
            ticket.edit_time = now()
            ticket.save()

    return redirect("curation_ticket_detail", ticket_id=ticket.pk)
