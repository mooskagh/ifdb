from django.core.management.base import BaseCommand
from games.models import GameAuthorRole, GameTagCategory, GameTag, URLCategory

AUTHOR_ROLES = [
    ['author', 'Автор'],
    ['artist', 'Художник'],
    ['tester', 'Тестировщик'],
    ['translator', 'Переводчик'],
    ['porter', 'Перенёс на другую платформу'],
    ['character', 'Персонаж'],
    ['member', 'Участник (прочие)'],
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
    ['ifid', 'IFID', True],
    ['version', 'Версия', True],
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
            self.stdout.write(
                'Author role: %s (%s)... ' % (slug, desc), ending='')
            _, created = GameAuthorRole.objects.update_or_create(
                symbolic_id=slug, defaults={'title': desc})
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in TAG_CATS:
            (slug, desc, allow_new, *perm) = x
            self.stdout.write('Tag cat: %s (%s)... ' % (slug, desc), ending='')
            updates = {'name': desc, 'allow_new_tags': allow_new}
            if perm:
                updates['show_in_edit_perm'] = perm[0]
                updates['show_in_search_perm'] = perm[0]
                updates['show_in_details_perm'] = perm[0]
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
                symbolic_id=slug, category=c, defaults={'name': desc})
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))

        for x in URL_CATS:
            (slug, desc, cloneable) = x
            self.stdout.write('Url: %s (%s)... ' % (slug, desc), ending='')
            _, created = URLCategory.objects.update_or_create(
                symbolic_id=slug,
                defaults={
                    'title': desc,
                    'allow_cloning': cloneable
                })
            if created:
                self.stdout.write(self.style.SUCCESS('created.'))
            else:
                self.stdout.write(self.style.WARNING('already exists.'))
