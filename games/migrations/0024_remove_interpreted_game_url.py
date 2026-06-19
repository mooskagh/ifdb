from django.db import migrations


def delete_play_in_interpreter_category(apps, schema_editor):
    GameURLCategory = apps.get_model("games", "GameURLCategory")
    GameURLCategory.objects.filter(symbolic_id="play_in_interpreter").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0023_alter_game_id_alter_gameauthor_id_and_more"),
    ]

    operations = [
        migrations.RunPython(
            delete_play_in_interpreter_category, migrations.RunPython.noop
        ),
        migrations.DeleteModel(
            name="InterpretedGameUrl",
        ),
    ]
