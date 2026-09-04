from django.db import migrations


def delete_orphan_game_histories(apps, schema_editor):
    GameHistory = apps.get_model("curation", "GameHistory")
    GameHistory.objects.filter(game__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0029_alter_gamehistoryauditlog_kind"),
        ("games", "0025_game_redirect_to_game_state_and_more"),
    ]

    operations = [
        migrations.RunPython(
            delete_orphan_game_histories, migrations.RunPython.noop
        ),
    ]
