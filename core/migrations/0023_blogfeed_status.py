from django.db import migrations, models

SEED_FEEDS = [
    {
        "feed_id": "ifhub",
        "title": "IF Hub",
        "url": "https://ifhub.club/",
        "rss": "https://ifhub.club/rss/full",
        "show_author": True,
    },
    {
        "feed_id": "ifru",
        "title": "forum.ifiction.ru",
        "url": "https://forum.ifiction.ru/",
        "rss": "https://forum.ifiction.ru/extern.php?action=active&type=rss",
        "show_author": True,
    },
    {
        "feed_id": "urq",
        "title": "urq.borda.ru",
        "url": "http://urq.borda.ru/",
        "rss": "http://urq.borda.ru/",
        "show_author": True,
    },
    {
        "feed_id": "inst",
        "title": "INSTEAD forum",
        "url": "http://instead-games.ru/forum/",
        "rss": "http://instead-games.ru/forum/index.php?p=/discussions/feed.rss",
        "show_author": True,
    },
]


def seed_hardcoded_feeds(apps, schema_editor):
    BlogFeed = apps.get_model("core", "BlogFeed")
    for feed in SEED_FEEDS:
        BlogFeed.objects.update_or_create(
            feed_id=feed["feed_id"],
            defaults={**feed, "is_enabled": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_hourly_fetch_feeds_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="blogfeed",
            name="is_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="blogfeed",
            name="last_attempt",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="blogfeed",
            name="last_success",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="blogfeed",
            name="failing_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="blogfeed",
            name="last_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(seed_hardcoded_feeds, migrations.RunPython.noop),
    ]
