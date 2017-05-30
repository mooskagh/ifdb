from django.core.management.base import BaseCommand
from games.models import GameAuthorRole, GameTagCategory, GameTag, URLCategory

AUTHOR_ROLES = [
    ['author', 'Автор'],
    ['artist', 'Художник'],
    ['tester', 'Тестировщик'],
]

TAG_CATS = [
    ['admin', 'Админское', False, '@admin'],
    ['state', 'Стадия разработки', False],
    ['genre', 'Жанр', True],
    ['platform', 'Платформа', True],
    ['country', 'Страна', True],
    ['os', 'Операционная система', False],
    ['source', 'Исходный код', False],
    ['price', 'Цена', False],
    ['competition', 'Участник конкурса', True],
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
    ['os', 'os_ioS', 'iOS'],
    ['os', 'os_android', 'Android'],
    ['os', 'os_dos', 'DOS'],
    ['os', 'os_other', 'Другая ОС'],
    ['source', 'open_source', 'Открыт'],
    ['source', 'closed_source', 'Закрыт'],
    ['price', 'free_price', 'Бесплатно'],
    ['price', 'has_price', 'Платно'],
]

URL_CATS = [
    ['game_page', 'Эта игра на другом сайте', False],
    ['download_direct', 'Скачать (прямая ссылка)', True],
    ['download_landing', 'Скачать (ссылка на сайт)', False],
    ['play_online', 'Играть онлайн', False],
    ['unknown', 'Прочее', False],
    ['poster', 'Постер', True],
    ['screenshot', 'Скриншот', True],
    ['project_page', 'Официальная страница', False],
    ['forum', 'Обсуждение (форум)', False],
    ['review', 'Обзор', False],
    ['video', 'Видео прохождения', False],
]


class Command(BaseCommand):
    help = 'Populates initial tags/author categories/etc'

    def handle(self, *args, **options):
        for x in AUTHOR_ROLES:
            (slug, desc) = x
            self.stdout.write('Author role: %s (%s)' % (slug, desc))
            y = GameAuthorRole()
            y.symbolic_id = slug
            y.title = desc
            y.save()

        for x in TAG_CATS:
            (slug, desc, allow_new, *perm) = x
            self.stdout.write('Tag cat: %s (%s)' % (slug, desc))
            y = GameTagCategory()
            y.symbolic_id = slug
            y.name = desc
            y.allow_new_tags = allow_new
            if perm:
                y.show_in_edit_perm = perm[0]
                y.show_in_search_perm = perm[0]
                y.show_in_details_perm = perm[0]
            y.save()

        for x in TAGS:
            (cat, slug, desc) = x
            self.stdout.write('Tag: %s (%s)' % (slug, desc))
            c = GameTagCategory.objects.get(symbolic_id=cat)
            y = GameTag()
            y.symbolic_id = slug
            y.category = c
            y.name = desc
            y.save()

        for x in URL_CATS:
            (slug, desc, cloneable) = x
            self.stdout.write('Url: %s (%s)' % (slug, desc))
            y = URLCategory()
            y.symbolic_id = slug
            y.title = desc
            y.allow_cloning = cloneable
            y.save()
