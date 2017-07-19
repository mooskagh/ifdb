import re
from django.core.management.base import BaseCommand
from games.models import InterpretedGameUrl, URL, Game
from core.models import TaskQueueElement
import subprocess
import os.path
import shutil
import json

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


class Command(BaseCommand):
    help = 'Does some batch processing.'

    def handle(self, *args, **options):
        BuildLoonchatableLinks()
