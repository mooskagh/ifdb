from django.core.management.base import BaseCommand
from django.db import transaction

from curation.models import EnrichmentRule, GenreMapping

# Ported from the old games/importer/enrichment.py rule list. Each entry is a
# (condition, action) pair of plain-Python source, run in order.
RULES = [
    (
        'has_tag("platform", "6days.*", "adrift", "r?inform.*", "r?tads.*", '
        '"tom 2", "ярил")',
        'add_tag("parser")',
    ),
    (
        'has_tag("platform", ".*qsp", ".*urq( .*)?", "apero", "axma.*", '
        '"ink.*", "questbox", "tweebox", "twine", "аперо", "квестер")',
        'add_tag("menu")',
    ),
    (
        'has_tag("platform", "aeroqsp", "apero", "axma.*", "r?inform.*", '
        '"tweebox", "twine", "urqw", "аперо", "квестер")',
        'add_tag("os_web")',
    ),
    (
        'has_tag("platform", ".*qsp", "akurq.*", "fireurq", "r?inform.*", '
        '"r?tads.*", "ripurq", "instead")',
        'add_tag("os_win")',
    ),
    (
        'has_tag("platform", "r?tads.*", "r?inform.*", "instead")',
        'add_tag("os_linux", "os_macos")',
    ),
    ('has_tag("platform", "dosurq")', 'add_tag("os_dos")'),
    (
        'has_tag("platform", "qsp") and has_url_category("play_online")',
        'add_tag("os_web")',
    ),
    (
        'has_tag("platform", ".*urq.*") '
        'or is_from_site("game_page", "urq.plut.info")',
        'clone_url("download_direct", "play_in_interpreter", '
        '"Открыть в UrqW: {description:.30}")',
    ),
    ('not has_tag("language", ".*")', 'add_raw_tag("language", "русский")'),
]

# Ported from the old tag_to_genre dict: tag -> (genre_slug, replace).
TAG_TO_GENRE = {
    "18+": ("g_adult", True),
    "action": ("g_action", False),
    "horror": ("g_horror", False),
    "rpg": ("g_rpg", True),
    "боевик": ("g_action", True),
    "викторина": ("g_puzzle", False),
    "головоломка": ("g_puzzle", True),
    "головоломки": ("g_puzzle", True),
    "детектив": ("g_detective", True),
    "детская": ("g_kids", True),
    "детское": ("g_kids", True),
    "дистопия": ("g_dystopy", True),
    "доисторическое": ("g_historical", True),
    "дорожное приключение": ("g_adventure", True),
    "драма": ("g_drama", True),
    "историческое": ("g_historical", True),
    "казка": ("g_fairytale", True),
    "космос": ("g_scifi", False),
    "логическая": ("g_puzzle", True),
    "мистика": ("g_mystic", True),
    "містыка": ("g_mystic", True),
    "научная фантастика": ("g_scifi", False),
    "непонятное": ("g_experimental", False),
    "паззл": ("g_puzzle", True),
    "паззлы": ("g_puzzle", True),
    "пазл": ("g_puzzle", True),
    "пазлы": ("g_puzzle", True),
    "постапокалипсис": ("g_dystopy", False),
    "постапокалиптика": ("g_dystopy", False),
    "преступление": ("g_detective", False),
    "приключение": ("g_adventure", True),
    "приключения": ("g_adventure", True),
    "рамантыка": ("g_romance", True),
    "ребус": ("g_puzzle", False),
    "роботы": ("g_scifi", False),
    "романтика": ("g_romance", True),
    "рпг": ("g_rpg", True),
    "секс": ("g_adult", False),
    "симулятор": ("g_simulation", True),
    "сказка": ("g_fairytale", True),
    "сюр": ("g_experimental", False),
    "сюрреализм": ("g_experimental", False),
    "триллер": ("g_horror", False),
    "убийство": ("g_detective", False),
    "ужас": ("g_horror", True),
    "ужасы": ("g_horror", True),
    "фантастика": ("g_scifi", True),
    "фанфик": ("g_fanfic", True),
    "фентези": ("g_fantasy", True),
    "фэнтези": ("g_fantasy", True),
    "хоррор": ("g_horror", False),
    "черный юмор": ("g_humor", False),
    "чёрный юмор": ("g_humor", False),
    "чёрти что": ("g_experimental", False),
    "шутер": ("g_action", False),
    "экспериментальное": ("g_experimental", True),
    "экшн": ("g_action", False),
    "эротика": ("g_adult", False),
    "юмор": ("g_humor", True),
}


class Command(BaseCommand):
    help = (
        "Seed enrichment rules and genre mappings from the old "
        "games/importer/enrichment.py defaults. Idempotent / re-runnable."
    )

    def handle(self, *args, **options):
        with transaction.atomic():
            rules_created = 0
            for order, (condition, action) in enumerate(RULES):
                _, created = EnrichmentRule.objects.get_or_create(
                    order=order,
                    condition=condition,
                    action=action,
                )
                rules_created += created

            mappings_created = 0
            for tag, (genre_slug, replace) in TAG_TO_GENRE.items():
                _, created = GenreMapping.objects.get_or_create(
                    tag=tag,
                    defaults={"genre_slug": genre_slug, "replace": replace},
                )
                mappings_created += created

        self.stdout.write(f"Enrichment rules created: {rules_created}")
        self.stdout.write(f"Genre mappings created: {mappings_created}")
