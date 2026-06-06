from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0021_gamehistory_processing_lease"),
    ]

    operations = [
        migrations.RenameField(
            model_name="gamehistory",
            old_name="attention_reason",
            new_name="note",
        ),
        migrations.AlterField(
            model_name="gamehistory",
            name="note",
            field=models.TextField(blank=True, null=True, verbose_name="Note"),
        ),
    ]
