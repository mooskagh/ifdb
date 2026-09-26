import html
import json
import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile

from core.archives import ArchiveError, extract_archive, open_archive
from play.blueprint import (
    BlueprintSpec,
    GenerateResult,
    GenerateSpec,
    insert_telemetry,
)

ASSETS_DIR = Path(__file__).parent / "assets"

_RELEASE_NAME = re.compile(r"^instead-js-(?P<version>\d+(?:\.\d+)*)\.zip$")
_GAMEFILE_NAMES = frozenset(("main.lua", "main3.lua"))
_IMAGE_EXTENSIONS = frozenset((
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
))
_TITLE_TAG = re.compile(r"<title>[^<]*</title>", re.IGNORECASE)
_MUTE_SETTING = re.compile(r"mute\s*:\s*(?:true|false)")

_NAME_RU_RE = re.compile(r"\$Name\(ru\)\s*:\s*([^$\r\n]+)")
_NAME_RE = re.compile(r"\$Name\s*:\s*([^$\r\n]+)")
_AUTHOR_RE = re.compile(r"\$Author\s*:\s*([^$\r\n]+)")
_VERSION_RE = re.compile(r"\$Version\s*:\s*([^$\r\n]+)")
_INFO_RE = re.compile(r"\$Info\s*:\s*([^$\r\n]+)")

VALID_CONFIG_KEYS = frozenset(("mute",))


def _is_gamefile_member(member: str) -> bool:
    parts = member.replace("\\", "/").split("/")
    parts = [p for p in parts if p and p != "."]
    return len(parts) in (1, 2) and parts[-1] in _GAMEFILE_NAMES


def accepts(filename: Path, **kwargs: object) -> bool:
    try:
        with open_archive(filename) as archive:
            return any(
                _is_gamefile_member(member) for member in archive.namelist()
            )
    except (ArchiveError, OSError):
        return False


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(component) for component in version.split("."))


def _release_paths() -> dict[str, Path]:
    releases: dict[str, Path] = {}
    for path in sorted(ASSETS_DIR.rglob("*.zip"), key=str):
        if not path.is_file():
            continue
        match = _RELEASE_NAME.fullmatch(path.name)
        if match:
            releases[match.group("version")] = path
    return releases


def get_spec() -> BlueprintSpec:
    versions = sorted(_release_paths(), key=_version_key)
    return BlueprintSpec(name="INSTEAD.js", versions=versions)


def _flatten_single_dir(directory: Path) -> None:
    entries = [p for p in directory.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        sub = entries[0]
        temp_move = directory.parent / f".tmp_{sub.name}"
        sub.rename(temp_move)
        for item in temp_move.iterdir():
            shutil.move(str(item), str(directory / item.name))
        temp_move.rmdir()


def _normalize_member_path(member: str) -> Path | None:
    parts = [p for p in member.replace("\\", "/").split("/") if p and p != "."]
    if not parts:
        return None
    if parts[0] == "instead-js":
        parts = parts[1:]
    if not parts or parts[0] in ("games", "__MACOSX"):
        return None
    if parts[-1] in ("README", "list_games.js", ".DS_Store"):
        return None
    return Path(*parts)


def _extract_runtime(
    runtime: ZipFile, stage: Path, title: str | None, mute: bool
) -> None:
    for member in runtime.namelist():
        if member.endswith("/"):
            continue
        rel_path = _normalize_member_path(member)
        if rel_path is None:
            continue

        if rel_path == Path("index.html"):
            raw_html = runtime.read(member).decode("utf-8")
            if title:
                raw_html = _TITLE_TAG.sub(
                    f"<title>{html.escape(title)} - INSTEAD.js</title>",
                    raw_html,
                    count=1,
                )
            if not mute:
                raw_html = _MUTE_SETTING.sub("mute: false", raw_html, count=1)
            html_with_telemetry = insert_telemetry(raw_html)
            (stage / "index.html").write_text(
                html_with_telemetry, encoding="utf-8"
            )
            continue

        target_file = stage / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with runtime.open(member) as src, target_file.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _read_lua_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _publish(stage: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    stage.rename(destination)


def generate(spec: GenerateSpec) -> GenerateResult:
    invalid_keys = set(spec.config) - VALID_CONFIG_KEYS
    if invalid_keys:
        keys_str = ", ".join(sorted(invalid_keys))
        raise ValueError(f"Unsupported config keys for INSTEAD.js: {keys_str}")

    releases = _release_paths()
    if spec.version not in releases:
        raise ValueError(f"Unknown INSTEAD.js version: {spec.version}")

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{spec.destination.name}.", dir=spec.destination.parent
        )
    )
    try:
        mute = bool(spec.config.get("mute", False))
        with ZipFile(releases[spec.version]) as runtime:
            _extract_runtime(runtime, stage, spec.title, mute=mute)

        game_dir = stage / "games" / "game"
        game_dir.mkdir(parents=True)
        extract_archive(spec.game_file, game_dir)
        _flatten_single_dir(game_dir)

        if (game_dir / "main3.lua").is_file():
            stead = 3
            main_file = game_dir / "main3.lua"
        elif (game_dir / "main.lua").is_file():
            stead = 2
            main_file = game_dir / "main.lua"
        else:
            raise ValueError(
                "Game archive does not contain main.lua or main3.lua"
            )

        lua_text = _read_lua_text(main_file)
        game_name = spec.title
        if not game_name:
            match = _NAME_RU_RE.search(lua_text) or _NAME_RE.search(lua_text)
            game_name = match.group(1).strip() if match else "Game"

        author_match = _AUTHOR_RE.search(lua_text)
        version_match = _VERSION_RE.search(lua_text)
        info_match = _INFO_RE.search(lua_text)

        manifest = {
            "game": {
                "name": game_name,
                "details": {
                    "version": version_match.group(1).strip()
                    if version_match
                    else "",
                    "author": author_match.group(1).strip()
                    if author_match
                    else "",
                    "info": info_match.group(1).strip() if info_match else "",
                },
                "stead": stead,
                "theme": (game_dir / "theme.ini").is_file(),
                "preload": [
                    p.relative_to(game_dir).as_posix()
                    for p in sorted(game_dir.rglob("*"))
                    if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
                ],
            }
        }
        (stage / "games" / "games_list.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _publish(stage, spec.destination)
        return GenerateResult(
            player_name="INSTEAD.js",
            player_url="https://github.com/instead-hub/instead-js",
        )
    finally:
        if stage.exists():
            shutil.rmtree(stage)
