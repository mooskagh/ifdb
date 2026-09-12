import copy
import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from curation.edit import (
    PASS_REGISTRY,
    _build_state,
    _resolve_pipeline,
    normalize_pass_specs,
)
from curation.models import (
    EditPipeline,
    GameCuration,
    GameHistoryAuditLog,
)
from curation.overrides import apply_and_prune_overrides
from games.gameinfo import _split_front_matter
from games.models import Game

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Reconcile include/exclude overrides with game sources. Enqueues "
        "games for update if front matter changes, or prunes satisfied "
        "overrides if not."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate execution without modifying the database.",
        )
        parser.add_argument(
            "--game",
            type=int,
            help="Process only a specific game PK.",
        )
        parser.add_argument(
            "--pipeline",
            help=(
                "Edit pipeline PK or name "
                "(defaults to first configured pipeline)."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of games to process.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print detailed progress for each game.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        game_id: int | None = options.get("game")
        pipeline_arg: str | None = options.get("pipeline")
        limit: int | None = options.get("limit")
        verbose: bool = options["verbose"] or options["verbosity"] > 1

        pipeline = self._get_pipeline(pipeline_arg)
        pass_specs = [
            spec
            for spec in normalize_pass_specs(pipeline.passes)
            if spec.name != "llm_workflow"
        ]

        games_qs = (
            Game.objects
            .order_by("pk")
            .select_related("curation")
            .exclude(state=Game.State.ABANDONED)
            .exclude(curation__state=GameCuration.State.ABANDONED)
        )
        if game_id is not None:
            games_qs = games_qs.filter(pk=game_id)

        self.stdout.write(
            f"Starting reconcile_overrides using pipeline '{pipeline.name}' "
            f"({'DRY RUN' if dry_run else 'LIVE'})..."
        )

        total_inspected = 0
        enqueued_count = 0
        already_scheduled_count = 0
        pruned_count = 0
        unchanged_count = 0
        no_sources_count = 0
        error_count = 0

        for game in games_qs.iterator(chunk_size=500):
            if limit is not None and total_inspected >= limit:
                break

            curation: GameCuration | None = getattr(game, "curation", None)
            if curation is None:
                continue

            total_inspected += 1

            try:
                state = _build_state(curation)
                usable_sources = [s for s in state.sources if s.canonical_text]
                if not usable_sources:
                    no_sources_count += 1
                    if verbose:
                        self.stdout.write(
                            f"Game #{game.pk} ('{game.title}'): "
                            "no usable sources, skipped."
                        )
                    continue

                for spec in pass_specs:
                    PASS_REGISTRY[spec.name].apply(state, spec.params)
                    state.current.canonicalize()

                curation_copy = copy.deepcopy(curation)
                state.current, overrides_changed = apply_and_prune_overrides(
                    curation_copy, state.current
                )
                state.current.canonicalize()

                fm_served, _ = _split_front_matter(state.served.to_canonical())
                fm_current, _ = _split_front_matter(
                    state.current.to_canonical()
                )

                if fm_served != fm_current:
                    if (
                        curation.state
                        != GameCuration.State.SCHEDULED_FOR_UPDATE
                    ):
                        if not dry_run:
                            with transaction.atomic():
                                old_state = curation.state
                                curation.state = (
                                    GameCuration.State.SCHEDULED_FOR_UPDATE
                                )
                                curation.save(update_fields=["state"])
                                GameHistoryAuditLog.record_auto_update_scheduled(
                                    curation.game, old_state, curation.state
                                )
                        enqueued_count += 1
                        if verbose:
                            self.stdout.write(
                                f"Game #{game.pk} ('{game.title}'): "
                                "front matter changed -> enqueued for update."
                            )
                    else:
                        already_scheduled_count += 1
                        if verbose:
                            self.stdout.write(
                                f"Game #{game.pk} ('{game.title}'): "
                                "front matter changed -> already scheduled."
                            )
                else:
                    if (
                        curation.include_overrides
                        != curation_copy.include_overrides
                        or curation.exclude_overrides
                        != curation_copy.exclude_overrides
                    ):
                        if not dry_run:
                            curation.include_overrides = (
                                curation_copy.include_overrides
                            )
                            curation.exclude_overrides = (
                                curation_copy.exclude_overrides
                            )
                            curation.save(
                                update_fields=[
                                    "include_overrides",
                                    "exclude_overrides",
                                ]
                            )
                        pruned_count += 1
                        if verbose:
                            self.stdout.write(
                                f"Game #{game.pk} ('{game.title}'): "
                                "front matter unchanged -> pruned overrides."
                            )
                    else:
                        unchanged_count += 1
                        if verbose:
                            self.stdout.write(
                                f"Game #{game.pk} ('{game.title}'): "
                                "front matter unchanged -> "
                                "overrides unchanged."
                            )

            except Exception:
                error_count += 1
                logger.exception("Error reconciling game #%s", game.pk)
                self.stderr.write(f"Error processing game #{game.pk}")

        self.stdout.write(
            f"Finished reconcile_overrides:\n"
            f"  Inspected:         {total_inspected}\n"
            f"  Enqueued:          {enqueued_count}\n"
            f"  Already scheduled: {already_scheduled_count}\n"
            f"  Overrides pruned:  {pruned_count}\n"
            f"  Unchanged:         {unchanged_count}\n"
            f"  No usable sources: {no_sources_count}\n"
            f"  Errors:            {error_count}"
        )

    def _get_pipeline(self, pipeline_arg: str | None) -> EditPipeline:
        if not pipeline_arg:
            return _resolve_pipeline(None)
        if pipeline_arg.isdigit():
            pipeline = EditPipeline.objects.filter(
                pk=int(pipeline_arg)
            ).first()
        else:
            pipeline = EditPipeline.objects.filter(name=pipeline_arg).first()
        if pipeline is None:
            raise ValueError(f"Pipeline '{pipeline_arg}' not found.")
        return pipeline
