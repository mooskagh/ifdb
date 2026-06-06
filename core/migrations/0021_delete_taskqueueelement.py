from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_remove_document_model"),
    ]

    operations = [
        migrations.DeleteModel(
            name="TaskQueueElement",
        ),
    ]
