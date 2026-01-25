#!/bin/env python3

import difflib
import filecmp
import json
import os
import os.path
import pickle
import re
import shutil
import socket
import sys
import time
import traceback
from pathlib import Path

import django
from django.conf import settings
from django.template import Context, Template
from plumbum import FG, cli, colors, local

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
        print(colors.yellow | f"$ {cmd_line}")
        try:
            local["bash"]["-c", cmd_line] & FG
            # FG execution returns None on success, raises exception on failure
            return True
        except Exception as e:
            print(f"Error executing command: {e}")
            return False

    if doc:
        f.__doc__ = doc
    else:
        f.__doc__ = f"Execution of {cmd_line}"
    return f


def GetFromTemplate(template, dst, params, gen_header=True):
    def f(context):
        cnt = GenerateStringFromTemplate(template, params, gen_header)
        with open(CONFIGS_DIR / dst, "w") as fo:
            fo.write(cnt)
        return True

    f.__doc__ = f"Generate {dst} from template"
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
            for x in GenerateStringFromTemplate(template, parms, False).split(
                "\n"
            )
        ]
        diff = list(difflib.context_diff(tpl, cnt))
        if not diff:
            return True
        print(colors.red | colors.bold | "Regenerated file does not match:")
        for line in diff:
            print(colors.red | line.rstrip())

    f.__doc__ = f"Check file {dst} with template"
    return f


def JumpIfExists(var, if_true=1, if_false=1):
    def f(ctx):
        jmp = None
        if var in ctx:
            print(
                colors.yellow
                | f"{var} exists and equal to {ctx[var]}, jumping {if_true:+d}"
            )
            jmp = if_true
        else:
            print(
                colors.yellow
                | f"{var} is not in context, jumping {if_false:+d}"
            )
            jmp = if_false
        if jmp == 1:
            return True
        else:
            raise Jump(jmp)

    f.__doc__ = f"Jump {if_true:+d} if {var} exists else jump {if_false:+d}"
    return f


def Message(msg, text="Press Enter to continue..."):
    def f(ctx):
        print(colors.yellow | msg)
        input(text)
        return True

    f.__doc__ = f"Prints message: {msg}"
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
    print(
        f"Was offline for {hours} hours, {min} minutes, {sec} seconds. "
        "Check prod."
    )
    input("Press Enter to continue...")
    return True


def ChDir(whereto):
    def f(ctx):
        os.chdir(whereto)
        ctx["chdir"] = whereto
        return True

    f.__doc__ = f"Change directory to {whereto}"
    return f


def CreateStaging(ctx):
    """Create staging directory"""
    os.mkdir(STAGING_DIR)
    return True


def KillStaging(ctx):
    """Remove staging directory is exists"""
    RunCmdStep("uwsgi --stop /tmp/uwsgi-ifdb-staging.pid")(ctx)
    if STAGING_DIR.is_dir():
        shutil.rmtree(STAGING_DIR)
    return True


def LoopStep(func, text="Should I?"):
    def f(ctx):
        while True:
            print(colors.yellow | f"Want to run [{func.__doc__}]")
            if input(f"{text} (y/n): ").lower() != "y":
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
            print(
                colors.red | colors.bold | f"File {filename} does not match:"
            )
            for line in diff:
                print(colors.red | line.rstrip())
        if input("Do you want to continue? (y/n): ").lower() == "y":
            return True
        else:
            print("Aborted")
            sys.exit(1)

    f.__doc__ = f"Comparing {filename}"
    return f


def GetCurrentVersion():
    version_re = re.compile(r"v(\d+)\.(\d+)(?:\.(\d+))?")
    cnt = open(DISTRIB_DIR / "version.txt").read().strip()
    m = version_re.match(cnt)
    if not m:
        print(
            colors.red
            | f"version.txt contents is [{cnt}], doesn't parse as version"
        )
        return None
    return (
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)) if m.group(3) else 0,
    )


def BuildVersionStr(major, minor, bugfix):
    res = f"v{major}.{minor:02d}"
    if bugfix:
        res += f".{bugfix}"
    return res


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
        print(
            f"Current version is {BuildVersionStr(*v)}. "
            "What will be the new one?"
        )
        for i, n in enumerate(variants):
            print(colors.yellow | f"{i + 1}. {BuildVersionStr(*n)}")
        r = input(">>>>>>> ")
        try:
            r = int(r) - 1
            if 0 <= r < len(variants):
                ctx["new-version"] = BuildVersionStr(*variants[r])
                return True
        except Exception:
            pass


def MaybeCreateNewBugfixVersion(ctx):
    """Creates a new bugfix version if needed."""
    if "new-version" in ctx:
        print(
            colors.yellow | f"New version {ctx['new-version']} already known."
        )
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
        f.write(f"{v}")
    if not RunCmdStep("git add version.txt")(ctx):
        return False
    if not RunCmdStep(f'git commit -m "Change version.txt to {v}."')(ctx):
        return False
    if not RunCmdStep(f'git tag -a {v} -m "Adding tag {v}"')(ctx):
        return False
    return True


class DeployApp(cli.Application):
    """Deployment application using Plumbum CLI"""

    VERSION = "1.0"

    start = cli.SwitchAttr(
        "--start", int, default=1, help="Start from step number"
    )
    list_only = cli.Flag("--list", help="List steps only")
    step_by_step = cli.Flag("--steps", help="Run step by step")

    def __init__(self, executable):
        super().__init__(executable)
        self.pipeline = Pipeline()

    def main(self):
        self.pipeline.start = self.start
        self.pipeline.list_only = self.list_only
        self.pipeline.step_by_step = self.step_by_step
        print("Use subcommands: red, green, stage, deploy")


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
            if input("Forgotten state found. Restore? (y/n): ").lower() == "y":
                with open(self.StateFileName(), "rb") as f:
                    self.context = pickle.load(f)
                    if "chdir" in self.context:
                        os.chdir(self.context["chdir"])

    def StoreState(self):
        state_file = self.StateFileName()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "wb") as f:
            pickle.dump(self.context, f)

    def Run(self, cmd_name):
        self.cmd_name = cmd_name
        if self.list_only:
            for i, n in enumerate(self.steps):
                print(colors.green | f"{i + 1:2d}. {n.__doc__}")
            return

        os.system("clear")

        if self.end is None:
            end = len(self.steps)
        self.context["idx"] = self.start - 1

        self.MaybeLoadState()

        while self.start <= (self.context["idx"] + 1) <= end:
            self.StoreState()

            task_f = self.steps[self.context["idx"]]
            try:
                step_info = (
                    colors.green
                    | f"[{self.context['idx'] + 1:2d}/{len(self.steps):2d}]"
                )
                print(f"{step_info} {task_f.__doc__}...")

                if self.step_by_step:
                    if input("Should I run it? (y/n): ").lower() != "y":
                        print("Aborted")
                        sys.exit(1)

                if task_f(self.context):
                    self.context["idx"] += 1
                    continue
            except KeyboardInterrupt:
                sys.exit(1)
            except Jump as jmp:
                self.context["idx"] += jmp.whereto
                jump_info = colors.green | colors.bold | "[ JMP ]"
                print(
                    f"{jump_info} Jumping to {self.context['idx'] + 1} "
                    f"({self.steps[self.context['idx']].__doc__})"
                )
                continue
            except Exception:
                print(colors.red | traceback.format_exc())

            print(colors.red | colors.bold | "[ FAIL ]")
            while True:
                print(colors.cyan | "(retry/ignore/abort)")
                value = input(">>>>>>> ")
                if value == "retry":
                    break
                elif value == "ignore":
                    self.context["idx"] += 1
                    break
                elif value == "abort":
                    sys.exit(1)

        print(colors.green | colors.bold | "The pipeline has finished.")
        if os.path.exists(self.StateFileName()):
            os.remove(self.StateFileName())


@DeployApp.subcommand("red")
class RedCommand(cli.Application):
    """Set maintenance mode"""

    message = cli.SwitchAttr(
        "--message",
        str,
        default="Сайт временно не работает (что-то поломалось).",
        help="Maintenance message",
    )

    def main(self):
        p = Pipeline()
        p.start = self.parent.start
        p.list_only = self.parent.list_only
        p.step_by_step = self.parent.step_by_step

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


@DeployApp.subcommand("green")
class GreenCommand(cli.Application):
    """Exit maintenance mode"""

    def main(self):
        p = Pipeline()
        p.start = self.parent.start
        p.list_only = self.parent.list_only
        p.step_by_step = self.parent.step_by_step

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


@DeployApp.subcommand("stage")
class StageCommand(cli.Application):
    """Create staging environment"""

    tag = cli.SwitchAttr("--tag", str, help="Git tag to stage")

    def main(self):
        p = Pipeline()
        p.start = self.parent.start
        p.list_only = self.parent.list_only
        p.step_by_step = self.parent.step_by_step

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
                f"{virtualenv_dir}/bin/pip install -r "
                f"{DISTRIB_DIR}/requirements.txt --no-cache-dir"
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
                f"{virtualenv_dir}/bin/uwsgi --stop "
                "/tmp/uwsgi-ifdb-staging.pid"
            )
        )
        p.Run("stage")


@DeployApp.subcommand("deploy")
class DeployCommand(cli.Application):
    """Deploy application"""

    hot = cli.Flag("--hot", help="Hot deployment without downtime")
    from_master = cli.SwitchAttr(
        "--from-master", help="Deploy from master branch"
    )

    def main(self):
        if self.from_master is None:
            print(
                colors.red
                | colors.bold
                | "Please specify --from-master or --no-from-master!"
            )
            sys.exit(1)

        p = Pipeline()
        p.start = self.parent.start
        p.list_only = self.parent.list_only
        p.step_by_step = self.parent.step_by_step

        virtualenv_dir = ROOT_DIR / "venv"
        python_dir = virtualenv_dir / "bin/python"

        p.AddStep(
            RunCmdStep(
                f"pg_dump ifdb > "
                f"{BACKUPS_DIR / 'database' / time.strftime('%Y%m%d_%H%M')}"
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
                    {
                        "message": "Сайт обновляется",
                        "timestamp": int(time.time()),
                    },
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
            p.AddStep(
                RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi-kontigr")
            )
            p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-uwsgi-zok"))

        p.AddStep(RunCmdStep("sudo /bin/systemctl stop ifdb-worker"))

        if not self.hot:
            p.AddStep(
                Message(
                    "uWSGI is stopped now. You can break now to do "
                    "manual steps."
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
                    f"{virtualenv_dir}/bin/pip install -r "
                    f"{DISTRIB_DIR}/requirements.txt --no-cache-dir"
                )
            )
            p.AddStep(
                RunCmdStep(f"{python_dir} {DISTRIB_DIR}/manage.py migrate")
            )
            timestamp = time.strftime("%Y%m%d_%H%M-postmigr")
            backup_path = BACKUPS_DIR / "database" / timestamp
            p.AddStep(RunCmdStep(f"pg_dump ifdb > {backup_path}"))

        if self.hot:
            p.AddStep(
                RunCmdStep(
                    f"{python_dir} {DISTRIB_DIR}/manage.py collectstatic"
                )
            )
        else:
            p.AddStep(
                RunCmdStep(
                    f"{python_dir} {DISTRIB_DIR}/manage.py "
                    "collectstatic --clear"
                )
            )
        if not self.hot:
            p.AddStep(
                RunCmdStep(f"{python_dir} {DISTRIB_DIR}/manage.py initifdb")
            )

        if self.hot:
            p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi"))
            p.AddStep(
                RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-kontigr")
            )
            p.AddStep(RunCmdStep("sudo /bin/systemctl restart ifdb-uwsgi-zok"))
        else:
            p.AddStep(RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi"))
            p.AddStep(
                RunCmdStep("sudo /bin/systemctl start ifdb-uwsgi-kontigr")
            )
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
                "Break NOW if anything is wrong",
                "Check PROD and break if needed.",
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


if __name__ == "__main__":
    DeployApp.run()
