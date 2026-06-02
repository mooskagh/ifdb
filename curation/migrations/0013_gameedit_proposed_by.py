import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("curation", "0012_remove_gamehistory_priority"),
    ]

    operations = [
        migrations.AddField(
            model_name="gameedit",
            name="proposed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="proposed_game_edits",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
