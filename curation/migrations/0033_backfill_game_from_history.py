from django.db import migrations


def backfill_game_from_history(apps, schema_editor):
    GameHistory = apps.get_model("curation", "GameHistory")
    history_to_game = dict(GameHistory.objects.values_list("id", "game_id"))
    for model_name in [
        "GameEdit",
        "GameSource",
        "GameHistoryComment",
        "GameHistoryAuditLog",
        "LlmTrajectory",
    ]:
        Model = apps.get_model("curation", model_name)
        for obj in Model.objects.filter(history__isnull=False).only(
            "id", "history_id"
        ):
            game_id = history_to_game.get(obj.history_id)
            if game_id:
                Model.objects.filter(pk=obj.pk).update(game_id=game_id)


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0032_add_game_to_curation_models"),
    ]

    operations = [
        migrations.RunPython(
            backfill_game_from_history,
            migrations.RunPython.noop,
        ),
    ]
