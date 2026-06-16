from decimal import Decimal

from django.db import migrations, models

DEDUPLICATE_PROMPT = """\
Your task is to produce one final description by removing duplicate or \
near-duplicate imported copies.

Descriptions may be separated by "---". If two sections contain the same \
information, keep only one copy. Do not keep repeated duplicate sections.

Do NOT change formatting inside the kept text, do NOT fix spelling mistakes, \
and do NOT delete unique content. Only remove duplicated content.

You can do that in multiple steps. After each successful edit tool call, \
inspect the returned result, which is a snippet around the edit location.

Deduplicate whole imported copies or substantial repeated blocks only.
Do not remove translated dialogue, quotes, examples, or repeated phrases \
inside a single coherent description. If a duplicate section has unique tail \
lines, preserve those unique lines.

Once you are happy with the result, call commit_edited_result.
If the initial input already contains no large repeated blocks, call \
no_duplicates_found without editing.

If you feel you messed up, call abort. If you are not sure, call \
request_human_review.

If you are lost at what's expected, or have a suggestion for better tool API, \
use "complain" function.

<text>
{{ current_content_text }}
</text>
"""

STATUS_REVIEW_PROMPT = """\
Your task is to confirm that this edit does not delete any useful \
information. This is an edit of the description of an interactive fiction \
game in online database.

Removing formatting, non-description information like improperly cleaned up \
tags, is fine. Removing empty document sections is fine.

<original>
{{ served_content_text }}
</original>

<edited>
{{ current_content_text }}
</edited>

<diff>
{{ content_text_diff }}
</diff>
"""

IMPORT_PIPELINE_PASSES = [
    {"name": "merge_sources"},
    {"name": "enrich"},
    {"name": "cleanup_text"},
    {"name": "dedup_personality_aliases"},
    {"name": "llm_workflow", "workflow": "deduplicate"},
    {"name": "llm_workflow", "workflow": "automod"},
]


def seed_defaults(apps, schema_editor):
    LLMModel = apps.get_model("curation", "LLMModel")
    LlmWorkflow = apps.get_model("curation", "LlmWorkflow")
    EditPipeline = apps.get_model("curation", "EditPipeline")

    model, _ = LLMModel.objects.update_or_create(
        name="google/gemma-4-26b-a4b-it",
        defaults={
            "context_length": 262144,
            "input_cost": Decimal("0.0600"),
            "cached_input_cost": Decimal("0.0000"),
            "cache_write_cost": Decimal("0.0000"),
            "output_cost": Decimal("0.3300"),
        },
    )
    LlmWorkflow.objects.update_or_create(
        name="deduplicate",
        defaults={
            "runner": "content_editor",
            "prompt_template": DEDUPLICATE_PROMPT,
            "model": model,
            "runner_params": {},
        },
    )
    LlmWorkflow.objects.update_or_create(
        name="automod",
        defaults={
            "runner": "status_review",
            "prompt_template": STATUS_REVIEW_PROMPT,
            "model": model,
            "runner_params": {},
        },
    )
    EditPipeline.objects.update_or_create(
        name="Импорт",
        defaults={"passes": IMPORT_PIPELINE_PASSES},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0019_fetch_sources_task"),
    ]

    operations = [
        migrations.CreateModel(
            name="EditPipeline",
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
                        max_length=100, unique=True, verbose_name="Name"
                    ),
                ),
                (
                    "passes",
                    models.JSONField(default=list, verbose_name="Passes"),
                ),
            ],
            options={"default_permissions": ()},
        ),
        migrations.RunPython(seed_defaults, migrations.RunPython.noop),
    ]
