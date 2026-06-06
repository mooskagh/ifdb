from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0023_one_proposed_edit_per_history"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gamehistoryauditlog",
            name="field",
            field=models.CharField(
                blank=True,
                choices=[
                    ("AUTO_UPDATES", "Auto-update policy"),
                    ("STATE", "State"),
                    ("NOTE", "Note"),
                ],
                max_length=32,
                null=True,
                verbose_name="Field",
            ),
        ),
    ]
