from django.db import migrations


def backfill_gamecuration_from_history(apps, schema_editor):
    GameHistory = apps.get_model("curation", "GameHistory")
    GameCuration = apps.get_model("curation", "GameCuration")
    curations = [
        GameCuration(
            game_id=h.game_id,
            auto_updates=h.auto_updates,
            state=h.state,
            note=h.note,
            processing_started_at=h.processing_started_at,
            processing_task_id=h.processing_task_id,
        )
        for h in GameHistory.objects.filter(game_id__isnull=False)
    ]
    GameCuration.objects.bulk_create(curations, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0039_create_gamecuration"),
    ]

    operations = [
        migrations.RunPython(
            backfill_gamecuration_from_history,
            migrations.RunPython.noop,
        ),
    ]
