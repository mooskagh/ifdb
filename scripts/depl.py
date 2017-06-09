#!/home/ifdb/virtualenv/bin/python

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

    f.__doc__ = "Check file %s with template" % dst
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
        self.list_only = False
        self.step_by_step = False

    def AddStep(self, func):
        self.steps.append(func)

    def Run(self):
        if self.list_only:
            for i, n in enumerate(self.steps):
                click.secho('%2d. %s' % (i + 1, n.__doc__))
            return
        click.clear()

        context = {}
        if self.end is None:
            end = len(self.steps)
        idx = self.start - 1
        while self.start <= (idx + 1) <= end:
            task_f = self.steps[idx]
            try:
                click.echo(
                    click.style(
                        '[%2d/%2d]' % (idx + 1, len(self.steps)),
                        fg='green') + ' %s...' % task_f.__doc__)
                if self.step_by_step:
                    if not click.confirm('Should I run it?'):
                        idx += 1
                        continue
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
                    '[ JMP ] Jumping to %d (%s)' %
                    (idx + 1, self.steps[idx].__doc__),
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
@click.option('--start', '-s', default=1, type=int)
@click.option('--list-only', '-l', is_flag=True)
@click.option('--steps', is_flag=True)
@click.pass_context
def cli(ctx, start, list_only, steps):
    p = ctx.obj['pipeline']
    p.start = start
    p.list_only = list_only
    p.step_by_step = steps


@cli.command()
@click.option(
    '--message',
    '-m',
    default='Сайт временно не работает (что-то поломалось).',
    type=str)
@click.pass_context
def red(ctx, message):
    p = ctx.obj['pipeline']
    p.AddStep(
        GetFromTemplate('wallpage.tpl', 'wallpage/index.html',
                        {'message': message,
                         'timestamp':
                         int(time.time())}, False))
    p.AddStep(CheckFromTemplate('nginx.tpl', 'nginx.conf'))
    p.AddStep(
        GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                    [{'host': 'prod',
                                                      'conf': 'wallpage'},
                                                     {'host': 'staging',
                                                      'conf': 'deny'}]}))
    p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.AddStep(RunCmdStep('sudo /bin/systemctl stop ifdb'))
    p.Run()


@cli.command()
@click.pass_context
def green(ctx):
    p = ctx.obj['pipeline']
    p.AddStep(CheckFromTemplate('nginx.tpl', 'nginx.conf'))
    p.AddStep(
        GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                    [{'host': 'prod',
                                                      'conf': 'prod'},
                                                     {'host': 'staging',
                                                      'conf': 'deny'}]}))
    p.AddStep(RunCmdStep('sudo /bin/systemctl start ifdb'))
    p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.Run()


@cli.command()
@click.option('--tag', '-t', type=str)
@click.pass_context
def stage(ctx, tag):
    p = ctx.obj['pipeline']

    django_dir = os.path.join(STAGING_DIR, 'django')
    virtualenv_dir = os.path.join(STAGING_DIR, 'virtualenv')
    python_dir = os.path.join(virtualenv_dir, 'bin/python')

    p.AddStep(KillStaging)
    p.AddStep(CreateStaging)
    p.AddStep(
        RunCmdStep('git clone git@bitbucket.org:mooskagh/ifdb.git %s' %
                   django_dir))
    p.AddStep(ChDir(django_dir))
    p.AddStep(RunCmdStep('git checkout -b staging %s' % (tag or '')))
    p.AddStep(RunCmdStep('virtualenv -p python3 %s' % virtualenv_dir))
    p.AddStep(StagingDiff('django/requirements.txt'))
    p.AddStep(
        RunCmdStep('%s/bin/pip install -r %s/requirements.txt' % (
            virtualenv_dir, django_dir)))
    p.AddStep(StagingDiff('django/games/migrations/'))
    p.AddStep(StagingDiff('django/games/management/commands/initifdb.py'))
    p.AddStep(
        RunCmdStep('%s %s/manage.py collectstatic --clear' % (python_dir,
                                                              django_dir)))
    p.AddStep(StagingDiff('static/'))
    p.AddStep(CheckFromTemplate('nginx.tpl', 'nginx.conf'))
    p.AddStep(
        GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                    [{'host': 'prod',
                                                      'conf': 'prod'},
                                                     {'host': 'staging',
                                                      'conf': 'staging'}]}))
    p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.AddStep(
        LoopStep(RunCmdStep('kill -HUP `cat /tmp/uwsgi-ifdb-staging.pid`')))
    p.AddStep(
        GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                    [{'host': 'prod',
                                                      'conf': 'prod'},
                                                     {'host': 'staging',
                                                      'conf': 'deny'}]}))
    p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))
    p.AddStep(RunCmdStep('uwsgi --stop /tmp/uwsgi-ifdb-staging.pid'))
    p.Run()


@cli.command()
@click.option('--hot', is_flag=True)
@click.pass_context
def deploy(ctx, hot):
    p = ctx.obj['pipeline']
    django_dir = os.path.join(ROOT_DIR, 'django')
    virtualenv_dir = os.path.join(ROOT_DIR, 'virtualenv')
    python_dir = os.path.join(virtualenv_dir, 'bin/python')

    p.AddStep(
        RunCmdStep(
            'git diff-index --quiet HEAD --',
            doc="Check that git doesn't have uncommited changes"))
    p.AddStep(GetNextVersion)

    if not hot:
        p.AddStep(
            GetFromTemplate('wallpage.tpl', 'wallpage/index.html',
                            {'message': 'Сайт обновляется',
                             'timestamp':
                             int(time.time())}, False))
        p.AddStep(CheckFromTemplate('nginx.tpl', 'nginx.conf'))
        p.AddStep(
            GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                        [{'host': 'prod',
                                                          'conf': 'wallpage'},
                                                         {'host': 'staging',
                                                          'conf': 'deny'}]}))
        p.AddStep(StartTimer)
        p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))
        p.AddStep(RunCmdStep('sudo /bin/systemctl stop ifdb'))

    p.AddStep(ChDir(django_dir))
    p.AddStep(RunCmdStep('git pull'))

    if not hot:
        p.AddStep(
            RunCmdStep('%s/bin/pip install -r %s/requirements.txt' % (
                virtualenv_dir, django_dir)))
        p.AddStep(
            RunCmdStep('%s %s/manage.py migrate' % (python_dir, django_dir)))

    p.AddStep(
        RunCmdStep('%s %s/manage.py collectstatic --clear' % (python_dir,
                                                              django_dir)))
    if not hot:
        p.AddStep(
            RunCmdStep('%s %s/manage.py initifdb' % (python_dir, django_dir)))

    if hot:
        p.AddStep(RunCmdStep('sudo /bin/systemctl restart ifdb'))
    else:
        p.AddStep(RunCmdStep('sudo /bin/systemctl start ifdb'))

    p.AddStep(LoopStep(RunCmdStep('sudo /bin/systemctl restart ifdb')))

    if not hot:
        p.AddStep(
            GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                        [{'host': 'prod',
                                                          'conf': 'wallpage'},
                                                         {'host': 'staging',
                                                          'conf': 'prod'}]}))
        p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))

    p.AddStep(LoopStep(Message('Break NOW if anything is wrong')))

    if not hot:
        p.AddStep(
            GetFromTemplate('nginx.tpl', 'nginx.conf', {'configs':
                                                        [{'host': 'prod',
                                                          'conf': 'prod'},
                                                         {'host': 'staging',
                                                          'conf': 'deny'}]}))
        p.AddStep(RunCmdStep('sudo /bin/systemctl reload nginx'))
        p.AddStep(StopTimer)

    p.AddStep(GitTag)
    p.AddStep(RunCmdStep('git push origin master'))
    p.AddStep(WriteVersionConfig)
    p.Run()


def WriteVersionConfig(ctx):
    """Write current version into config."""
    with open(os.path.join(ROOT_DIR, 'configs/version.txt'), 'w') as f:
        f.write(ctx['new-version'])
    return True


def GitTag(ctx):
    """Adds a version tag into git."""
    cmd = 'git tag -a %s -m "Adding tag %s"' % (ctx['new-version'],
                                                ctx['new-version'])
    return RunCmdStep(cmd)(ctx)


def Message(msg):
    def f(ctx):
        click.secho(msg, fg='yellow')
        return True

    f.__doc__ = "Prints message: %s" % msg
    return f


def StartTimer(ctx):
    """Start timer."""
    ctx['down-time'] = int(time.time())
    return True


def StopTimer(ctx):
    """Stop timer."""
    hours = int(time.time()) - ctx['down-time']
    sec = hours % 60
    hours //= 60
    min = hours % 60
    hours //= 60
    click.secho('Was offline for %d hours, %d minutes, %d seconds. Check prod.'
                % (hours, min, sec))
    click.pause()
    return True


def GetNextVersion(ctx):
    """Determine Next Version"""
    version_re = re.compile(r'v(\d+).(\d+).(\d+)?')
    cnt = open(os.path.join(ROOT_DIR, 'configs/version.txt')).read().strip()
    m = version_re.match(cnt)
    if not m:
        click.secho(
            "version.txt contents is [%s], doesn't parse as version" % cnt,
            fg='red')
        return False
    v = (int(m.group(1)), int(m.group(2)), int(m.group(2))
         if m.group(2) else 0)
    variants = [(v[0], v[1], v[2] + 1), (v[0], v[1] + 1, 0), (v[0] + 1, 0, 0)]
    while True:
        click.secho("Current version is %s. What will be the new one?" % cnt)
        for i, n in enumerate(variants):
            click.secho("%d. %s" % (i + 1, BuildVersionStr(*n)), fg='yellow')
        r = click.prompt('', prompt_suffix='>>>>>>> ')
        try:
            r = int(r) - 1
            if 0 <= r < len(variants):
                ctx['new-version'] = BuildVersionStr(*v[r])
                return True
        except:
            pass


def BuildVersionStr(major, minor, bugfix):
    res = 'v%d.%02d' % (major, minor)
    if bugfix:
        res += '.%d' % bugfix
    return res


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


p = Pipeline()
cli(obj={'pipeline': p})
