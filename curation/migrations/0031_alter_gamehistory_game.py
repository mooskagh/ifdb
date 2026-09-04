import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0030_delete_orphan_gamehistory"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gamehistory",
            name="game",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE, to="games.game"
            ),
        ),
    ]
