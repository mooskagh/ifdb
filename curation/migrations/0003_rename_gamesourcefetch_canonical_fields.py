from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0002_alter_gamesource_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="gamesourcefetch",
            old_name="filtered_content",
            new_name="canonical_text",
        ),
        migrations.RenameField(
            model_name="gamesourcefetch",
            old_name="filtered_content_hash",
            new_name="canonical_text_hash",
        ),
        migrations.AlterField(
            model_name="gamesourcefetch",
            name="canonical_text",
            field=models.TextField(verbose_name="Canonical text"),
        ),
        migrations.AlterField(
            model_name="gamesourcefetch",
            name="canonical_text_hash",
            field=models.CharField(
                db_index=True,
                max_length=64,
                verbose_name="Canonical text hash",
            ),
        ),
    ]
