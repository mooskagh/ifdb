from django.db import migrations

PROMPT = (
    "Your task is to apply the semantic change from `sources_old` to "
    "`sources_new` to `current`.\n\n"
    "`sources_diff` is evidence of what changed in the sources. It is "
    "**not** a patch to copy into `current`.\n\n"
    "Only edit `current` when a specific change in `sources_diff` requires "
    "it.\n\n"
    "Rules:\n\n"
    "- Apply only information that was added, removed, or changed by the "
    "diff.\n"
    "- Treat added source text as candidate information, not text to paste.\n"
    "- Before adding anything, check whether the same information already "
    "exists anywhere in `current`. A paraphrase or translation counts as "
    "the same information. If it already exists, do nothing.\n"
    "- Never paste a whole added source block and clean up duplicates "
    "afterward. Add only the genuinely new information, directly in its "
    "appropriate place.\n"
    "- Do not add empty headings, separators, source-specific structure, "
    "or formatting unless they carry a meaningful change that must be "
    "represented in `current`.\n"
    "- If information is unchanged between `sources_old` and `sources_new`, "
    "do not modify the corresponding text in `current`, even if it looks "
    "wrong, malformed, misspelled, duplicated, or different from the "
    "sources.\n"
    "- Do not clean up, rewrite, normalize, reformat, or improve unrelated "
    "text.\n"
    "- If the diff replaces information, change only the corresponding "
    "information in `current`.\n"
    "- If the diff removes information, remove the corresponding information "
    "from `current` and finish with `request_human_review`.\n"
    "- If you cannot confidently determine whether an added item is "
    "genuinely new, or cannot identify the corresponding text to change, "
    "do not guess; finish with `request_human_review`.\n\n"
    "Every edit rationale must name the specific source-diff change that "
    "justifies the edit. If no specific diff change justifies it, do not "
    "make the edit.\n\n"
    "Prefer the smallest possible edit. Do not restructure `current` to "
    "resemble `sources_new`.\n\n"
    "When all applicable changes are handled, finish with `commit`. "
    "A commit with no edits is valid.\n\n"
    "If you made an unjustified or incorrect edit, finish with `abort`.\n\n"
    "Prefer Russian for rationale/explanation.\n\n"
    "{{ numbered_files }}\n"
)


def seed_workflow(apps, schema_editor):
    LLMModel = apps.get_model("curation", "LLMModel")
    LlmWorkflow = apps.get_model("curation", "LlmWorkflow")
    model = LLMModel.objects.get(name="google/gemma-4-26b-a4b-it")
    LlmWorkflow.objects.update_or_create(
        name="update_description",
        defaults={
            "runner": "update_description",
            "prompt_template": PROMPT,
            "model": model,
            "runner_params": {},
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("curation", "0045_alter_gamesource_type_and_more"),
        ("games", "0037_gamerevision_source_snapshots"),
    ]

    operations = [
        migrations.RunPython(seed_workflow, migrations.RunPython.noop)
    ]
