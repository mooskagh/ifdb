from django.core.management.base import BaseCommand
from games.models import (GameAuthorRole, GameTagCategory, GameTag,
                          GameURLCategory, PersonalityURLCategory, URL)
from contest.models import (CompetitionURLCategory)

AUTHOR_ROLES = [
    ['author', 'Автор'],
    ['artist', 'Художник'],
    ['tester', 'Тестировщик'],
    ['translator', 'Переводчик'],
    ['porter', 'Перенёс на другую платформу'],
    ['character', 'Персонаж'],
    ['programmer', 'Программист'],
    ['member', 'Участник (прочие)'],
    ['composer', 'Композитор'],
    ['orig_author', 'Автор оригинала'],
    ['voiceover', 'Актёр озвучания'],
]

TAG_CATS = [
    ['admin', 'Служебные', False, {
        'all': '@gardener'
    }],
    ['state', 'Стадия разработки', False, {
        'search': '@all'
    }],
    ['genre', 'Жанр', False, {}],
    ['platform', 'Платформа', True, {}],
    ['country', 'Страна', True, {
        'search': '@all'
    }],
    ['control', 'Управление', False, {}],
    ['os', 'Операционная система', False, {}],
    ['competition', 'Участник конкурса', True, {}],
    ['tag', 'Тэг', True, {}],
    ['language', 'Язык', True, {
        'search': '@all'
    }],
    ['ifid', 'IFID', True, {
        'search': '@all'
    }],
    ['version', 'Версия', True, {
        'search': '@all'
    }],
]

TAGS = [
    ['state', 'in_dev', 'В разработке'],
    ['state', 'beta', 'Бета'],
    ['state', 'released', 'Готовая'],
    ['state', 'demo', 'Демо'],
    ['os', 'os_win', 'Windows'],
    ['os', 'os_web', 'Web (online)'],
    ['os', 'os_macos', 'MacOs'],
    ['os', 'os_linux', 'Linux'],
    ['os', 'os_ios', 'iOS'],
    ['os', 'os_android', 'Android'],
    ['os', 'os_dos', 'DOS'],
    ['os', 'os_other', 'Другая ОС'],
    ['control', 'parser', 'Парсерная'],
    ['control', 'menu', 'Менюшная'],
    ['tag', 'ifwiki_featured', 'избранная на ifwiki'],
    ['genre', 'g_action', 'Боевик'],
    ['genre', 'g_adult', '18+'],
    ['genre', 'g_adventure', 'Приключения'],
    ['genre', 'g_detective', 'Детектив'],
    ['genre', 'g_drama', 'Драма'],
    ['genre', 'g_dystopy', 'Дистопия'],
    ['genre', 'g_experimental', 'Экспериментальное'],
    ['genre', 'g_fairytale', 'Сказка'],
    ['genre', 'g_fanfic', 'Фанфик'],
    ['genre', 'g_fantasy', 'Фэнтези'],
    ['genre', 'g_historical', 'Историческое'],
    ['genre', 'g_horror', 'Ужасы'],
    ['genre', 'g_humor', 'Юмор'],
    ['genre', 'g_kids', 'Детское'],
    ['genre', 'g_mystic', 'Мистика'],
    ['genre', 'g_puzzle', 'Головоломка'],
    ['genre', 'g_romance', 'Романтика'],
    ['genre', 'g_rpg', 'RPG'],
    ['genre', 'g_scifi', 'Фантастика'],
    ['genre', 'g_simulation', 'Симулятор'],
]

GAME_URL_CATS = [
    ['game_page', 'Эта игра на другом сайте', False],
    ['download_direct', 'Скачать (прямая ссылка)', True],
    ['download_landing', 'Скачать (ссылка на файлообменник)', False],
    [
        'play_in_interpreter', 'Открыть в интерпретаторе игр (UrqW и т.д.)',
        True
    ],
    ['play_online', 'Играть онлайн', False],
    ['poster', 'Постер', True],
    ['screenshot', 'Скриншот', True],
    ['forum', 'Обсуждение (форум)', False],
    ['review', 'Обзор', False],
    ['video', 'Видео', False],
    ['other', 'Прочее', False],
    ['unknown', 'Категория не назначена', False],
]

PERSONALITY_URL_CATS = [
    ['personal_page', 'Личный сайт автора', False],
    ['other_site', 'Страница автора на другом сайте', False],
    ['avatar', 'Фото/аватар', True],
    ['social', 'Ссылка в соцсети', False],
    ['interview', 'Интервью', False],
    ['other', 'Прочее', False],
]

COMPETITION_URL_CATS = [
    ['logo', 'Логотип', True],
    ['video', 'Видеообзор конкурса', False],
    ['official_page', 'Официальная страница конкурса', False],
    ['other_site', 'Описание конкурса на другом сайте', False],
    ['review', 'Обзоры конкурса', False],
    ['video', 'Видео', False],
    ['forum', 'Обсуждение конкурса', False],
    ['download_direct', 'Архив игр конкурса', True],
]


class Command(BaseCommand):
    help = 'Populates initial tags/author categories/etc'

    def handle(self, *args, **options):
        for x in AUTHOR_ROLES:
            (slug, desc) = x
            self.stdout.write(
                'Author role: %s (%s)... ' % (slug, desc), ending='')
            _, created = GameAuthorRole.objects.update_or_create(
                symbolic_id=slug, defaults={
                    'title': desc
                })
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in TAG_CATS:
            (slug, desc, allow_new, perm) = x
            self.stdout.write('Tag cat: %s (%s)... ' % (slug, desc), ending='')
            updates = {'name': desc, 'allow_new_tags': allow_new}
            if 'all' in perm:
                updates['show_in_edit_perm'] = perm['all']
                updates['show_in_search_perm'] = perm['all']
                updates['show_in_details_perm'] = perm['all']
            if 'search' in perm:
                updates['show_in_search_perm'] = perm['search']
            if 'edit' in perm:
                updates['show_in_search_perm'] = perm['edit']
            if 'details' in perm:
                updates['show_in_search_perm'] = perm['details']
            _, created = GameTagCategory.objects.update_or_create(
                symbolic_id=slug, defaults=updates)
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in TAGS:
            (cat, slug, desc) = x
            self.stdout.write('Tag: %s (%s)... ' % (slug, desc), ending='')
            c = GameTagCategory.objects.get(symbolic_id=cat)
            _, created = GameTag.objects.update_or_create(
                symbolic_id=slug, category=c, defaults={
                    'name': desc
                })
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in GAME_URL_CATS:
            (slug, desc, cloneable) = x
            self.stdout.write('GameUrl: %s (%s)... ' % (slug, desc), ending='')
            _, created = GameURLCategory.objects.update_or_create(
                symbolic_id=slug,
                defaults={
                    'title': desc,
                    'allow_cloning': cloneable
                })
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in PERSONALITY_URL_CATS:
            (slug, desc, cloneable) = x
            self.stdout.write('PersUrl: %s (%s)... ' % (slug, desc), ending='')
            _, created = PersonalityURLCategory.objects.update_or_create(
                symbolic_id=slug,
                defaults={
                    'title': desc,
                    'allow_cloning': cloneable
                })
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in COMPETITION_URL_CATS:
            (slug, desc, cloneable) = x
            self.stdout.write('CompUrl: %s (%s)... ' % (slug, desc), ending='')
            _, created = CompetitionURLCategory.objects.update_or_create(
                symbolic_id=slug,
                defaults={
                    'title': desc,
                    'allow_cloning': cloneable
                })
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))
