import re
from typing import Any

from django.core.management.base import (
    BaseCommand,
    CommandError,
    CommandParser,
)

from play.blueprint import BlueprintInfo, discover_blueprints
from play.models import Playable
from play.tasks import generate_playable


def version_sort_key(v: str) -> tuple[tuple[int, int | str], ...]:
    if not v:
        return ()
    parts: list[tuple[int, int | str]] = []
    for piece in re.split(r"[-.]", v):
        if not piece:
            continue
        if piece.isdigit():
            parts.append((0, int(piece)))
        else:
            parts.append((1, piece))
    return tuple(parts)


def is_version_newer(
    latest_version: str,
    current_version: str,
    available_versions: list[str] | None = None,
) -> bool:
    if not current_version:
        return bool(latest_version)
    if latest_version == current_version:
        return False
    if (
        available_versions
        and current_version in available_versions
        and latest_version in available_versions
    ):
        return available_versions.index(
            latest_version
        ) > available_versions.index(current_version)
    return version_sort_key(latest_version) > version_sort_key(current_version)


def get_blueprint_map() -> dict[str, BlueprintInfo]:
    return {info.name: info for info in discover_blueprints()}


def resolve_player_slug(
    player_input: str, blueprints: dict[str, BlueprintInfo]
) -> str:
    cleaned = player_input.strip().lower()
    for slug, info in blueprints.items():
        if (
            slug.lower() == cleaned
            or info.blueprint.get_spec().name.lower() == cleaned
        ):
            return slug
    available = ", ".join(sorted(blueprints.keys()))
    raise CommandError(
        f"Unknown player type '{player_input}'. "
        f"Available player types: {available}"
    )


class Command(BaseCommand):
    help = "Regenerate generated playable games."
    suppressed_base_arguments = {"--version"}

    def add_base_argument(
        self, parser: CommandParser, *args: Any, **kwargs: Any
    ) -> None:
        for arg in args:
            if arg in self.suppressed_base_arguments:
                return
        super().add_base_argument(parser, *args, **kwargs)

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-p",
            "--player",
            "--player-type",
            "--template",
            dest="player_type",
            help=(
                "Filter by player type (blueprint slug or display name, e.g. "
                "'parchment', 'qspider'). Defaults to ALL players."
            ),
        )
        parser.add_argument(
            "-V",
            "--version",
            "--template-version",
            "--playable-version",
            dest="version",
            help="Filter by playable template version.",
        )
        parser.add_argument(
            "-u",
            "--update-outdated",
            "--outdated",
            dest="update_outdated",
            action="store_true",
            help=(
                "Only update playables where the latest version is newer than "
                "the playable's current version."
            ),
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            action="store_true",
            help="Show what would be regenerated without performing changes.",
        )
        parser.add_argument(
            "--async",
            dest="run_async",
            action="store_true",
            help="Enqueue regeneration via Celery instead of synchronously.",
        )
        parser.add_argument(
            "--include-building",
            action="store_true",
            help="Include playables that are currently in BUILDING state.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        player_type: str | None = options.get("player_type")
        version_filter: str | None = options.get("version")
        update_outdated: bool = options.get("update_outdated", False)
        dry_run: bool = options.get("dry_run", False)
        run_async: bool = options.get("run_async", False)
        include_building: bool = options.get("include_building", False)

        blueprints = get_blueprint_map()

        filter_template: str | None = None
        if player_type:
            filter_template = resolve_player_slug(player_type, blueprints)

        qs = Playable.objects.select_related("game", "game_url__url").order_by(
            "pk"
        )
        if filter_template:
            qs = qs.filter(template=filter_template)
        if version_filter:
            qs = qs.filter(template_version=version_filter)

        candidates: list[tuple[Playable, str]] = []
        skipped_building = 0
        skipped_no_blueprint = 0
        skipped_up_to_date = 0

        for playable in qs:
            if (
                playable.state == Playable.State.BUILDING
                and not include_building
            ):
                skipped_building += 1
                continue

            blueprint_info = blueprints.get(playable.template)
            if not blueprint_info:
                self.stderr.write(
                    self.style.WARNING(
                        f"Skipping playable #{playable.pk}: "
                        f"unknown template '{playable.template}'"
                    )
                )
                skipped_no_blueprint += 1
                continue

            spec = blueprint_info.blueprint.get_spec()
            latest_version = (
                spec.versions[-1]
                if spec.versions
                else playable.template_version
            )

            is_outdated = (
                is_version_newer(
                    latest_version,
                    playable.template_version,
                    available_versions=spec.versions,
                )
                if spec.versions
                else False
            )

            if update_outdated and not is_outdated:
                skipped_up_to_date += 1
                continue

            target_version = latest_version or playable.template_version
            candidates.append((playable, target_version))

        if not candidates:
            if dry_run:
                self.stdout.write(
                    "Dry run complete: 0 playables to regenerate."
                )
            else:
                self.stdout.write("No playables to regenerate.")
            if skipped_building:
                self.stdout.write(
                    f"Note: {skipped_building} playable(s) skipped in "
                    "BUILDING state (use --include-building to include them)."
                )
            return

        mode_desc = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            f"{mode_desc}Found {len(candidates)} playable(s) to regenerate:"
        )

        for playable, target_version in candidates:
            version_change = (
                f"{playable.template_version} -> {target_version}"
                if playable.template_version != target_version
                else playable.template_version
            )
            title = playable.game.title if playable.game else "Unknown"
            self.stdout.write(
                f"  #{playable.pk}: {title} [{playable.template} "
                f"{version_change}] (state={playable.state})"
            )

        if dry_run:
            self.stdout.write(
                f"Dry run complete: {len(candidates)} playable(s) "
                "would be regenerated."
            )
            return

        succeeded = 0
        failed = 0

        for playable, target_version in candidates:
            if playable.template_version != target_version:
                playable.template_version = target_version
                playable.save(update_fields=["template_version", "updated"])

            title = playable.game.title if playable.game else "Unknown"
            if run_async:
                playable.state = Playable.State.PENDING
                playable.save(update_fields=["state", "updated"])
                generate_playable.delay(playable.pk)
                self.stdout.write(
                    f"Queued #{playable.pk} "
                    f"({title}, {playable.template} v{target_version})"
                )
                succeeded += 1
            else:
                self.stdout.write(
                    f"Regenerating #{playable.pk} "
                    f"({title}, {playable.template} v{target_version})... ",
                    ending="",
                )
                try:
                    generate_playable(playable.pk)
                    self.stdout.write(self.style.SUCCESS("OK"))
                    succeeded += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"FAILED: {e}"))
                    failed += 1

        self.stdout.write(
            f"Regeneration complete: {succeeded} succeeded, {failed} failed."
        )
