from django.db import migrations, models


def reject_old_proposed_edits(apps, schema_editor):
    GameEdit = apps.get_model("curation", "GameEdit")
    duplicate_history_ids = (
        GameEdit.objects
        .filter(status="PROPOSED")
        .values("history_id")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
        .values_list("history_id", flat=True)
    )

    for history_id in duplicate_history_ids:
        keep_id = (
            GameEdit.objects
            .filter(history_id=history_id, status="PROPOSED")
            .order_by("-proposed_at", "-id")
            .values_list("id", flat=True)
            .first()
        )
        GameEdit.objects.filter(
            history_id=history_id, status="PROPOSED"
        ).exclude(pk=keep_id).update(status="REJECTED")


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0022_rename_gamehistory_attention_reason"),
    ]

    operations = [
        migrations.RunPython(
            reject_old_proposed_edits, migrations.RunPython.noop
        ),
        migrations.AddConstraint(
            model_name="gameedit",
            constraint=models.UniqueConstraint(
                fields=("history",),
                condition=models.Q(status="PROPOSED"),
                name="curation_gameedit_one_proposed_per_history",
            ),
        ),
    ]
