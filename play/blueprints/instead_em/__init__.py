import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile

from play.blueprint import BlueprintSpec, GenerateSpec

ASSETS_DIR = Path(__file__).parent / "assets"

_RELEASE_NAME = re.compile(r"^instead-em-(\d+(?:\.\d+)*)\.zip$")
_GAMEFILE_MARKER = re.compile(
    rb'<!--(?P<leading>\s*)<meta name="gamefile" content="game\.zip">'
    rb"(?P<trailing>\s*)-->"
)
_VIEWPORT_FILE = "viewport.css"
_VIEWPORT_SCRIPT_FILE = "viewport.js"
_VIEWPORT_LINK = (
    b'\n    <link rel="stylesheet" type="text/css" href="viewport.css">\n'
)
_VIEWPORT_SCRIPT = (
    b'    <script type="text/javascript" src="viewport.js" defer></script>\n'
)
_RUNTIME_MEMBERS = (
    "instead-em/instead-em.data",
    "instead-em/instead-em.html",
    "instead-em/instead-em.js",
    "instead-em/instead-em.wasm",
    "instead-em/loader-em.js",
    "instead-em/loading-bar.css",
    "instead-em/loading-bar.min.js",
    "instead-em/sdl_instead.svg",
    "instead-em/README",
)
_LAUNCHER_MEMBER = "instead-em/instead-em.html"


def _release_paths() -> dict[str, Path]:
    releases: dict[str, Path] = {}
    for path in sorted(ASSETS_DIR.rglob("*.zip"), key=str):
        if not path.is_file():
            continue

        match = _RELEASE_NAME.fullmatch(path.name)
        if match:
            releases[match.group(1)] = path

    return releases


def get_spec() -> BlueprintSpec:
    versions = sorted(
        _release_paths(),
        key=lambda version: tuple(
            int(component) for component in version.split(".")
        ),
    )
    return BlueprintSpec(name="INSTEAD Emscripten", versions=versions)


def _activate_gamefile_marker(html: bytes) -> bytes:
    match = next(_GAMEFILE_MARKER.finditer(html))
    return (
        html[: match.start()]
        + match.group("leading")
        + b'<meta name="gamefile" content="game.zip">'
        + match.group("trailing")
        + _VIEWPORT_LINK
        + _VIEWPORT_SCRIPT
        + html[match.end() :]
    )


def _write_runtime(runtime: ZipFile, stage: Path) -> None:
    for member_name in _RUNTIME_MEMBERS:
        if member_name == _LAUNCHER_MEMBER:
            html = _activate_gamefile_marker(runtime.read(member_name))
            (stage / "index.html").write_bytes(html)
            continue

        with runtime.open(member_name) as source:
            with (stage / Path(member_name).name).open("wb") as target:
                shutil.copyfileobj(source, target)

    shutil.copyfile(ASSETS_DIR / _VIEWPORT_FILE, stage / _VIEWPORT_FILE)
    shutil.copyfile(
        ASSETS_DIR / _VIEWPORT_SCRIPT_FILE, stage / _VIEWPORT_SCRIPT_FILE
    )


def _publish(stage: Path, destination: Path) -> None:
    if destination.exists():
        destination.rmdir()
    stage.rename(destination)


def generate(spec: GenerateSpec) -> None:
    if spec.config != {}:
        raise ValueError("INSTEAD-EM generation does not support config")

    runtime_path = _release_paths()[spec.version]
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{spec.destination.name}.", dir=spec.destination.parent
        )
    )
    try:
        with ZipFile(runtime_path) as runtime:
            _write_runtime(runtime, stage)
        shutil.copyfile(spec.game_file, stage / "game.zip")
        _publish(stage, spec.destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
