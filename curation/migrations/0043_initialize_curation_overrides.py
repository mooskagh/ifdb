from django.db import migrations


def initialize_overrides(apps, schema_editor):
    GameCuration = apps.get_model("curation", "GameCuration")
    GameSource = apps.get_model("curation", "GameSource")

    from curation.overrides import build_initial_overrides
    from games.gameinfo import parse

    rich_game_ids = set(
        GameSource.objects.filter(
            type__in=["IFWIKI", "QUESTBOOK"], game_id__isnull=False
        ).values_list("game_id", flat=True)
    )

    curations_to_update = []
    for curation in (
        GameCuration.objects
        .select_related("game__published_revision")
        .all()
        .iterator(chunk_size=500)
    ):
        game = getattr(curation, "game", None)
        if not game or not game.published_revision_id:
            continue
        rev = game.published_revision
        if not rev or not rev.canonical_text:
            continue
        is_rich = game.id in rich_game_ids
        info = parse(rev.canonical_text)
        curation.include_overrides = build_initial_overrides(
            info, is_rich_source=is_rich
        )
        curation.exclude_overrides = {}
        curations_to_update.append(curation)
        if len(curations_to_update) >= 500:
            GameCuration.objects.bulk_update(
                curations_to_update, ["include_overrides", "exclude_overrides"]
            )
            curations_to_update.clear()

    if curations_to_update:
        GameCuration.objects.bulk_update(
            curations_to_update, ["include_overrides", "exclude_overrides"]
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0042_gamecuration_exclude_overrides_and_more"),
    ]

    operations = [
        migrations.RunPython(initialize_overrides, noop_reverse),
    ]
