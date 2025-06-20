#!/usr/bin/env python3

import difflib
import filecmp
import json
import os
import os.path
import pickle
import re
import shlex
import shutil
import socket
import sys
import time
import traceback
from pathlib import Path

import django
from django.conf import settings
from django.template import Context, Template
from plumbum import cli, local, colors
from plumbum.commands import ProcessExecutionError

# --- Django Setup (unchanged) ---
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.dirname(os.path.realpath(__file__))],
    }
]
settings.configure(TEMPLATES=TEMPLATES)
django.setup()

# --- Global Constants (unchanged) ---
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
    """Factory for a pipeline step that runs a shell command."""

    def f(context):
        print(colors.yellow | f"$ {cmd_line}")
        try:
            # Use shlex.split to handle quoted arguments correctly
            args = shlex.split(cmd_line)
            cmd = local[args[0]]
            cmd[args[1:]].run_foreground()
            return True
        except (ProcessExecutionError, FileNotFoundError) as e:
            print(colors.red | f"Error executing command: {e}")
            print(f"The command was: {colors.yellow | cmd_line}")
            return False

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
            print(colors.red | f"Header not found in {dst}")
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
        print(colors.bold & colors.red | "Regenerated file does not match:")
        for line in diff:
            print(colors.red | line.rstrip())
        return False

    f.__doc__ = "Check file %s with template" % dst
    return f


def RetryPrompt():
    while True:
        print(colors.cyan | "(retry/ignore/abort)")
        value = cli.prompt("", prompt_suffix=">>>>>>> ")
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
            if cli.ask("Forgotten state found. Restore?"):
                with open(self.StateFileName(), "rb") as f:
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
                print(f"{colors.green | (i + 1):>2}. {n.__doc__}")
            return
        cli.term.clear()

        if self.end is None:
            self.end = len(self.steps)
        self.context["idx"] = self.start - 1

        self.MaybeLoadState()

        while self.start <= (self.context["idx"] + 1) <= self.end:
            self.StoreState()

            task_f = self.steps[self.context["idx"]]
            try:
                print(
                    (
                        colors.green
                        | f"[{self.context['idx'] + 1:2d}/{len(self.steps):2d}]"
                    )
                    + f" {task_f.__doc__}..."
                )
                if self.step_by_step:
                    if not cli.ask("Should I run it?"):
                        raise cli.Abort
                if task_f(self.context):
                    self.context["idx"] += 1
                    continue
            except cli.Abort:
                raise
            except Jump as jmp:
                self.context["idx"] += jmp.whereto
                print(
                    colors.bold & colors.green
                    | f"[ JMP ] Jumping to {self.context['idx'] + 1} ({self.steps[self.context['idx']].__doc__})"
                )
                continue
            except Exception:
                print(colors.red | traceback.format_exc())

            print(colors.bold & colors.red | "[ FAIL ]")
            if not RetryPrompt():
                self.context["idx"] += 1
        print(colors.bold & colors.green | "The pipeline has finished.")
        os.remove(self.StateFileName())


# ==============================================================================
# Plumbum Application Definition
# ==============================================================================


class DeployTool(cli.Application):
    """A deployment and management script for the IFDB project."""

    PROGNAME = os.path.basename(__file__)
    pipeline = Pipeline()

    # --- Global options ---
    start = cli.SwitchAttr(["s", "start"], int, default=1, help="Step to start from")
    list_only = cli.Flag(["l", "list"], help="List all steps and exit")
    step_by_step = cli.Flag(["steps"], help="Run in step-by-step confirmation mode")

    def _setup_pipeline(self):
        """Configures the pipeline instance from the global command-line switches."""
        self.pipeline.start = self.start
        self.pipeline.list_only = self.list_only
        self.pipeline.step_by_step = self.step_by_step
        return self.pipeline

    def main(self):
        """This method is run if no subcommand is given."""
        print(
            colors.red | "No command specified. Use --help to see available commands."
        )
        return 1

    # --------------------------------------------------------------------------
    # RED command
    # --------------------------------------------------------------------------
    @cli.Application.subcommand("red")
    class RedCommand(cli.Application):
        """Put the site into maintenance mode (show a wall page)."""

        message = cli.SwitchAttr(
            ["m", "message"],
            str,
            default="Сайт временно не работает (что-то поломалось).",
            help="The message to display on the maintenance page.",
        )

        def main(self):
            p = self.parent._setup_pipeline()
            p.AddStep(
                GetFromTemplate(
                    "wallpage.tpl",
                    "wallpage/index.html",
                    {"message": self.message, "timestamp": int(time.time())},
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

    # --------------------------------------------------------------------------
    # GREEN command
    # --------------------------------------------------------------------------
    @cli.Application.subcommand("green")
    class GreenCommand(cli.Application):
        """Bring the site back online from maintenance mode."""

        def main(self):
            p = self.parent._setup_pipeline()
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

    # --------------------------------------------------------------------------
    # STAGE command
    # --------------------------------------------------------------------------
    @cli.Application.subcommand("stage")
    class StageCommand(cli.Application):
        """Prepare and run a staging version of the site."""

        tag = cli.SwitchAttr(
            ["t", "tag"],
            str,
            default=None,
            help="The git tag or branch to check out for staging. Defaults to the current branch.",
        )

        def main(self):
            p = self.parent._setup_pipeline()
            virtualenv_dir = STAGING_DIR / "venv"
            python_dir = virtualenv_dir / "bin/python"

            p.AddStep(KillStaging)
            p.AddStep(CreateStaging)
            p.AddStep(
                RunCmdStep(
                    f"git clone git@bitbucket.org:mooskagh/ifdb.git {DISTRIB_DIR}"
                )
            )
            p.AddStep(ChDir(DISTRIB_DIR))
            p.AddStep(RunCmdStep(f"git checkout -b staging {self.tag or ''}"))
            p.AddStep(RunCmdStep(f"python3 -m venv {virtualenv_dir}"))
            p.AddStep(StagingDiff(PROD_SUBDIR / "requirements.txt"))
            p.AddStep(
                RunCmdStep(
                    f"{virtualenv_dir}/bin/pip install -r {DISTRIB_DIR}/requirements.txt --no-cache-dir"
                )
            )
            p.AddStep(StagingDiff(PROD_SUBDIR / "games/migrations/"))
            p.AddStep(StagingDiff(PROD_SUBDIR / "core/migrations/"))
            p.AddStep(
                StagingDiff(PROD_SUBDIR / "games/management/commands/initifdb.py")
            )
            p.AddStep(StagingDiff(PROD_SUBDIR / "scripts/nginx.tpl"))
            p.AddStep(
                RunCmdStep(
                    f"{python_dir} {DISTRIB_DIR}/manage.py collectstatic --clear"
                )
            )
            p.AddStep(StagingDiff("static/"))
            p.AddStep(RunCmdStep(f"chmod -R a+rX {STAGING_DIR}/static"))
            p.AddStep(
                RunCmdStep(
                    f"{virtualenv_dir}/bin/uwsgi {CONFIGS_DIR}/uwsgi-staging.ini"
                )
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
                RunCmdStep(
                    f"{virtualenv_dir}/bin/uwsgi --stop /tmp/uwsgi-ifdb-staging.pid"
                )
            )
            p.Run("stage")

    # --------------------------------------------------------------------------
    # DEPLOY command
    # --------------------------------------------------------------------------
    @cli.Application.subcommand("deploy")
    class DeployCommand(cli.Application):
        """Deploy a new version to production."""

        hot = cli.Flag(
            "--hot", help="Perform a hot-deploy (restarts uWSGI but no downtime)."
        )
        from_master = cli.Flag(
            "--from-master",
            help="Merge from master before deploying.",
            group="Merge Strategy",
        )
        no_from_master = cli.Flag(
            "--no-from-master", help="Do not merge from master.", group="Merge Strategy"
        )

        def main(self):
            if self.from_master == self.no_from_master:
                print(
                    colors.bold & colors.red
                    | "Error: Please specify either --from-master or --no-from-master, but not both."
                )
                raise cli.Abort()

            p = self.parent._setup_pipeline()
            virtualenv_dir = ROOT_DIR / "venv"
            python_dir = virtualenv_dir / "bin/python"

            p.AddStep(
                RunCmdStep(
                    f"pg_dump ifdb > {BACKUPS_DIR / 'database' / time.strftime('%Y%m%d_%H%M')}"
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

            if not self.hot:
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

            if not self.hot:
                p.AddStep(
                    Message(
                        "uWSGI is stopped now. You can break now to do manual steps."
                    )
                )

            p.AddStep(RunCmdStep("git checkout release"))
            p.AddStep(RunCmdStep("git pull"))

            if self.from_master:
                p.AddStep(RunCmdStep("git fetch origin master:master"))
                p.AddStep(RunCmdStep("git merge --no-ff master"))
                p.AddStep(GetNextVersion)

            if not self.hot:
                p.AddStep(
                    RunCmdStep(
                        f"{virtualenv_dir}/bin/pip install -r {DISTRIB_DIR}/requirements.txt --no-cache-dir"
                    )
                )
                p.AddStep(RunCmdStep(f"{python_dir} {DISTRIB_DIR}/manage.py migrate"))
                p.AddStep(
                    RunCmdStep(
                        f"pg_dump ifdb > {BACKUPS_DIR / 'database' / time.strftime('%Y%m%d_%H%M-postmigr')}"
                    )
                )

            if self.hot:
                p.AddStep(
                    RunCmdStep(f"{python_dir} {DISTRIB_DIR}/manage.py collectstatic")
                )
            else:
                p.AddStep(
                    RunCmdStep(
                        f"{python_dir} {DISTRIB_DIR}/manage.py collectstatic --clear"
                    )
                )
            if not self.hot:
                p.AddStep(RunCmdStep(f"{python_dir} {DISTRIB_DIR}/manage.py initifdb"))

            if self.hot:
                p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi"))
                p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-kontigr"))
                p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-zok"))
            else:
                p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi"))
                p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-kontigr"))
                p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-zok"))
            p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-worker"))

            if not self.hot:
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

            if not self.hot:
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
                Message(
                    "Break NOW if anything is wrong", "Check PROD and break if needed."
                )
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

            if self.from_master:
                p.AddStep(RunCmdStep("git fetch . release:master"))

            p.AddStep(RunCmdStep("git push --all origin"))
            p.AddStep(RunCmdStep("git push --tags origin"))

            p.Run("deploy")


# --- Pipeline Step Helper Functions ---


def JumpIfExists(var, if_true=1, if_false=1):
    def f(ctx):
        jmp = None
        if var in ctx:
            print(
                colors.yellow
                | f"{var} exists and equal to {ctx[var]}, jumping %+d" % if_true
            )
            jmp = if_true
        else:
            print(colors.yellow | f"{var} is not in context, jumping %+d" % if_false)
            jmp = if_false
        if jmp == 1:
            return True
        else:
            raise Jump(jmp)

    f.__doc__ = f"Jump %+d if {var} exists else jump %+d" % (if_true, if_false)
    return f


def MaybeCreateNewBugfixVersion(ctx):
    """Creates a new bugfix version if needed."""
    if "new-version" in ctx:
        print(colors.yellow | f"New version {ctx['new-version']} already known.")
        return True
    if RunCmdStep("git describe --exact-match HEAD")(ctx):
        print(colors.yellow | "No changes since last version.")
        return True
    v = GetCurrentVersion()
    v = BuildVersionStr(v[0], v[1], v[2] + 1)
    print(colors.yellow | f"New version is {v}.")
    ctx["new-version"] = v
    return True


def WriteVersionConfigAndGitTag(ctx):
    """Write current version into config."""
    v = ctx["new-version"]
    with open(DISTRIB_DIR / "version.txt", "w") as f:
        f.write("%s" % v)
    if not RunCmdStep("git add version.txt")(ctx):
        return False
    if not RunCmdStep(f'git commit -m "Change version.txt to {v}."')(ctx):
        return False
    if not RunCmdStep(f'git tag -a {v} -m "Adding tag {v}"')(ctx):
        return False
    return True


def GetCurrentVersion():
    version_re = re.compile(r"v(\d+)\.(\d+)(?:\.(\d+))?")
    cnt = open(DISTRIB_DIR / "version.txt").read().strip()
    m = version_re.match(cnt)
    if not m:
        print(colors.red | f"version.txt contents is [{cnt}], doesn't parse as version")
        return None
    return (
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)) if m.group(3) else 0,
    )


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
        print(f"Current version is {BuildVersionStr(*v)}. What will be the new one?")
        for i, n in enumerate(variants):
            print(colors.yellow | f"{i + 1}. {BuildVersionStr(*n)}")
        r = cli.prompt("", prompt_suffix=">>>>>>> ")
        try:
            r = int(r) - 1
            if 0 <= r < len(variants):
                ctx["new-version"] = BuildVersionStr(*variants[r])
                return True
        except (ValueError, IndexError):
            pass


def Message(msg, text="Press Enter to continue..."):
    def f(ctx):
        print(colors.yellow | msg)
        cli.prompt(text)
        return True

    f.__doc__ = f"Prints message: {msg}"
    return f


def StartTimer(ctx):
    """Start timer."""
    ctx["down-time"] = int(time.time())
    return True


def StopTimer(ctx):
    """Stop timer."""
    duration = int(time.time()) - ctx["down-time"]
    sec = duration % 60
    duration //= 60
    min = duration % 60
    hours = duration // 60
    print(f"Was offline for {hours} hours, {min} minutes, {sec} seconds. Check prod.")
    cli.prompt("Press ENTER to continue...")
    return True


def BuildVersionStr(major, minor, bugfix):
    res = f"v{major}.{minor:02d}"
    if bugfix:
        res += f".{bugfix}"
    return res


def LoopStep(func, text="Should I?"):
    def f(ctx):
        while True:
            print(colors.yellow | f"Want to run [{func.__doc__}]")
            if not cli.ask(text):
                return True
            if not func(ctx):
                return False

    f.__doc__ = f"Loop: {func.__doc__}"
    return f


def print_diff_files(dcmp):
    diff = False
    for name in dcmp.diff_files:
        print(colors.red | f"* {name}")
        diff = True
    for name in dcmp.left_only:
        print(colors.red | f"- {name}")
        diff = True
    for name in dcmp.right_only:
        print(colors.red | f"+ {name}")
        diff = True
    for sub_dcmp in dcmp.subdirs.values():
        diff = print_diff_files(sub_dcmp) or diff
    return diff


def StagingDiff(filename):
    def f(ctx):
        path_str = str(filename)
        if path_str.endswith("/"):
            d1 = ROOT_DIR / filename
            d2 = STAGING_DIR / filename
            diff = print_diff_files(filecmp.dircmp(d1, d2, ["__pycache__"]))
            if not diff:
                return True
        else:
            with open(ROOT_DIR / filename) as f1, open(STAGING_DIR / filename) as f2:
                t1 = f1.read().splitlines()
                t2 = f2.read().splitlines()
            diff = list(difflib.context_diff(t1, t2))
            if not diff:
                return True
            print(colors.bold & colors.red | f"File {filename} does not match:")
            for line in diff:
                print(colors.red | line.rstrip())

        if cli.ask("Do you want to continue?"):
            return True
        else:
            raise cli.Abort()

    f.__doc__ = f"Comparing {filename}"
    return f


def ChDir(whereto):
    def f(ctx):
        os.chdir(whereto)
        ctx["chdir"] = str(whereto)
        return True

    f.__doc__ = f"Change directory to {whereto}"
    return f


def CreateStaging(ctx):
    """Create staging directory"""
    os.mkdir(STAGING_DIR)
    return True


def KillStaging(ctx):
    """Remove staging directory if it exists"""
    # This command may fail if the pid file doesn't exist; we ignore the result.
    RunCmdStep("uwsgi --stop /tmp/uwsgi-ifdb-staging.pid")(ctx)
    if STAGING_DIR.is_dir():
        shutil.rmtree(STAGING_DIR)
    return True


if __name__ == "__main__":
    DeployTool.run()
