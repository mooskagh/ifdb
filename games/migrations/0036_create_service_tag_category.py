from django.db import migrations


def create_service_tag_category(apps, schema_editor):
    GameTagCategory = apps.get_model("games", "GameTagCategory")
    GameTagCategory.objects.update_or_create(
        symbolic_id="service",
        defaults={
            "name": "Служебный",
            "allow_new_tags": True,
            "is_internal": True,
            "order": 100,
        },
    )


def remove_service_tag_category(apps, schema_editor):
    GameTagCategory = apps.get_model("games", "GameTagCategory")
    GameTagCategory.objects.filter(symbolic_id="service").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0035_gametagcategory_is_internal"),
    ]

    operations = [
        migrations.RunPython(
            create_service_tag_category, remove_service_tag_category
        ),
    ]
