import re
from django.core.management.base import BaseCommand
from games.models import (InterpretedGameUrl, URL, Game, GameAuthor,
                          Personality, PersonalityAlias, GameURL)
from core.models import TaskQueueElement
import subprocess
import os.path
import shutil
import json
from logging import getLogger

logger = getLogger('worker')

#  {"module": "games.tasks.uploads", "name": "MarkBroken"}


def IfwikiCapitalizeFile():
    r = re.compile('^(.*ifwiki.ru/files/)(\w)(.*)$')
    for x in URL.objects.all():
        m = r.match(x.original_url)
        if m and m.group(2).islower():
            print(x.original_url)


def RenameUrls():
    R = re.compile(r'^/uploads/(.*)$')
    for x in URL.objects.all():
        if not x.local_url:
            continue
        m = R.match(x.local_url)
        if not m:
            raise x
        if x.is_uploaded:
            x.local_url = '/f/uploads/' + m.group(1)
        else:
            x.local_url = '/f/backups/' + m.group(1)
        x.save()


def RenameRecodes():
    R = re.compile(r'^/uploads/recode/(.*)$')
    for x in InterpretedGameUrl.objects.all():
        if not x.recoded_url:
            continue
        m = R.match(x.recoded_url)
        if not m:
            raise x
        x.recoded_url = '/f/recodes/' + m.group(1)
        x.save()


def UpdateTaskQueues():
    for x in TaskQueueElement.objects.all():
        if 'CloneGame' not in x.name:
            continue
        if x.fail:
            x.fail = False
            x.pending = True
        x.onfail_json = ('{"module": "games.tasks.uploads", '
                         '"name": "MarkBroken"}')
        x.save()


def ResetPermissions():
    for x in Game.objects.all():
        print(x.title)
        x.comment_perm = '(alias game_comment)'
        x.view_perm = '(alias game_view)'
        x.edit_perm = '(alias game_edit)'
        x.delete_perm = '(alias game_delete)'
        x.vote_perm = '(alias game_vote)'
        x.save()
    for x in Personality.objects.all():
        print(x.name)
        x.view_perm = '(alias personality_view)'
        x.edit_perm = '(alias personality_edit)'
        x.save()


def HasTag(tags, tag):
    for x in tags:
        if tag in x.lower():
            return x
    return False


def BuildLoonchatableLinks():
    DSTDIR = r'D:/Debug/Loons'
    count = 0
    BACKUPS_PATH = 'D:/Dev/ifdb/files/backups/%s'
    EXTRACTOR_PATH = '"C:/Program Files/7-Zip/7z.exe" x "%s" "-O%s"'
    for x in URL.objects.all():
        try:
            if not x.local_filename:
                continue
            ext = os.path.splitext(x.local_filename)[1][1:].lower()
            if ext in ['gif', 'jpg', 'jpeg', 'html', 'htm', 'png', 'txt']:
                continue
            g = list(
                Game.objects.filter(
                    gameurl__category__symbolic_id='download_direct',
                    gameurl__url=x).distinct())
            print(x.local_filename, g)
            if not g:
                continue
            d = {'panic': [], 'games': [], 'pkg': "gam-%05d" % count}
            if len(g) != 1:
                d['panic'].append('More than one game')
            tags = []
            for n in g:
                d['games'].append(n.title)
                tags.extend([y.name.lower() for y in n.tags.all()])
            d['tags'] = tags
            d['id'] = g[0].id

            src = BACKUPS_PATH % x.local_filename
            dst = os.path.join(DSTDIR, "%04d" % count)
            os.mkdir(dst)

            suffix = ''
            need_unpacking = True
            fireurq = HasTag(tags, 'fireurq')
            if fireurq:
                d['metadata'] = {"dependencies": [{"package": "fireurq"}]}
            if fireurq and ext == 'qst':
                need_unpacking = False
                d['metadata']['variables'] = {'gamefile': x.local_filename}

            if ext == 'qsp':
                need_unpacking = False

            if need_unpacking:
                try:
                    subprocess.check_output(
                        EXTRACTOR_PATH % (src, dst),
                        stderr=subprocess.STDOUT,
                        shell=True)
                    if fireurq:
                        suffix = 'fireurq'
                except subprocess.CalledProcessError:
                    d['panic'].append("Unextractable!")
                    need_unpacking = False
            if not need_unpacking:
                shutil.copyfile(src, os.path.join(dst, x.local_filename))

            if ext == 'qsp' or HasTag(tags, 'qsp'):
                d['metadata'] = {"dependencies": [{"package": "qsp"}]}
                if ext == 'qsp':
                    d['metadata']['variables'] = {'gamefile': x.local_filename}
                else:
                    for root, subFolders, files in os.walk(dst):
                        y = HasTag(files, '.qsp')
                        if y:
                            d['metadata']['variables'] = {'gamefile': y}
                            if os.path.abspath(root) != os.path.abspath(dst):
                                suffix = 'qsp'
                            break
                    else:
                        d['panic'].append('Не нашелся qsp')

            if 'metadata' not in d:
                d['panic'].append('Неизвестно что!')

            if d['panic'] and not suffix:
                if HasTag(tags, 'dosurq'):
                    suffix = 'dosurq'
                else:
                    suffix = 'panic'

            if suffix:
                os.rename(dst, dst + '_' + suffix)

            filename = ('!%04d.txt' % count) if d['panic'] else (
                '%04d.txt' % count)
            with open(
                    os.path.join(DSTDIR, filename), 'w',
                    encoding='utf-8') as f:
                f.write(json.dumps(d, indent=2, ensure_ascii=False))
        except:
            pass
        count += 1


def RemoveAuthors():
    Personality.objects.all().delete()
    GameAuthor.objects.filter(game__edit_time__isnull=True).delete()
    PersonalityAlias.objects.filter(gameauthor__isnull=True).delete()


# TODO Run that as a periodic job.
def FixGameAuthors():
    logger.info('*** Fixing blacklisted aliases')
    for x in PersonalityAlias.objects.filter(is_blacklisted=True):
        if x.personality:
            logger.info('Remove personality from alias [%s]' % x)
            x.personality = None
            x.save()
        if x.hidden_for:
            logger.info('Remove hidden_for from alias [%s]' % x)
            x.hidden_for = None
            x.save()

    logger.info('*** Checking hidden_for to be correct')
    for x in PersonalityAlias.objects.filter(
            hidden_for__isnull=False).select_related():
        if x.personality != None:
            x.personality = None
            logger.info('Resetting hidden_for for alias [%s]' % x)
            x.save()

    logger.info('*** Applying blacklist/hidden_for for non-edited games')
    for x in GameAuthor.objects.select_related():
        if x.author.is_blacklisted:
            logger.info('Blacklisted [%s] find in game [%s]' % (x.author,
                                                                x.game))
            if x.game.edit_time is None:
                x.delete()
            else:
                logger.warning('Game [%s] NOT AUTOUPDATEABLE!' % x.game)
            continue
        if x.author.hidden_for:
            logger.info('HiddenFor [%s] find in game [%s]' % (x.author,
                                                              x.game))
            if x.game.edit_time is not None:
                logger.warning('Game [%s] NOT AUTOUPDATEABLE!' % x.game)
            x.author = x.author.hidden_for
            x.save()

    logger.info('*** Fixing game duplicate aliases')
    for g in Game.objects.all():
        clusters = dict()
        for x in GameAuthor.objects.filter(game=g).select_related():
            clusters.setdefault((x.role.id, x.author.personality),
                                []).append(x)
        for k, v in clusters.items():
            if len(v) == 1:
                continue
            best = None
            record = None
            for i, y in enumerate(v):
                count = y.author.gameauthor_set.count()
                if best is None or count < best:
                    best = count
                    record = i

            logger.info('Game [%s], over [%s] we are keeping [%s]' %
                        (g, v, v[record]))
            for i, y in enumerate(v):
                if i != record:
                    y.delete()
            if g.edit_time is not None:
                logger.warning('Game [%s] NOT AUTOUPDATEABLE!' % g)

    logger.info('*** Killing hanging personalities')
    Personality.objects.filter(personalityalias__isnull=True).delete()

    logger.info('*** Killing hanging aliases')
    PersonalityAlias.objects.filter(
        is_blacklisted=False, hidden_for__isnull=True,
        gameauthor__isnull=True).delete()


def FixDuplicateUrls():
    logger.info('Fixing duplicate URLs')
    for x in Game.objects.all():
        urls = set()
        for y in GameURL.objects.filter(game=x):
            v = (y.url_id, y.category_id)
            if v in urls:
                logger.info("Game %s, url %s, removing" % (x, y))
                y.delete()
            else:
                urls.add(v)


class Command(BaseCommand):
    help = 'Does some batch processing.'

    def add_arguments(self, parser):
        parser.add_argument('cmd')

    def handle(self, cmd, *args, **options):
        options = {
            'removeauthors-destructiv': RemoveAuthors,
            'fixgameauthors': FixGameAuthors,
            'fixurldups': FixDuplicateUrls,
            'resetperms': ResetPermissions,
        }
        if cmd in options:
            options[cmd]()
        else:
            print('Unknown command, valid ones are:\n%s' % ', '.join(
                options.keys()))
