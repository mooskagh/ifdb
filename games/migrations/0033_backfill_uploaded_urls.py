import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.db import migrations


def backfill_uploaded_urls(apps, schema_editor):
    URL = apps.get_model("games", "URL")
    uploads_fs = settings.UPLOADS_FS
    backups_fs = settings.BACKUPS_FS

    for u in URL.objects.filter(local_filename__isnull=True).iterator():
        if not u.original_url:
            continue
        parsed = urlparse(u.original_url)
        path = parsed.path
        if "/f/uploads/" in path:
            rel = unquote(path.split("/f/uploads/", 1)[1]).lstrip("/")
            if rel and uploads_fs.exists(rel):
                u.local_filename = rel
                u.local_url = uploads_fs.url(rel)
                u.is_uploaded = True
                u.file_size = uploads_fs.size(rel)
                u.ok_to_clone = False
                if not u.original_filename:
                    u.original_filename = Path(rel).name
                if not u.content_type:
                    ctype, _ = mimetypes.guess_type(rel)
                    if ctype:
                        u.content_type = ctype
                u.save(
                    update_fields=[
                        "local_filename",
                        "local_url",
                        "is_uploaded",
                        "file_size",
                        "ok_to_clone",
                        "original_filename",
                        "content_type",
                    ]
                )
        elif "/f/backups/" in path:
            rel = unquote(path.split("/f/backups/", 1)[1]).lstrip("/")
            if rel and backups_fs.exists(rel):
                u.local_filename = rel
                u.local_url = backups_fs.url(rel)
                u.is_uploaded = False
                u.file_size = backups_fs.size(rel)
                if not u.original_filename:
                    u.original_filename = Path(rel).name
                if not u.content_type:
                    ctype, _ = mimetypes.guess_type(rel)
                    if ctype:
                        u.content_type = ctype
                u.save(
                    update_fields=[
                        "local_filename",
                        "local_url",
                        "is_uploaded",
                        "file_size",
                        "original_filename",
                        "content_type",
                    ]
                )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0032_delete_admin_tag_category"),
    ]

    operations = [
        migrations.RunPython(
            backfill_uploaded_urls, reverse_code=migrations.RunPython.noop
        ),
    ]
