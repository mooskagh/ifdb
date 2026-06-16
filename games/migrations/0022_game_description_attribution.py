import re

from django.db import migrations, models

ATTRIBUTION_RE = re.compile(
    r"\n*\s*_\(\s*описание взято с сайта\s+([^)]+?)\s*\)_",
    re.IGNORECASE,
)


def migrate_description_attributions(apps, schema_editor):
    Game = apps.get_model("games", "Game")
    Attribution = apps.get_model("games", "GameDescriptionAttribution")

    for game in Game.objects.exclude(description__isnull=True).iterator():
        names = [
            match.group(1).strip()
            for match in ATTRIBUTION_RE.finditer(game.description)
        ]
        if not names:
            continue

        for name in dict.fromkeys(names):
            attribution, _ = Attribution.objects.get_or_create(name=name)
            game.description_attributions.add(attribution)

        description = ATTRIBUTION_RE.sub("", game.description).strip()
        game.description = description or None
        game.save(update_fields=["description"])


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0021_auto_20190728_1928"),
    ]

    operations = [
        migrations.CreateModel(
            name="GameDescriptionAttribution",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        db_index=True, max_length=255, unique=True
                    ),
                ),
            ],
            options={
                "default_permissions": (),
            },
        ),
        migrations.AddField(
            model_name="game",
            name="description_attributions",
            field=models.ManyToManyField(
                blank=True, to="games.gamedescriptionattribution"
            ),
        ),
        migrations.RunPython(
            migrate_description_attributions, migrations.RunPython.noop
        ),
    ]
