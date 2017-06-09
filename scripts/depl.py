#!/bin/env python

from django.conf import settings
from django.template import Template, Context
import click
import difflib
import django
import os
import os.path
import re
import sys
import time
import traceback
import socket
import json
import filecmp
import shutil

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.dirname(os.path.realpath(__file__))],
    }
]
settings.configure(TEMPLATES=TEMPLATES)
django.setup()
os.path.realpath(__file__)

IS_PROD = socket.gethostname() == 'ribby.mooskagh.com'
TPL_DIR = os.path.dirname(os.path.realpath(__file__))
if IS_PROD:
    ROOT_DIR = '/home/ifdb'
    DST_DIR = '/home/ifdb/configs'
else:
    ROOT_DIR = 'D:/tmp'
    DST_DIR = 'D:/tmp'
STAGING_DIR = os.path.join(ROOT_DIR, 'staging')


class Jump(BaseException):
    def __init__(self, whereto):
        self.whereto = whereto


def GenerateStringFromTemplate(template, params, gen_header):
    with open(os.path.join(TPL_DIR, template)) as f:
        tpl = f.read()
    t = Template(tpl)
    c = Context(params)
    content = ('# Gen-hdr: %s\n' % json.dumps(params)) if gen_header else ''
    content += t.render(c)
    return content


def RunCmdStep(cmd_line, doc=None):
    def f(context):
        click.secho('$ %s' % cmd_line, fg='yellow')
        r = os.system(cmd_line)
        if r != 0:
            click.echo('Return code %d, The command was: %s' % (r, click.style(
                cmd_line, fg='yellow')))
            return False
        return True

    if doc:
        f.__doc__ = doc
    else:
        f.__doc__ = "Execution of %s " % cmd_line
    return f


def GetFromTemplate(template, dst, params, gen_header=True):
    def f(context):
        cnt = GenerateStringFromTemplate(template, params, gen_header)
        with open(os.path.join(DST_DIR, dst), 'w') as fo:
            fo.write(cnt)
        return True

    f.__doc__ = "Generate %s from template" % dst
    return f


def CheckFromTemplate(template, dst):
    def f(ctx):
        with open(os.path.join(DST_DIR, dst)) as f:
            cnt = f.read()

        m = re.match(r'# Gen-hdr: ([^\n]+)\n(.*)', cnt, re.DOTALL)
        if not m:
            click.secho('Header not found in %s' % dst, fg='red')
            return False
        parms = json.loads(m.group(1))
        cnt = [x.rstrip() for x in m.group(2).split('\n')]
        tpl = [x.rstrip()
               for x in GenerateStringFromTemplate(template, parms, False)
               .split('\n')]
        diff = list(difflib.context_diff(tpl, cnt))
        if not diff:
            return True
        click.secho('Regenerated file does not match:', fg='red', bold=True)
        for l in diff:
            click.secho(l.rstrip(), fg='red')

    f.__doc__ = "Generate file %s with template" % dst
    return f


def RetryPrompt():
    while True:
        click.secho('(retry/ignore/abort)', fg='cyan')
        value = click.prompt('', prompt_suffix='>>>>>>> ')
        if value == 'retry':
            return True
        if value == 'ignore':
            return False
        if value == 'abort':
            sys.exit(1)


class Pipeline:
    def __init__(self):
        self.steps = []
        self.start = 1
        self.end = None

    def AddStep(self, name, func):
        self.steps.append((name, func))

    def Run(self):
        click.clear()
        context = {}
        if self.start is str:
            self.start = zip(*self.steps)[0].index(self.start) + 1
        if self.end is str:
            self.end = zip(*self.tasks)[0].index(self.end) + 1
        if self.end is None:
            end = len(self.steps)
        idx = self.start - 1
        while self.start <= (idx + 1) <= end:
            task_id, task_f = self.steps[idx]
            try:
                click.echo(
                    click.style(
                        '[%2d/%2d]' % (idx + 1, len(self.steps)), fg='green') +
                    ' %s - %s...' % (click.style(
                        task_id, bold=True), task_f.__doc__))
                if task_f(context):
                    idx += 1
                    continue
            except click.Abort:
                raise
            except Jump as jmp:
                if jmp.whereto is int:
                    idx += jmp.whereto
                else:
                    idx = zip(*self.steps)[0].index(jmp.whereto)
                click.secho(
                    '[ JMP ] Jumping to %s (%d)' %
                    (self.steps[idx][0], idx + 1),
                    fg='green',
                    bold=True)
                continue
            except:
                click.secho(traceback.format_exc(), fg='red')

            click.secho('[ FAIL ]', fg='red', bold=True)
            if not RetryPrompt():
                idx += 1
        click.secho('The pipeline has finished.', fg='green', bold=True)


@click.group()
@click.pass_context
@click.option(
   '--start', '-s', default=1, type=int)
def cli(ctx, start):
    p = Pipeline()
    p.start = start
    ctx.obj['pipeline'] = p



@cli.command()
@click.option(
    '--message',
    '-m',
    default='Сайт временно не работает (что-то поломалось).',
    type=str)
@click.pass_context
def red(ctx, message):
    p = ctx.obj['pipeline']
    p.AddStep('gen-wallpage', GetFromTemplate(
        'wallpage.tpl', 'wallpage/index.html', {'message': message,
                                                'timestamp':
                                                int(time.time())}, False))
    p.AddStep('cnk-nginx', CheckFromTemplate('nginx.tpl', 'nginx.conf'))
    p.AddStep('gen-nginx', GetFromTemplate(
        'nginx.tpl', 'nginx.conf', {'configs':
                                    [{'host': 'prod',
                                      'conf': 'wallpage'}, {'host': 'staging',
                                                            'conf': 'deny'}]}))
    p.AddStep('reload-nginx', RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.AddStep('stop-uwsgi', RunCmdStep('sudo /bin/systemctl stop ifdb'))
    p.Run()


@cli.command()
@click.pass_context
def green(ctx):
    p = ctx.obj['pipeline']
    p.AddStep('cnk-nginx', CheckFromTemplate('nginx.tpl', 'nginx.conf'))
    p.AddStep('gen-nginx', GetFromTemplate(
        'nginx.tpl', 'nginx.conf', {'configs':
                                    [{'host': 'prod',
                                      'conf': 'prod'}, {'host': 'staging',
                                                        'conf': 'deny'}]}))
    p.AddStep('stop-uwsgi', RunCmdStep('sudo /bin/systemctl start ifdb'))
    p.AddStep('reload-nginx', RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.Run()


@cli.command()
@click.option('--tag', '-t', type=str)
@click.pass_context
def stage(ctx, tag):
    p = ctx.obj['pipeline']

    django_dir = os.path.join(STAGING_DIR, 'django')
    virtualenv_dir = os.path.join(STAGING_DIR, 'virtualenv')
    python_dir = os.path.join(virtualenv_dir, 'bin/python')

    p.AddStep('rm-old-staging', KillStaging)
    p.AddStep('create-staging', CreateStaging)
    p.AddStep('git-clone', RunCmdStep(
        'git clone git@bitbucket.org:mooskagh/ifdb.git %s' % django_dir))
    p.AddStep('cd-staging', ChDir(django_dir))
    p.AddStep('git-checkout',
              RunCmdStep('git checkout -b staging %s' % (tag or '')))
    p.AddStep('mk-virtualenv',
              RunCmdStep('virtualenv -p python3 %s' % virtualenv_dir))
    p.AddStep('reqs-diff', StagingDiff('django/requirements.txt'))
    p.AddStep('venv-pip', RunCmdStep(
        '%s/bin/pip install -r %s/requirements.txt' % (virtualenv_dir, django_dir)))
    p.AddStep('reqs-migr', StagingDiff('django/games/migrations/'))
    p.AddStep('reqs-initifdb',
              StagingDiff('django/games/management/commands/initifdb.py'))
    p.AddStep('collect-static', RunCmdStep('%s %s/manage.py collectstatic --clear' % (python_dir, django_dir)))
    p.AddStep('reqs-migr', StagingDiff('static/'))
    p.AddStep('cnk-nginx', CheckFromTemplate('nginx.tpl', 'nginx.conf'))
    p.AddStep('gen-nginx1', GetFromTemplate(
        'nginx.tpl', 'nginx.conf', {'configs':
                                    [{'host': 'prod',
                                      'conf': 'prod'}, {'host': 'staging',
                                                        'conf': 'staging'}]}))
    p.AddStep('reload-nginx1', RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.AddStep(
        'loop-uwsgi',
        LoopStep(RunCmdStep('kill -HUP `cat /tmp/uwsgi-ifdb-staging.pid`')))
    p.AddStep('gen-nginx2', GetFromTemplate(
        'nginx.tpl', 'nginx.conf', {'configs':
                                    [{'host': 'prod',
                                      'conf': 'prod'}, {'host': 'staging',
                                                        'conf': 'deny'}]}))
    p.AddStep('reload-nginx2', RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.AddStep('kill-uwsgi', RunCmdStep('uwsgi --stop /tmp/uwsgi-ifdb-staging.pid'))
    p.Run()


def LoopStep(func):
    def f(ctx):
        while True:
            click.secho('Want to run [%s]' % func.__doc__, fg='yellow')
            if not click.confirm('Should I?'):
                return True
            if not func(ctx):
                return False
    f.__doc__ = "Loop: %s" % func.__doc__
    return f


def print_diff_files(dcmp):
    diff = False
    for name in dcmp.diff_files:
        click.secho('* %s' % name, fg='red')
        diff = True
    for name in dcmp.left_only:
        click.secho('- %s' % name, fg='red')
        diff = True
    for name in dcmp.right_only:
        click.secho('+ %s' % name, fg='red')
        diff = True
    for sub_dcmp in dcmp.subdirs.values():
        diff = print_diff_files(sub_dcmp) or diff
    return diff


def StagingDiff(filename):
    def f(ctx):
        if filename[-1] == '/':
            d1 = os.path.join(ROOT_DIR, filename)
            d2 = os.path.join(STAGING_DIR, filename)
            diff = print_diff_files(filecmp.dircmp(d1, d2, ['__pycache__']))
            if not diff:
                return True
        else:
            t1 = open(os.path.join(ROOT_DIR, filename)).read().split('\n')
            t2 = open(os.path.join(STAGING_DIR, filename)).read().split('\n')
            diff = list(difflib.context_diff(t1, t2))
            if not diff:
                return True
            click.secho(
                'File %s does not match:' % filename, fg='red', bold=True)
            for l in diff:
                click.secho(l.rstrip(), fg='red')
        if click.confirm('Do you want to continue?'):
            return True
        else:
            raise click.Abort

    f.__doc__ = "Comparing %s" % filename
    return f


def ChDir(whereto):
    def f(ctx):
        os.chdir(whereto)
        return True

    f.__doc__ = "Change directory to %s" % whereto
    return f


def CreateStaging(ctx):
    """Create staging directory"""
    d = os.path.join(STAGING_DIR)
    os.mkdir(d)
    return True


def KillStaging(ctx):
    """Remove staging directory is exists"""
    d = os.path.join(STAGING_DIR)
    if os.path.isdir(d):
        shutil.rmtree(d)
    return True

# @cli.command()
# @click.pass_context
# def deploy(ctx):
#     p = ctx.obj['pipeline']
#     p.AddStep(
#         'git-nochanges',
#         RunCmdStep(
#             'git diff-index --quiet HEAD --',
#             doc="Check that git doesn't have uncommited changes"))

cli(obj={})
