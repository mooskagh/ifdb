#!/bin/env python3

from django.conf import settings
from django.template import Template, Context
import click
import difflib
import django
import os
import os.path
import pickle
import re
import sys
import time
import traceback
import socket
import json
import filecmp
import shutil
from pathlib import Path

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.dirname(os.path.realpath(__file__))],
    }
]
settings.configure(TEMPLATES=TEMPLATES)
django.setup()

IS_PROD = socket.gethostname() in ["crem.xyz", "flatty"]
TPL_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
ROOT_DIR = Path("/home/ifdb")

PROD_SUBDIR = Path("distrib/ifdb")
CONFIGS_DIR = ROOT_DIR / "configs"
STAGING_DIR = ROOT_DIR / "staging"
BACKUPS_DIR = ROOT_DIR / "backups"
DISTRIB_DIR = ROOT_DIR / PROD_SUBDIR


class Jump(BaseException):

    def __init__(self, whereto):
        self.whereto = whereto


def GenerateStringFromTemplate(template, params, gen_header):
    with open(TPL_DIR / template) as f:
        tpl = f.read()
    t = Template(tpl)
    c = Context(params)
    content = ("# Gen-hdr: %s\n" % json.dumps(params)) if gen_header else ""
    content += t.render(c)
    return content


def RunCmdStep(cmd_line, doc=None):

    def f(context):
        click.secho("$ %s" % cmd_line, fg="yellow")
        r = os.system(cmd_line)
        if r != 0:
            click.echo(
                "Return code %d, The command was: %s"
                % (r, click.style(cmd_line, fg="yellow"))
            )
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
        with open(CONFIGS_DIR / dst, "w") as fo:
            fo.write(cnt)
        return True

    f.__doc__ = "Generate %s from template" % dst
    return f


def CheckFromTemplate(template, dst):

    def f(ctx):
        with open(CONFIGS_DIR / dst) as f:
            cnt = f.read()

        m = re.match(r"# Gen-hdr: ([^\n]+)\n(.*)", cnt, re.DOTALL)
        if not m:
            click.secho("Header not found in %s" % dst, fg="red")
            return False
        parms = json.loads(m.group(1))
        cnt = [x.rstrip() for x in m.group(2).split("\n")]
        tpl = [
            x.rstrip()
            for x in GenerateStringFromTemplate(template, parms, False).split("\n")
        ]
        diff = list(difflib.context_diff(tpl, cnt))
        if not diff:
            return True
        click.secho("Regenerated file does not match:", fg="red", bold=True)
        for line in diff:
            click.secho(line.rstrip(), fg="red")

    f.__doc__ = "Check file %s with template" % dst
    return f


def RetryPrompt():
    while True:
        click.secho("(retry/ignore/abort)", fg="cyan")
        value = click.prompt("", prompt_suffix=">>>>>>> ")
        if value == "retry":
            return True
        if value == "ignore":
            return False
        if value == "abort":
            sys.exit(1)


class Pipeline:

    def __init__(self):
        self.steps = []
        self.start = 1
        self.end = None
        self.list_only = False
        self.step_by_step = False
        self.context = {}
        self.cmd_name = "unknown"

    def AddStep(self, func):
        self.steps.append(func)

    def StateFileName(self):
        return CONFIGS_DIR / f"{self.cmd_name}_state.pickle"

    def MaybeLoadState(self):
        if os.path.isfile(self.StateFileName()):
            if click.confirm("Forgotten state found. Restore?"):
                with open(self.StateFileName(), "b") as f:
                    self.context = pickle.load(f)
                    if "chdir" in self.context:
                        os.chdir(self.context["chdir"])

    def StoreState(self):
        with open(self.StateFileName(), "wb") as f:
            pickle.dump(self.context, f)

    def Run(self, cmd_name):
        self.cmd_name = cmd_name
        if self.list_only:
            for i, n in enumerate(self.steps):
                click.secho("%2d. %s" % (i + 1, n.__doc__))
            return
        click.clear()

        if self.end is None:
            end = len(self.steps)
        self.context["idx"] = self.start - 1

        self.MaybeLoadState()

        while self.start <= (self.context["idx"] + 1) <= end:
            self.StoreState()

            task_f = self.steps[self.context["idx"]]
            try:
                click.echo(
                    click.style(
                        "[%2d/%2d]" % (self.context["idx"] + 1, len(self.steps)),
                        fg="green",
                    )
                    + " %s..." % task_f.__doc__
                )
                if self.step_by_step:
                    if not click.confirm("Should I run it?"):
                        raise click.Abort
                if task_f(self.context):
                    self.context["idx"] += 1
                    continue
            except click.Abort:
                raise
            except Jump as jmp:
                self.context["idx"] += jmp.whereto
                click.secho(
                    "[ JMP ] Jumping to %d (%s)"
                    % (
                        self.context["idx"] + 1,
                        self.steps[self.context["idx"]].__doc__,
                    ),
                    fg="green",
                    bold=True,
                )
                continue
            except:
                click.secho(traceback.format_exc(), fg="red")

            click.secho("[ FAIL ]", fg="red", bold=True)
            if not RetryPrompt():
                self.context["idx"] += 1
        click.secho("The pipeline has finished.", fg="green", bold=True)
        os.remove(self.StateFileName())


@click.group()
@click.option("--start", "-s", default=1, type=int)
@click.option("--list", "-l", is_flag=True)
@click.option("--steps", is_flag=True)
@click.pass_context
def cli(ctx, start, list, steps):
    p = ctx.obj["pipeline"]
    p.start = start
    p.list_only = list
    p.step_by_step = steps


##############################################################################
# Red
##############################################################################


@cli.command()
@click.option(
    "--message",
    "-m",
    default="Сайт временно не работает (что-то поломалось).",
    type=str,
)
@click.pass_context
def red(ctx, message):
    p = ctx.obj["pipeline"]
    p.AddStep(
        GetFromTemplate(
            "wallpage.tpl",
            "wallpage/index.html",
            {"message": message, "timestamp": int(time.time())},
            False,
        )
    )
    p.AddStep(CheckFromTemplate("nginx.tpl", "nginx.conf"))
    p.AddStep(
        GetFromTemplate(
            "nginx.tpl",
            "nginx.conf",
            {
                "configs": [
                    {"host": "prod", "conf": "wallpage"},
                    {"host": "kontigr", "conf": "wallpage"},
                    {"host": "zok", "conf": "wallpage"},
                    {"host": "staging", "conf": "deny"},
                ]
            },
        )
    )
    p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi-kontigr"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi-zok"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-worker"))
    p.Run("red")


##############################################################################
# Green
##############################################################################


@cli.command()
@click.pass_context
def green(ctx):
    p = ctx.obj["pipeline"]
    p.AddStep(CheckFromTemplate("nginx.tpl", "nginx.conf"))
    p.AddStep(
        GetFromTemplate(
            "nginx.tpl",
            "nginx.conf",
            {
                "configs": [
                    {"host": "prod", "conf": "prod"},
                    {"host": "kontigr", "conf": "kontigr"},
                    {"host": "zok", "conf": "zok"},
                    {"host": "staging", "conf": "deny"},
                ]
            },
        )
    )
    p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-kontigr"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-zok"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-worker"))
    p.Run("green")


##############################################################################
# Stage
##############################################################################


@cli.command()
@click.option("--tag", "-t", type=str)
@click.pass_context
def stage(ctx, tag):
    p = ctx.obj["pipeline"]

    virtualenv_dir = STAGING_DIR / "virtualenv"
    python_dir = virtualenv_dir / "bin/python"

    p.AddStep(KillStaging)
    p.AddStep(CreateStaging)
    p.AddStep(
        RunCmdStep("git clone git@bitbucket.org:mooskagh/ifdb.git %s" % DISTRIB_DIR)
    )
    p.AddStep(ChDir(DISTRIB_DIR))
    p.AddStep(RunCmdStep("git checkout -b staging %s" % (tag or "")))
    p.AddStep(RunCmdStep("virtualenv -p python3 %s" % virtualenv_dir))
    p.AddStep(StagingDiff(PROD_SUBDIR / "requirements.txt"))
    p.AddStep(
        RunCmdStep(
            "%s/bin/pip install -r %s/requirements.txt --no-cache-dir"
            % (virtualenv_dir, DISTRIB_DIR)
        )
    )
    p.AddStep(StagingDiff(PROD_SUBDIR / "games/migrations/"))
    p.AddStep(StagingDiff(PROD_SUBDIR / "core/migrations/"))
    p.AddStep(StagingDiff(PROD_SUBDIR / "games/management/commands/initifdb.py"))
    p.AddStep(StagingDiff(PROD_SUBDIR / "scripts/nginx.tpl"))
    p.AddStep(
        RunCmdStep("%s %s/manage.py collectstatic --clear" % (python_dir, DISTRIB_DIR))
    )
    p.AddStep(StagingDiff("static/"))
    p.AddStep(RunCmdStep("chmod -R a+rX %s/static" % STAGING_DIR))
    p.AddStep(
        RunCmdStep("%s/bin/uwsgi %s/uwsgi-staging.ini" % (virtualenv_dir, CONFIGS_DIR))
    )
    p.AddStep(CheckFromTemplate("nginx.tpl", "nginx.conf"))
    p.AddStep(
        GetFromTemplate(
            "nginx.tpl",
            "nginx.conf",
            {
                "configs": [
                    {"host": "prod", "conf": "prod"},
                    {"host": "kontigr", "conf": "kontigr"},
                    {"host": "zok", "conf": "zok"},
                    {"host": "staging", "conf": "staging"},
                ]
            },
        )
    )
    p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))
    p.AddStep(
        LoopStep(
            RunCmdStep("kill -HUP `cat /tmp/uwsgi-ifdb-staging.pid`"),
            "Check STAGING and reload if needed.",
        )
    )
    p.AddStep(
        GetFromTemplate(
            "nginx.tpl",
            "nginx.conf",
            {
                "configs": [
                    {"host": "prod", "conf": "prod"},
                    {"host": "kontigr", "conf": "kontigr"},
                    {"host": "zok", "conf": "zok"},
                    {"host": "staging", "conf": "deny"},
                ]
            },
        )
    )
    p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))
    p.AddStep(
        RunCmdStep("%s/bin/uwsgi --stop /tmp/uwsgi-ifdb-staging.pid" % virtualenv_dir)
    )
    p.Run("stage")


##############################################################################
# Deploy
##############################################################################


@cli.command()
@click.option("--hot", is_flag=True)
@click.option("--from-master/--no-from-master", default=None, is_flag=True)
@click.pass_context
def deploy(ctx, hot, from_master):
    if from_master is None:
        click.secho("Please specify --[no-]from-master!", fg="red", bold=True)
        raise click.Abort
    p = ctx.obj["pipeline"]
    virtualenv_dir = ROOT_DIR / "virtualenv"
    python_dir = virtualenv_dir / "bin/python"

    p.AddStep(
        RunCmdStep(
            "pg_dump ifdb > %s"
            % (BACKUPS_DIR / "database" / time.strftime("%Y%m%d_%H%M"))
        )
    )
    p.AddStep(ChDir(DISTRIB_DIR))
    p.AddStep(
        RunCmdStep(
            "git diff-index --quiet HEAD --",
            doc="Check that git doesn't have uncommited changes",
        )
    )
    p.AddStep(RunCmdStep("git fetch"))

    if not hot:
        p.AddStep(
            GetFromTemplate(
                "wallpage.tpl",
                "wallpage/index.html",
                {"message": "Сайт обновляется", "timestamp": int(time.time())},
                False,
            )
        )
        p.AddStep(CheckFromTemplate("nginx.tpl", "nginx.conf"))
        p.AddStep(
            GetFromTemplate(
                "nginx.tpl",
                "nginx.conf",
                {
                    "configs": [
                        {"host": "prod", "conf": "wallpage"},
                        {"host": "kontigr", "conf": "wallpage"},
                        {"host": "zok", "conf": "wallpage"},
                        {"host": "staging", "conf": "deny"},
                    ]
                },
            )
        )
        p.AddStep(StartTimer)
        p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi-kontigr"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi-zok"))

    p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-worker"))

    if not hot:
        p.AddStep(
            Message("uWSGI is stopped now. You can break now to do manual steps.")
        )

    p.AddStep(RunCmdStep("git checkout release"))
    p.AddStep(RunCmdStep("git pull"))

    if from_master:
        p.AddStep(RunCmdStep("git fetch origin master:master"))
        p.AddStep(RunCmdStep("git merge --no-ff master"))
        p.AddStep(GetNextVersion)

    if not hot:
        p.AddStep(
            RunCmdStep(
                "%s/bin/pip install -r %s/requirements.txt --no-cache-dir"
                % (virtualenv_dir, DISTRIB_DIR)
            )
        )
        p.AddStep(RunCmdStep("%s %s/manage.py migrate" % (python_dir, DISTRIB_DIR)))
        p.AddStep(
            RunCmdStep(
                "pg_dump ifdb > %s"
                % (BACKUPS_DIR / "database" / time.strftime("%Y%m%d_%H%M-postmigr"))
            )
        )

    if hot:
        p.AddStep(
            RunCmdStep("%s %s/manage.py collectstatic" % (python_dir, DISTRIB_DIR))
        )
    else:
        p.AddStep(
            RunCmdStep(
                "%s %s/manage.py collectstatic --clear" % (python_dir, DISTRIB_DIR)
            )
        )
    if not hot:
        p.AddStep(RunCmdStep("%s %s/manage.py initifdb" % (python_dir, DISTRIB_DIR)))

    if hot:
        p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-kontigr"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-zok"))
    else:
        p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-kontigr"))
        p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-zok"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-worker"))

    if not hot:
        p.AddStep(
            GetFromTemplate(
                "nginx.tpl",
                "nginx.conf",
                {
                    "configs": [
                        {"host": "prod", "conf": "wallpage"},
                        {"host": "kontigr", "conf": "wallpage"},
                        {"host": "zok", "conf": "wallpage"},
                        {"host": "staging", "conf": "prod"},
                    ]
                },
            )
        )
        p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))

    p.AddStep(
        LoopStep(
            RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi"),
            "Check STAGING and reload if needed.",
        )
    )

    if not hot:
        p.AddStep(
            GetFromTemplate(
                "nginx.tpl",
                "nginx.conf",
                {
                    "configs": [
                        {"host": "prod", "conf": "prod"},
                        {"host": "kontigr", "conf": "kontigr"},
                        {"host": "zok", "conf": "zok"},
                        {"host": "staging", "conf": "deny"},
                    ]
                },
            )
        )
        p.AddStep(RunCmdStep("sudo /bin/systemctl reload nginx"))
        p.AddStep(StopTimer)
    p.AddStep(
        Message("Break NOW if anything is wrong", "Check PROD and break if needed.")
    )

    p.AddStep(
        RunCmdStep(
            "git diff-index --exit-code HEAD --",
            doc="Check that git doesn't have uncommited changes.",
        )
    )

    p.AddStep(MaybeCreateNewBugfixVersion)

    p.AddStep(JumpIfExists("new-version", if_false=2))
    p.AddStep(WriteVersionConfigAndGitTag)
    p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-kontigr"))
    p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-zok"))

    if from_master:
        p.AddStep(RunCmdStep("git fetch . release:master"))

    p.AddStep(RunCmdStep("git push --all origin"))
    p.AddStep(RunCmdStep("git push --tags origin"))

    p.Run("deploy")


def JumpIfExists(var, if_true=1, if_false=1):

    def f(ctx):
        jmp = None
        if var in ctx:
            click.secho(
                "%s exists and equal to %s, jumping %+d" % (var, ctx[var], if_true),
                fg="yellow",
            )
            jmp = if_true
        else:
            click.secho(
                "%s is not in context, jumping %+d" % (var, if_false), fg="yellow"
            )
            jmp = if_false
        if jmp == 1:
            return True
        else:
            raise Jump(jmp)

    f.__doc__ = "Jump %+d if %s exists else jump %+d" % (if_true, var, if_false)
    return f


def MaybeCreateNewBugfixVersion(ctx):
    """Creates a new bugfix version if needed."""
    if "new-version" in ctx:
        click.secho("New version %s already known." % ctx["new-version"], fg="yellow")
        return True
    if RunCmdStep("git describe --exact-match HEAD")(ctx):
        click.secho("No changes since last version.", fg="yellow")
        return True
    v = GetCurrentVersion()
    v = BuildVersionStr(v[0], v[1], v[2] + 1)
    click.secho("New version is %s." % v, fg="yellow")
    ctx["new-version"] = v
    return True


def WriteVersionConfigAndGitTag(ctx):
    """Write current version into config."""
    v = ctx["new-version"]
    with open(DISTRIB_DIR / "version.txt", "w") as f:
        f.write("%s" % v)
    if not RunCmdStep("git add version.txt")(ctx):
        return False
    if not RunCmdStep('git commit -m "Change version.txt to %s."' % v)(ctx):
        return False
    if not RunCmdStep('git tag -a %s -m "Adding tag %s"' % (v, v))(ctx):
        return False
    return True


def GetCurrentVersion():
    version_re = re.compile(r"v(\d+)\.(\d+)(?:\.(\d+))?")
    cnt = open(DISTRIB_DIR / "version.txt").read().strip()
    m = version_re.match(cnt)
    if not m:
        click.secho(
            "version.txt contents is [%s], doesn't parse as version" % cnt, fg="red"
        )
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else 0)


def GetNextVersion(ctx):
    """Determine Next Version"""
    v = GetCurrentVersion()
    if not v:
        return None
    variants = [
        (v[0], v[1], v[2] + 1),
        (v[0], v[1] + 1, 0),
        (v[0], v[1] + 2, 0),
        (v[0] + 1, 0, 0),
    ]
    while True:
        click.secho(
            "Current version is %s. What will be the new one?" % BuildVersionStr(*v)
        )
        for i, n in enumerate(variants):
            click.secho("%d. %s" % (i + 1, BuildVersionStr(*n)), fg="yellow")
        r = click.prompt("", prompt_suffix=">>>>>>> ")
        try:
            r = int(r) - 1
            if 0 <= r < len(variants):
                ctx["new-version"] = BuildVersionStr(*variants[r])
                return True
        except:
            pass


def Message(msg, text="Press Enter to continue..."):

    def f(ctx):
        click.secho(msg, fg="yellow")
        click.prompt(text)
        return True

    f.__doc__ = "Prints message: %s" % msg
    return f


def StartTimer(ctx):
    """Start timer."""
    ctx["down-time"] = int(time.time())
    return True


def StopTimer(ctx):
    """Stop timer."""
    hours = int(time.time()) - ctx["down-time"]
    sec = hours % 60
    hours //= 60
    min = hours % 60
    hours //= 60
    click.secho(
        "Was offline for %d hours, %d minutes, %d seconds. Check prod."
        % (hours, min, sec)
    )
    click.pause()
    return True


def BuildVersionStr(major, minor, bugfix):
    res = "v%d.%02d" % (major, minor)
    if bugfix:
        res += ".%d" % bugfix
    return res


def LoopStep(func, text="Should I?"):

    def f(ctx):
        while True:
            click.secho("Want to run [%s]" % func.__doc__, fg="yellow")
            if not click.confirm(text):
                return True
            if not func(ctx):
                return False

    f.__doc__ = "Loop: %s" % func.__doc__
    return f


def print_diff_files(dcmp):
    diff = False
    for name in dcmp.diff_files:
        click.secho("* %s" % name, fg="red")
        diff = True
    for name in dcmp.left_only:
        click.secho("- %s" % name, fg="red")
        diff = True
    for name in dcmp.right_only:
        click.secho("+ %s" % name, fg="red")
        diff = True
    for sub_dcmp in dcmp.subdirs.values():
        diff = print_diff_files(sub_dcmp) or diff
    return diff


def StagingDiff(filename):

    def f(ctx):
        if filename[-1] == "/":
            d1 = ROOT_DIR / filename
            d2 = STAGING_DIR / filename
            diff = print_diff_files(filecmp.dircmp(d1, d2, ["__pycache__"]))
            if not diff:
                return True
        else:
            t1 = open(ROOT_DIR / filename).read().split("\n")
            t2 = open(STAGING_DIR / filename).read().split("\n")
            diff = list(difflib.context_diff(t1, t2))
            if not diff:
                return True
            click.secho("File %s does not match:" % filename, fg="red", bold=True)
            for line in diff:
                click.secho(line.rstrip(), fg="red")
        if click.confirm("Do you want to continue?"):
            return True
        else:
            raise click.Abort

    f.__doc__ = "Comparing %s" % filename
    return f


def ChDir(whereto):

    def f(ctx):
        os.chdir(whereto)
        ctx["chdir"] = whereto
        return True

    f.__doc__ = "Change directory to %s" % whereto
    return f


def CreateStaging(ctx):
    """Create staging directory"""
    os.mkdir(STAGING_DIR)
    return True


def KillStaging(ctx):
    """Remove staging directory is exists"""
    RunCmdStep("uwsgi --stop /tmp/uwsgi-ifdb-staging.pid")(ctx)
    if STAGING_DIR.isdir():
        shutil.rmtree(STAGING_DIR)
    return True


p = Pipeline()
cli(obj={"pipeline": p})
