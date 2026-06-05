from decimal import Decimal

from django.db import migrations, models

DEDUPLICATE_PROMPT = "\n".join([
    "Your task is to produce one final description by removing duplicate or "
    "near-duplicate imported copies.",
    "",
    'Descriptions may be separated by "---". If two sections contain the '
    "same information, keep only one copy. Do not keep repeated duplicate "
    "sections.",
    "",
    "Do NOT change formatting inside the kept text, do NOT fix spelling "
    "mistakes, and do NOT delete unique content. Only remove duplicated "
    "content.",
    "",
    "You can do that in multiple steps. After each successful edit tool call, "
    "inspect the returned result, which is a snippet around the edit "
    "location.",
    "",
    "Once you are happy with the result, call finish with resolution "
    '"commit".',
    "If the initial input already contains a single non-duplicated "
    'description, call finish with resolution "commit" without editing.',
    "",
    'If you feel you messed up, call finish with resolution "abort". If '
    'you are not sure, use resolution "request_human_review".',
    "",
    "If you are lost at what's expected, or have a suggestion for better tool "
    'API, use "complain" function.',
    "",
    "<text>",
    "{{ current_content_text }}",
    "</text>",
])


IMPORT_PIPELINE_PASSES = [
    {"name": "merge_sources"},
    {"name": "enrich"},
    {"name": "cleanup_text"},
    {"name": "dedup_personality_aliases"},
    {"name": "llm_workflow", "workflow": "deduplicate"},
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
