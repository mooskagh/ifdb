import copy
import json
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Avg,
    Case,
    Count,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    When,
)
from django.db.models.functions import Coalesce, TruncMonth
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import now
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from core.tasks import fetch_feeds
from games.importer.discord import PostNewGameToDiscord
from games.models import Game

from . import openrouter
from .diff import build_diff
from .gameinfo import GameInfo, parse
from .manual_reconcile import (
    column_for_game,
    initial_payload,
    save_reconcile_payload,
)
from .merge import contest_related_usage, merge_game_into_history
from .models import (
    EditPipeline,
    GameEdit,
    GameHistory,
    GameHistoryAuditLog,
    GameHistoryComment,
    GameSource,
    GameSourceFetch,
    LLMModel,
    LlmTrajectory,
    SourceDiscoveryStatus,
)
from .providers import REGISTERED_PROVIDERS
from .tasks import (
    discover_sources,
    edit_sources,
    fetch_sources,
    reconcile_sources,
)

GROUP_WINDOW = timedelta(minutes=1)

FETCH_SOURCES_TASK_NAME = "Fetch sources"
FETCH_SOURCES_TASK = "curation.tasks.fetch_sources"
DISCOVER_SOURCES_TASK_NAME = "Discover sources"
DISCOVER_SOURCES_TASK = "curation.tasks.discover_sources"
RECONCILE_SOURCES_TASK_NAME = "Reconcile sources"
RECONCILE_SOURCES_TASK = "curation.tasks.reconcile_sources"
FETCH_FEEDS_TASK_NAME = "Fetch feeds"
FETCH_FEEDS_TASK = "core.tasks.fetch_feeds"
EDIT_SOURCES_TASK_NAME = "Edit sources"
EDIT_SOURCES_TASK = "curation.tasks.edit_sources"
INTERVAL_PERIODS = [
    (IntervalSchedule.MINUTES, "минут"),
    (IntervalSchedule.HOURS, "часов"),
    (IntervalSchedule.DAYS, "дней"),
]
INTERVAL_PERIOD_VALUES = {period for period, _label in INTERVAL_PERIODS}


def _display_passes(passes):
    display = []
    for item in passes:
        if isinstance(item, str):
            display.append({"name": item, "params": {}})
        elif isinstance(item, dict):
            display.append({
                "name": item.get("name", "—"),
                "params": {k: v for k, v in item.items() if k != "name"},
            })
        else:
            display.append({"name": str(item), "params": {}})
    return display


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
    GameHistory.State.SCHEDULED_FOR_UPDATE: "заплан.",
    GameHistory.State.PROCESSING: "обраб.",
    GameHistory.State.NEEDS_ATTENTION: "внимание",
    GameHistory.State.ABANDONED: "заброш.",
}
HISTORY_AUTO_SHORT = {
    GameHistory.AutoUpdate.REJECT: "откл.",
    GameHistory.AutoUpdate.PROPOSE: "предл.",
    GameHistory.AutoUpdate.ACCEPT: "авто",
}


def history_list(request):
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state") or ""
    auto = request.GET.get("auto") or ""
    sort = request.GET.get("sort") or "relevance"

    pending_edits = GameEdit.objects.filter(
        history=OuterRef("pk"), status=GameEdit.EditStatus.PROPOSED
    ).order_by("-proposed_at", "-pk")
    histories = GameHistory.objects.select_related("game").annotate(
        updated=Coalesce("edit_time", "creation_time"),
        pending_edit_id=Subquery(pending_edits.values("pk")[:1]),
    )
    if q:
        histories = histories.filter(game__title__icontains=q)
    if state:
        histories = histories.filter(state=state)
    if auto:
        histories = histories.filter(auto_updates=auto)

    if sort == "updated":
        histories = histories.order_by("-updated")
    else:
        sort = "relevance"
        histories = histories.annotate(
            attention_rank=Case(
                When(state=GameHistory.State.NEEDS_ATTENTION, then=0),
                default=1,
                output_field=IntegerField(),
            ),
        ).order_by("attention_rank", "-updated")

    page = Paginator(histories, 500).get_page(request.GET.get("page"))
    histories = page.object_list

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
            "page": page,
            "histories": histories,
            "q": q,
            "state": state,
            "auto": auto,
            "sort": sort,
            "state_choices": GameHistory.State.choices,
            "auto_choices": GameHistory.AutoUpdate.choices,
        },
    )


def discovery_status(request):
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


def tasks(request):
    if request.method == "POST":
        return _tasks_post(request)

    return _render_tasks(request)


def _tasks_post(request):
    action = request.POST.get("action")
    if action == "run_discover_sources":
        source_type = request.POST.get("source_type")
        types = [source_type] if source_type in _discoverable_types() else None
        discover_sources.delay(types=types)
        messages.success(
            request, "Задание на вытягивание списков игр запущено."
        )
    elif action == "run_reconcile_sources":
        reconcile_sources.delay()
        messages.success(
            request, "Задание на обработку новых источников запущено."
        )
    elif action == "run_fetch_sources":
        limit = _positive_int(request.POST.get("run_limit"), default=5)
        fetch_sources.delay(limit=limit)
        messages.success(
            request, "Задание на выкачивание источников запущено."
        )
    elif action == "run_fetch_feeds":
        fetch_feeds.delay()
        messages.success(request, "Задание на выкачивание форумов запущено.")
    elif action == "run_edit_sources":
        limit = _positive_int(request.POST.get("run_limit"), default=5)
        pipeline = _pipeline_from_post(request.POST)
        edit_sources.delay(limit=limit, pipeline_id=pipeline.pk)
        messages.success(request, "Задание на обработку очереди запущено.")
    elif action == "save_fetch_sources":
        limit = _positive_int(request.POST.get("periodic_limit"), default=5)
        _save_periodic_task(
            FETCH_SOURCES_TASK_NAME,
            FETCH_SOURCES_TASK,
            request.POST,
            kwargs={"limit": limit},
        )
        messages.success(
            request, "Расписание выкачивания источников сохранено."
        )
    elif action == "save_discover_sources":
        pipeline = _pipeline_from_post(request.POST)
        _save_periodic_task(
            DISCOVER_SOURCES_TASK_NAME,
            DISCOVER_SOURCES_TASK,
            request.POST,
            kwargs={
                "types": None,
                "auto_import_new": request.POST.get("auto_import_new") == "on",
                "pipeline_id": pipeline.pk,
            },
        )
        messages.success(
            request, "Расписание вытягивания списков игр сохранено."
        )
    elif action == "save_reconcile_sources":
        _save_periodic_task(
            RECONCILE_SOURCES_TASK_NAME,
            RECONCILE_SOURCES_TASK,
            request.POST,
        )
        messages.success(
            request, "Расписание обработки новых источников сохранено."
        )
    elif action == "save_fetch_feeds":
        _save_periodic_task(
            FETCH_FEEDS_TASK_NAME,
            FETCH_FEEDS_TASK,
            request.POST,
        )
        messages.success(request, "Расписание выкачивания форумов сохранено.")
    elif action == "save_edit_sources":
        limit = _positive_int(request.POST.get("periodic_limit"), default=5)
        pipeline = _pipeline_from_post(request.POST)
        _save_periodic_task(
            EDIT_SOURCES_TASK_NAME,
            EDIT_SOURCES_TASK,
            request.POST,
            kwargs={"limit": limit, "pipeline_id": pipeline.pk},
        )
        messages.success(request, "Расписание обработки очереди сохранено.")
    else:
        return HttpResponseBadRequest("Unknown action.")
    return redirect("curation_tasks")


def _render_tasks(request):
    orphan_total = GameSource.objects.filter(
        history__isnull=True, keep_orphan=False
    ).count()
    orphan_ready = (
        GameSource.objects
        .filter(
            history__isnull=True,
            keep_orphan=False,
            gamesourcefetch__isnull=False,
        )
        .distinct()
        .count()
    )
    scheduled_histories = GameHistory.objects.filter(
        state=GameHistory.State.SCHEDULED_FOR_UPDATE
    ).count()
    return render(
        request,
        "curation/tasks.html",
        {
            "discoverable_types": _discoverable_type_choices(),
            "orphan_ready": orphan_ready,
            "orphan_total": orphan_total,
            "scheduled_histories": scheduled_histories,
            "periods": INTERVAL_PERIODS,
            "discover_sources": _periodic_task_config(
                DISCOVER_SOURCES_TASK_NAME,
                default_every=1,
                default_period=IntervalSchedule.HOURS,
            ),
            "reconcile_sources": _periodic_task_config(
                RECONCILE_SOURCES_TASK_NAME,
                default_every=5,
                default_period=IntervalSchedule.MINUTES,
            ),
            "fetch_sources": _periodic_task_config(
                FETCH_SOURCES_TASK_NAME,
                default_every=5,
                default_period=IntervalSchedule.MINUTES,
                default_periodic_limit=5,
                default_run_limit=5,
            ),
            "fetch_feeds": _periodic_task_config(
                FETCH_FEEDS_TASK_NAME,
                default_every=1,
                default_period=IntervalSchedule.HOURS,
            ),
            "edit_sources": _periodic_task_config(
                EDIT_SOURCES_TASK_NAME,
                default_every=5,
                default_period=IntervalSchedule.MINUTES,
                default_periodic_limit=5,
                default_run_limit=5,
            ),
            "edit_pipelines": EditPipeline.objects.order_by("id"),
        },
    )


def _pipeline_from_post(data):
    return get_object_or_404(EditPipeline, pk=data.get("pipeline"))


def _discoverable_types():
    return {provider.source_type for provider in REGISTERED_PROVIDERS}


def _discoverable_type_choices():
    labels = dict(GameSource.SourceType.choices)
    return [
        (provider.source_type, labels[provider.source_type])
        for provider in REGISTERED_PROVIDERS
    ]


def _periodic_task_config(
    name,
    *,
    default_every,
    default_period,
    default_periodic_limit=None,
    default_run_limit=None,
):
    task = (
        PeriodicTask.objects
        .filter(name=name)
        .select_related("interval")
        .first()
    )
    kwargs = _task_kwargs(task)
    return {
        "enabled": task.enabled if task else False,
        "every": task.interval.every
        if task and task.interval
        else default_every,
        "period": task.interval.period
        if task and task.interval
        else default_period,
        "periodic_limit": kwargs.get("limit", default_periodic_limit),
        "run_limit": default_run_limit,
        "pipeline_id": kwargs.get("pipeline_id"),
        "auto_import_new": kwargs.get("auto_import_new", False),
    }


def _task_kwargs(task):
    if not task or not task.kwargs:
        return {}
    try:
        return json.loads(task.kwargs)
    except json.JSONDecodeError:
        return {}


def _save_periodic_task(name, task, data, kwargs=None):
    every = _positive_int(data.get("every"), default=1)
    period = data.get("period")
    if period not in INTERVAL_PERIOD_VALUES:
        period = IntervalSchedule.HOURS
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=every,
        period=period,
    )
    PeriodicTask.objects.update_or_create(
        name=name,
        defaults={
            "interval": schedule,
            "task": task,
            "args": json.dumps([]),
            "kwargs": json.dumps(kwargs or {}),
            "enabled": data.get("enabled") == "on",
        },
    )


def _positive_int(value, *, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def llm_trajectories(request):
    aggregates = {
        "count": Count("id"),
        "total_cost": Sum("cost"),
        "avg_cost_cents": Avg("cost") * 100,
        "avg_prompt_tokens": Avg("prompt_tokens"),
        "avg_cached_input_tokens": Avg("cached_input_tokens"),
        "avg_cache_write_tokens": Avg("cache_write_tokens"),
        "avg_completion_tokens": Avg("completion_tokens"),
    }
    months = list(
        LlmTrajectory.objects
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(**aggregates)
        .order_by("-month")
    )
    breakdowns = (
        LlmTrajectory.objects
        .annotate(month=TruncMonth("created_at"))
        .values("month", "workflow__name", "model__name")
        .annotate(**aggregates)
        .order_by("-month", "workflow__name", "model__name")
    )
    month_by_key = {month["month"]: month for month in months}
    for month in months:
        month["breakdowns"] = []
    for row in breakdowns:
        month_by_key[row["month"]]["breakdowns"].append(row)

    trajectories = (
        LlmTrajectory.objects
        .select_related("workflow", "history__game")
        .annotate(cost_cents=F("cost") * 100)
        .order_by("-created_at", "-pk")
    )
    page = Paginator(trajectories, 100).get_page(request.GET.get("page"))

    return render(
        request,
        "curation/llm_trajectories.html",
        {
            "months": months,
            "page": page,
            "trajectories": page.object_list,
        },
    )


def llm_trajectory_detail(request, trajectory_id):
    trajectory = get_object_or_404(
        LlmTrajectory.objects.select_related(
            "workflow", "model", "history__game", "edit"
        ).annotate(cost_cents=F("cost") * 100),
        pk=trajectory_id,
    )
    return render(
        request,
        "curation/llm_trajectory_detail.html",
        {"trajectory": trajectory},
    )


def source_list(request):
    q = request.GET.get("q", "").strip()
    source_type = request.GET.get("type", "")
    state = request.GET.get("state", "")
    attached = request.GET.get("attached", "")
    sort = request.GET.get("sort") or "last_attempt"
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
    if attached == "orphan":
        sources = sources.filter(history__isnull=True)
    elif attached == "attached":
        sources = sources.filter(history__isnull=False)
    else:
        attached = ""

    match sort:
        case "last_fetch":
            sources = sources.order_by(
                F("latest_fetch_at").desc(nulls_last=True), "-pk"
            )
        case "created":
            sources = sources.order_by(
                F("created_at").desc(nulls_last=True), "-pk"
            )
        case "url":
            sources = sources.order_by("type", "url", "pk")
        case _:
            sort = "last_attempt"
            sources = sources.order_by(
                F("last_attempt").desc(nulls_last=True), "-pk"
            )
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
            "attached": attached,
            "sort": sort,
            "source_type_choices": GameSource.SourceType.choices,
        },
    )


def source_detail(request, source_id):
    source = get_object_or_404(
        GameSource.objects.select_related("history__game"), pk=source_id
    )
    if request.method == "POST":
        source.keep_orphan = request.POST.get("keep_orphan") == "on"
        source.save(update_fields=["keep_orphan"])
        messages.success(request, "Настройки источника сохранены.")
        return redirect("curation_source_detail", source_id=source.pk)

    fetches = source.gamesourcefetch_set.order_by("-last_fetch", "-pk")

    return render(
        request,
        "curation/source_detail.html",
        {"source": source, "fetches": fetches},
    )


def source_fetch_now(request, source_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST is supported.")

    source = get_object_or_404(GameSource, pk=source_id)
    fetch_sources.delay(limit=None, source_id=source.pk)
    messages.success(request, f"Источник #{source.pk} поставлен в очередь.")
    return redirect(
        request.POST.get("next") or "curation_source_detail",
        source_id=source.pk,
    )


def source_fetch_content(request, fetch_id, kind):
    fetch = get_object_or_404(GameSourceFetch, pk=fetch_id)
    if kind == "raw":
        content = fetch.raw_content
    else:
        content = fetch.canonical_text

    return HttpResponse(content, content_type="text/plain; charset=utf-8")


def history_source_add(request, history_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST is supported.")

    history = get_object_or_404(GameHistory, pk=history_id)
    source_id = (request.POST.get("source_id") or "").strip()
    if source_id:
        with transaction.atomic():
            source = get_object_or_404(
                GameSource.objects.select_for_update(), pk=source_id
            )
            if source.history_id is not None:
                return HttpResponseBadRequest("Source is already attached.")
            _attach_source(history, source, request.user)
        return redirect("curation_history_detail", history_id=history.pk)

    source_type = request.POST.get("type")
    if source_type not in GameSource.SourceType.values:
        return HttpResponseBadRequest("Unknown source type.")
    url = request.POST.get("url", "").strip() or None

    with transaction.atomic():
        source = None
        if url:
            existing = (
                GameSource.objects
                .select_for_update()
                .filter(type=source_type, url=url)
                .order_by("history_id", "pk")
                .first()
            )
            if existing and existing.history_id is not None:
                return HttpResponseBadRequest("Source is already attached.")
            source = existing
        if source is None:
            source = GameSource.objects.create(
                type=source_type,
                url=url,
                created_at=now(),
            )
        _attach_source(history, source, request.user)

    return redirect("curation_history_detail", history_id=history.pk)


def _attach_source(history, source, user):
    source.history = history
    source.save(update_fields=["history"])
    GameHistoryAuditLog.record_source(
        history,
        user,
        GameHistoryAuditLog.AuditKind.SOURCE_ATTACHED,
        source,
    )
    history.edit_time = now()
    history.save(update_fields=["edit_time"])


def history_sources_fetch_now(request, history_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST is supported.")

    history = get_object_or_404(GameHistory, pk=history_id)
    source_ids = list(
        GameSource.objects.filter(history=history).values_list("pk", flat=True)
    )
    for source_id in source_ids:
        fetch_sources.delay(limit=None, source_id=source_id)
    messages.success(
        request, f"Источники поставлены в очередь: {len(source_ids)}."
    )
    return redirect("curation_history_detail", history_id=history.pk)


# LLMModel fields synced from OpenRouter, compared to skip unchanged rows.
LLM_SYNC_FIELDS = [
    "context_length",
    "input_cost",
    "cached_input_cost",
    "cache_write_cost",
    "output_cost",
]


def llm_models(request):
    if request.method == "POST":
        return _llm_models_post(request)

    available = [openrouter.model_fields(e) for e in openrouter.fetch_models()]
    installed = list(LLMModel.objects.order_by("name"))
    installed_names = {model.name for model in installed}

    return render(
        request,
        "curation/llm_models.html",
        {
            "installed": installed,
            "available": available,
            "installed_names": installed_names,
        },
    )


def _llm_models_post(request):
    action = request.POST.get("action")
    fields_by_name = {
        entry["id"]: openrouter.model_fields(entry)
        for entry in openrouter.fetch_models()
    }

    if action == "update_all":
        for model in LLMModel.objects.all():
            fields = fields_by_name.get(model.name)
            if not fields or all(
                getattr(model, f) == fields[f] for f in LLM_SYNC_FIELDS
            ):
                continue
            for f in LLM_SYNC_FIELDS:
                setattr(model, f, fields[f])
            model.updated_at = now()
            model.save()
    elif action == "add":
        fields = fields_by_name.get(request.POST.get("name"))
        if fields:
            LLMModel.objects.create(**fields, updated_at=now())
    else:
        return HttpResponseBadRequest("Unknown action.")

    return redirect("curation_llm_models")


def history_source_detach(request, history_id, source_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST is supported.")

    with transaction.atomic():
        history = get_object_or_404(
            GameHistory.objects.select_for_update(), pk=history_id
        )
        source = get_object_or_404(
            GameSource.objects.select_for_update(),
            pk=source_id,
            history=history,
        )
        GameHistoryAuditLog.record_source(
            history,
            request.user,
            GameHistoryAuditLog.AuditKind.SOURCE_DETACHED,
            source,
        )
        source.history = None
        source.save(update_fields=["history"])
        history.edit_time = now()
        history.save(update_fields=["edit_time"])

    return redirect("curation_history_detail", history_id=history.pk)


def _sources_by_ids(ids):
    sources = GameSource.objects.filter(id__in=ids).select_related(
        "history__game"
    )
    by_id = {source.id: source for source in sources}
    return [by_id[id_] for id_ in ids if id_ in by_id]


def _source_clusters(clusters):
    return [_sources_by_ids(cluster) for cluster in clusters]


def discovery_detail(request, status_id):
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

    edits = list(
        GameEdit.objects
        .filter(history=history)
        .select_related("proposed_by", "approver")
        .prefetch_related(
            Prefetch(
                "llmtrajectory_set",
                queryset=LlmTrajectory.objects.select_related(
                    "workflow", "model"
                ).order_by("created_at", "pk"),
                to_attr="llm_trajectories",
            )
        )
    )
    for edit in edits:
        edit.display_passes = _display_passes(edit.passes)
        timeline.append({
            "ts": edit.approved_at or edit.proposed_at,
            "kind": "edit",
            "color": "green",
            "obj": edit,
            "who": edit.proposed_by,
        })

    for trajectory in LlmTrajectory.objects.filter(
        history=history, edit__isnull=True
    ).select_related("workflow", "model"):
        timeline.append({
            "ts": trajectory.created_at,
            "kind": "orphan_trajectory",
            "color": "green",
            "obj": trajectory,
            "who": None,
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
            "source_type_choices": GameSource.SourceType.choices,
            "proposed_edit_status": GameEdit.EditStatus.PROPOSED,
            "edit_pipelines": EditPipeline.objects.order_by("id"),
        },
    )


def history_comment_add(request, history_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    history = get_object_or_404(GameHistory, pk=history_id)
    text = request.POST.get("text", "").strip()
    if not text:
        messages.error(request, "Комментарий не может быть пустым.")
        return redirect("curation_history_detail", history_id=history.pk)

    GameHistoryComment.objects.create(
        history=history,
        user=request.user,
        type=GameHistoryComment.CommentType.MODS_COMMENT,
        text=text,
        creation_time=now(),
    )
    messages.success(request, "Комментарий добавлен.")
    return redirect("curation_history_detail", history_id=history.pk)


def history_run_edit(request, history_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    history = get_object_or_404(GameHistory, pk=history_id)
    if history.state == GameHistory.State.ABANDONED:
        messages.error(request, "Заброшенную историю нельзя обрабатывать.")
        return redirect("curation_history_detail", history_id=history.pk)
    pipeline = _pipeline_from_post(request.POST)
    edit_sources.delay(
        history_id=history.pk, pipeline_id=pipeline.pk, force=True
    )
    messages.success(request, "Задание на обработку истории запущено.")
    return redirect("curation_history_detail", history_id=history.pk)


def edit_diff(request, edit_id):
    edit = get_object_or_404(
        GameEdit.objects.select_related(
            "history__game", "proposed_by", "approver"
        ).prefetch_related(
            Prefetch(
                "llmtrajectory_set",
                queryset=LlmTrajectory.objects.select_related(
                    "workflow", "model"
                ).order_by("created_at", "pk"),
                to_attr="llm_trajectories",
            )
        ),
        pk=edit_id,
    )
    history = edit.history
    before = _served_canonical(history)
    edit.display_passes = _display_passes(edit.passes)

    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"rollback", "clone"}:
            with transaction.atomic():
                edit = GameEdit.objects.select_for_update().get(pk=edit.pk)
                edit = GameEdit.objects.select_related("history__game").get(
                    pk=edit.pk
                )
                try:
                    new_edit = _propose_from_settled_edit(
                        edit, request.user, request.POST
                    )
                except ValueError as e:
                    return HttpResponseBadRequest(str(e))
            return redirect("curation_edit_diff", edit_id=new_edit.pk)

        if action not in {"accept", "reject"}:
            return HttpResponseBadRequest("Unknown edit action.")
        if edit.status != GameEdit.EditStatus.PROPOSED:
            return HttpResponseBadRequest(
                "Only proposed edits can be settled."
            )
        with transaction.atomic():
            edit = GameEdit.objects.select_for_update().get(pk=edit.pk)
            edit = GameEdit.objects.select_related("history__game").get(
                pk=edit.pk
            )
            if edit.status != GameEdit.EditStatus.PROPOSED:
                return HttpResponseBadRequest(
                    "Only proposed edits can be settled."
                )
            history = edit.history
            before = _served_canonical(history)
            if action == "accept":
                _update_auto_accept(history, request)
                _accept_edit(edit, history, before, request.user)
            else:
                _reject_edit(edit, history, before, request.user)
        return _redirect_after_edit(request.POST.get("next"), edit, history)

    return render(
        request,
        "curation/edit_diff.html",
        {
            "edit": edit,
            "game": history.game,
            "history": history,
            "show_actions": edit.status == GameEdit.EditStatus.PROPOSED,
            "settled_action": _settled_edit_action(edit, history),
            "show_auto_accept": (
                history.auto_updates != GameHistory.AutoUpdate.REJECT
            ),
            "auto_accept_checked": (
                history.auto_updates == GameHistory.AutoUpdate.ACCEPT
            ),
            "rows": build_diff(
                edit.previous_canonical_text
                if edit.previous_canonical_text is not None
                else before,
                edit.canonical_text,
            ),
        },
    )


EDIT_FIELD_LABELS = {
    "title": "название",
    "release_date": "дата релиза",
    "authors": "авторы",
    "links": "ссылки",
    "tags": "свойства",
    "description": "описания",
    "sources": "источники",
}


def _settled_edit_action(edit, history):
    if edit.status == GameEdit.EditStatus.APPLIED:
        if edit.previous_canonical_text is None:
            return None
        action = "rollback"
        button = "откатить"
        title = "Откатить правку"
        target = parse(edit.previous_canonical_text)
    elif edit.status == GameEdit.EditStatus.REJECTED:
        action = "clone"
        button = "применить эту правку"
        title = "Применить эту правку"
        target = parse(edit.canonical_text)
    else:
        return None

    base = _served_gameinfo(history)
    changed = _changed_edit_fields(base, target)
    return {
        "action": action,
        "button": button,
        "title": title,
        "fields": [
            {"name": name, "label": label, "changed": name in changed}
            for name, label in EDIT_FIELD_LABELS.items()
        ],
    }


def _propose_from_settled_edit(edit, user, post):
    history = edit.history
    base = _served_gameinfo(history)
    if edit.status == GameEdit.EditStatus.APPLIED:
        if post.get("action") != "rollback":
            raise ValueError("Applied edits can only be rolled back.")
        if edit.previous_canonical_text is None:
            raise ValueError("This edit cannot be rolled back.")
        target = parse(edit.previous_canonical_text)
        source_edit = _previous_applied_edit(edit)
    elif edit.status == GameEdit.EditStatus.REJECTED:
        if post.get("action") != "clone":
            raise ValueError("Rejected edits can only be cloned.")
        target = parse(edit.canonical_text)
        source_edit = edit
    else:
        raise ValueError("Only applied or rejected edits can be reused.")

    changed = _changed_edit_fields(base, target)
    fields = {
        field
        for field in EDIT_FIELD_LABELS
        if post.get(f"include_{field}") == "on" and field in changed
    }
    if not fields:
        raise ValueError("No changed fields selected.")

    info = _mix_gameinfo(base, target, fields)
    new_edit = GameEdit.objects.create(
        history=history,
        proposed_at=now(),
        proposed_by=user,
        origin=GameEdit.Origin.USER_SUGGESTION,
        status=GameEdit.EditStatus.PROPOSED,
        canonical_text=info.to_canonical(),
    )
    if source_edit is not None:
        new_edit.used_sources.set(source_edit.used_sources.all())
    history.state = GameHistory.State.NEEDS_ATTENTION
    history.edit_time = now()
    history.save(update_fields=["state", "edit_time"])
    return new_edit


def _served_gameinfo(history):
    if history.game is None:
        return GameInfo()
    return GameInfo.from_game(history.game)


def _mix_gameinfo(base, target, fields):
    result = copy.deepcopy(base)
    if "title" in fields:
        result.name = target.name
    if "release_date" in fields:
        result.date = target.date
    if "authors" in fields:
        result.personalities = copy.deepcopy(target.personalities)
    if "links" in fields:
        result.urls = copy.deepcopy(target.urls)
    if "tags" in fields:
        result.tags = copy.deepcopy(target.tags)
    if "description" in fields:
        result.description = target.description
    if "sources" in fields:
        result.attributions = copy.deepcopy(target.attributions)
    return result


def _changed_edit_fields(base, target):
    changed = set()
    if base.name != target.name:
        changed.add("title")
    if base.date != target.date:
        changed.add("release_date")
    if base.personalities != target.personalities:
        changed.add("authors")
    if base.urls != target.urls:
        changed.add("links")
    if base.tags != target.tags:
        changed.add("tags")
    if base.description != target.description:
        changed.add("description")
    if base.attributions != target.attributions:
        changed.add("sources")
    return changed


def _previous_applied_edit(edit):
    previous = None
    for candidate in edit.history.gameedit_set.filter(
        status=GameEdit.EditStatus.APPLIED
    ).order_by("approved_at", "proposed_at", "id"):
        if candidate.pk == edit.pk:
            return previous
        previous = candidate
    return previous


def _redirect_after_edit(next_page, edit, history):
    if next_page == "edit_game" and history.game_id:
        return redirect("edit_game", game_id=history.game_id)
    if next_page == "game" and history.game_id:
        return redirect("show_game", game_id=history.game_id)
    if next_page == "history":
        return redirect("curation_history_detail", history_id=history.pk)
    if next_page == "stay":
        return redirect("curation_edit_diff", edit_id=edit.pk)
    return redirect("curation_history_list")


def _served_canonical(history):
    if history.game is None:
        return ""
    return GameInfo.from_game(history.game).to_canonical()


def _update_auto_accept(history, request):
    if history.auto_updates == GameHistory.AutoUpdate.REJECT:
        return
    new = (
        GameHistory.AutoUpdate.ACCEPT
        if request.POST.get("auto_accept") == "on"
        else GameHistory.AutoUpdate.PROPOSE
    )
    if history.auto_updates == new:
        return
    GameHistoryAuditLog.record_change(
        history,
        request.user,
        GameHistoryAuditLog.AuditField.AUTO_UPDATES,
        history.auto_updates,
        new,
    )
    history.auto_updates = new


def _accept_edit(edit, history, before, user):
    info = parse(edit.canonical_text)
    created_game = history.game is None
    game, after = info.save(history.game)
    if created_game:
        history.game = game
        game.added_by = edit.proposed_by
        game.save(update_fields=["added_by"])
    edit.status = GameEdit.EditStatus.APPLIED
    edit.approved_at = now()
    edit.approver = user
    edit.previous_canonical_text = before
    edit.canonical_text = after
    edit.save(
        update_fields=[
            "status",
            "approved_at",
            "approver",
            "previous_canonical_text",
            "canonical_text",
        ]
    )
    history.state = GameHistory.State.SETTLED
    old_note = history.note
    history.note = None
    GameHistoryAuditLog.record_note_change(
        history, user, old_note, history.note
    )
    history.edit_time = now()
    fields = ["auto_updates", "state", "note", "edit_time"]
    if created_game:
        fields.append("game")
    history.save(update_fields=fields)
    if created_game:
        PostNewGameToDiscord(game.id)


def _reject_edit(edit, history, before, user):
    edit.status = GameEdit.EditStatus.REJECTED
    edit.approved_at = now()
    edit.approver = user
    edit.previous_canonical_text = before
    edit.save(
        update_fields=[
            "status",
            "approved_at",
            "approver",
            "previous_canonical_text",
        ]
    )
    history.state = GameHistory.State.SETTLED
    old_note = history.note
    history.note = None
    GameHistoryAuditLog.record_note_change(
        history, user, old_note, history.note
    )
    history.edit_time = now()
    history.save(update_fields=["state", "note", "edit_time"])


def history_edit(request, history_id):
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
                if field == "state" and value == GameHistory.State.SETTLED:
                    old_note = history.note
                    history.note = None
                    GameHistoryAuditLog.record_note_change(
                        history, request.user, old_note, history.note
                    )
                changed = True
        if changed:
            history.edit_time = now()
            history.save()

    return redirect("curation_history_detail", history_id=history.pk)


def history_merge(request, history_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    history = get_object_or_404(
        GameHistory.objects.select_related("game"), pk=history_id
    )
    if history.game is None:
        messages.error(request, "У этой истории нет игры для объединения.")
        return redirect("curation_history_detail", history_id=history.pk)

    source_game_id = _positive_int(
        request.POST.get("source_game_id"), default=None
    )
    if source_game_id is None:
        messages.error(request, "Укажите id игры, которую нужно присоединить.")
        return redirect("curation_history_detail", history_id=history.pk)

    source_game = get_object_or_404(Game, pk=source_game_id)
    remap_contests = request.POST.get("remap_contests") == "on"
    usage = contest_related_usage(source_game)
    if usage and not remap_contests:
        related = ", ".join(f"{item.label}: {item.count}" for item in usage)
        messages.error(
            request,
            "У присоединяемой игры есть конкурсные ссылки. "
            f"Подтвердите переназначение чекбоксом: {related}.",
        )
        return redirect("curation_history_detail", history_id=history.pk)

    try:
        merge_game_into_history(
            target_history=history,
            source_game=source_game,
            actor=request.user,
            remap_contests=remap_contests,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Игры объединены.")
    return redirect("curation_history_detail", history_id=history.pk)


def history_reconcile(request, history_id):
    history = get_object_or_404(
        GameHistory.objects.select_related("game"), pk=history_id
    )
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode() or "{}")
            target = save_reconcile_payload(data, request.user)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        messages.success(request, "Игры сверены.")
        return JsonResponse({
            "redirect": reverse("curation_history_detail", args=[target.pk])
        })

    return render(
        request,
        "curation/history_reconcile.html",
        {
            "history": history,
            "payload": initial_payload(history),
        },
    )


def reconcile_game_json(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    return JsonResponse(column_for_game(game))
