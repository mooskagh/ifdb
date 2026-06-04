from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0017_llmmodel_updated_at"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="llmworkflow",
            name="allowed_tools",
        ),
        migrations.AddField(
            model_name="llmworkflow",
            name="runner_params",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="Runner parameters"
            ),
        ),
    ]
