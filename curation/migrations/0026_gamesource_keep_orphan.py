from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0025_abandoned_history_game_merged_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="gamesource",
            name="keep_orphan",
            field=models.BooleanField(
                default=False, verbose_name="Keep orphan"
            ),
        ),
    ]
