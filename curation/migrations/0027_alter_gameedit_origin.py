from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0026_gamesource_keep_orphan"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gameedit",
            name="origin",
            field=models.CharField(
                choices=[
                    ("AUTO_IMPORT", _("Automatic import")),
                    ("MANUAL_EDIT", _("Manual edit")),
                    ("USER_SUGGESTION", _("User suggestion")),
                    ("ROLLBACK", _("Rollback")),
                    ("REAPPLICATION", _("Reapplication")),
                ],
                max_length=16,
                verbose_name=_("Origin"),
            ),
        ),
    ]
