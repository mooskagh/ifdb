from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("curation", "0008_alter_gamehistoryauditlog_field"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="gameedit",
            name="parent_edit",
        ),
        migrations.AddField(
            model_name="gameedit",
            name="passes",
            field=models.JSONField(default=list, verbose_name="Passes"),
        ),
    ]
