from django.db import migrations

from core.crawler import decode_mojibake_filename


def fix_mojibake_filenames(apps, schema_editor):
    URLFetch = apps.get_model("games", "URLFetch")
    for fetch in URLFetch.objects.filter(original_filename__isnull=False):
        fixed = decode_mojibake_filename(fetch.original_filename)
        if fixed and fixed != fetch.original_filename:
            fetch.original_filename = fixed[:255]
            fetch.save(update_fields=["original_filename"])


class Migration(migrations.Migration):
    dependencies = [
        (
            "games",
            "0042_remove_url_content_type_remove_url_file_size_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            fix_mojibake_filenames, migrations.RunPython.noop
        ),
    ]
