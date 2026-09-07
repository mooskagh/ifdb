from django.db import migrations

PLAYABLE_DOMAIN_PROMPT = """\
You are choosing a domain name (subdomain) for an online playable version \
of an interactive fiction game.

Game title: {{ game.title }}
{% if game.description %}\
Game description: {{ game.description|truncatewords:80 }}
{% endif %}

Your goal is to suggest a short, clean, memorable, URL-friendly subdomain \
name (slug) for this game.
The game will be available at: <name>.{{ base_domain }}

Requirements for candidate names:
- Use only lowercase English letters (a-z), digits (0-9), and hyphens (-).
- Must start and end with a letter or digit (no leading or trailing hyphens).
- Do not use consecutive hyphens (no "--").
- Keep it concise (typically 3-20 characters, shorter is better).
- If the game title is in Russian or another language, transliterate or \
translate it concisely into English/Latin characters. Decide what's better \
for non-fluent English speakers: translate simple words, transliterate \
complex words, also consider the "vibe".
- Must be recognizable and relevant to the game.

Examples:
* Августгард: Воспоминания — avgustgard
* Куба — cuba
* Тропой партизана — trail
* Сказка о соломинке — solominka
* Резонанс — resonance
* Ржавая лопата — lopata
* Сделка века — deal
* Башня Парабеда — parabeda
* Ужасы Фарерских островов — farers

You have access to the `suggest_names` tool.
Call `suggest_names` with a list of candidate names in order of preference.
The tool will check each name to determine whether it is already busy \
(in use by another game or reserved) or available.
If all candidate names you suggest are busy, review the tool's feedback \
and call `suggest_names` again with a new list of candidates until an \
available name is found.
"""


def seed_playable_domain_workflow(apps, schema_editor):
    LLMModel = apps.get_model("curation", "LLMModel")
    LlmWorkflow = apps.get_model("curation", "LlmWorkflow")

    model = LLMModel.objects.first()
    if not model:
        raise RuntimeError(
            "No LLMModel found to associate with playable_domain workflow"
        )

    LlmWorkflow.objects.update_or_create(
        name="playable_domain",
        defaults={
            "runner": "playable_domain",
            "prompt_template": PLAYABLE_DOMAIN_PROMPT,
            "model": model,
            "runner_params": {},
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("play", "0005_playable_game_url_playable_state_alter_playable_slug"),
        ("curation", "0020_editpipeline_seed_defaults"),
    ]

    operations = [
        migrations.RunPython(
            seed_playable_domain_workflow, migrations.RunPython.noop
        ),
    ]
