import html
import json
import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from core.archives import (
    ArchiveError,
    extract_archive,
    open_archive,
)
from play.blueprint import (
    BlueprintSpec,
    Compatibility,
    GenerateResult,
    GenerateSpec,
    insert_telemetry,
)
from play.blueprints.urqw.detection import (
    SUPPORTED_EXTENSIONS,
    detect_encoding,
    detect_urq_mode,
)

ASSETS_DIR = Path(__file__).parent / "assets"

_RELEASE_NAME = re.compile(r"^urqw-(?P<version>\d+(?:[-.]\d+)*)\.zip$")
_LAUNCHER_MARKER = b'<script src="dist/bundle.js"></script>'
_TITLE_TAG = re.compile(rb"<title>[^<]*</title>", re.IGNORECASE)

_RUNTIME_FILES = (
    "dist/bundle.js",
    "dist/style.min.css",
    "logo.svg",
    "favicon.png",
    "rss.svg",
)

VALID_CONFIG_KEYS = frozenset((
    "urq_mode",
    "game_encoding",
    "html_support",
    "title",
))
VALID_MODES = frozenset(("urqw", "ripurq", "dosurq", "akurq"))
VALID_ENCODINGS = frozenset(("UTF-8", "CP1251"))

_IGNORED_ROOTS = frozenset(("__MACOSX",))
_IGNORED_NAMES = frozenset((".DS_Store",))


def _split_clean_parts(member: str) -> list[str]:
    return [p for p in member.replace("\\", "/").split("/") if p and p != "."]


def _is_ignored(parts: list[str]) -> bool:
    if not parts:
        return True
    if parts[0] in _IGNORED_ROOTS:
        return True
    if parts[0] in _IGNORED_NAMES or parts[-1] in _IGNORED_NAMES:
        return True
    if parts[-1].startswith("._"):
        return True
    return False


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(component) for component in re.split(r"[-.]", version))


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
    return BlueprintSpec(name="UrqW", versions=versions)


def _check_direct_file_compatibility(
    filename: Path, tags: list[str] | None = None
) -> Compatibility:
    ext = filename.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return Compatibility.NONE

    if tags:
        _, is_fire = detect_urq_mode(tags=tags)
        return Compatibility.PARTIAL if is_fire else Compatibility.FULL

    if ext == ".qst":
        try:
            with filename.open("rb") as f:
                sample_bytes = f.read(65536)
            try:
                sample_text = sample_bytes.decode("utf-8")
            except UnicodeDecodeError:
                sample_text = sample_bytes.decode("cp1251", "replace")
            _, is_fire = detect_urq_mode(content=sample_text)
            return Compatibility.PARTIAL if is_fire else Compatibility.FULL
        except OSError:
            return Compatibility.FULL

    return Compatibility.FULL


def _check_archive_compatibility(
    filename: Path, tags: list[str] | None = None
) -> Compatibility:
    try:
        with open_archive(filename) as archive:
            members = archive.namelist()
    except (ArchiveError, OSError):
        return Compatibility.NONE

    has_urq = False
    has_fireurq_name = False
    primary_qst_member: str | None = None
    for m in members:
        if m.endswith("/"):
            continue
        parts = _split_clean_parts(m)
        if _is_ignored(parts):
            continue
        m_lower = m.lower()
        if any(m_lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            has_urq = True
            if primary_qst_member is None and m_lower.endswith(".qst"):
                primary_qst_member = m
        if "fireurq" in m_lower or "furq" in m_lower:
            has_fireurq_name = True

    if not has_urq:
        return Compatibility.NONE

    if tags:
        _, is_fire = detect_urq_mode(tags=tags)
        return Compatibility.PARTIAL if is_fire else Compatibility.FULL

    if has_fireurq_name:
        return Compatibility.PARTIAL

    if primary_qst_member:
        try:
            if is_zipfile(filename):
                with ZipFile(filename) as zf:
                    actual_member = next(
                        (
                            n
                            for n in zf.namelist()
                            if n.replace("\\", "/") == primary_qst_member
                        ),
                        primary_qst_member,
                    )
                    sample_bytes = zf.read(actual_member)[:65536]
                    try:
                        sample_text = sample_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        sample_text = sample_bytes.decode("cp1251", "replace")
                    _, is_fire = detect_urq_mode(content=sample_text)
                    if is_fire:
                        return Compatibility.PARTIAL
        except Exception:
            pass

    return Compatibility.FULL


def accepts(
    filename: Path, *, tags: list[str] | None = None, **kwargs: object
) -> Compatibility:
    if not filename.is_file():
        return Compatibility.NONE

    if filename.suffix.lower() in SUPPORTED_EXTENSIONS:
        return _check_direct_file_compatibility(filename, tags=tags)

    return _check_archive_compatibility(filename, tags=tags)


def _patch_index_html(html_bytes: bytes, title: str) -> bytes:
    if _LAUNCHER_MARKER not in html_bytes:
        raise ValueError("Could not find bundle script tag in UrqW index.html")

    script_inject = b'<script>var urqw_default_game = "game";</script>'
    patched = html_bytes.replace(
        _LAUNCHER_MARKER, script_inject + _LAUNCHER_MARKER, 1
    )

    escaped_title = html.escape(title).encode("utf-8")
    title_replacement = b"<title>" + escaped_title + b"</title>"
    patched = _TITLE_TAG.sub(title_replacement, patched, count=1)
    return patched


def _write_runtime(runtime_path: Path, stage: Path, title: str) -> None:
    with ZipFile(runtime_path) as runtime:
        index_raw = runtime.read("index.html")
        patched_index = _patch_index_html(index_raw, title)
        (stage / "index.html").write_bytes(insert_telemetry(patched_index))

        for member in _RUNTIME_FILES:
            target_path = stage / member
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with runtime.open(member) as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

        for member in runtime.namelist():
            if member.startswith("fonts/") and not member.endswith("/"):
                target_path = stage / member
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with (
                    runtime.open(member) as src,
                    target_path.open("wb") as dst,
                ):
                    shutil.copyfileobj(src, dst)

    fonts_dir = ASSETS_DIR / "fonts"
    if fonts_dir.is_dir():
        shutil.copytree(fonts_dir, stage / "fonts", dirs_exist_ok=True)


def _flatten_single_dir(directory: Path) -> None:
    """If directory contains only one sub-directory, move its contents up."""
    entries = [p for p in directory.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        sub = entries[0]
        temp_move = directory.parent / f".tmp_{sub.name}"
        sub.rename(temp_move)
        for item in temp_move.iterdir():
            shutil.move(str(item), str(directory / item.name))
        temp_move.rmdir()


def _unpack_nested_qsz(directory: Path) -> None:
    """Unpack any .qsz archives within directory in place."""
    for qsz in list(directory.rglob("*.qsz")):
        extract_dir = qsz.parent
        extract_archive(qsz, extract_dir)
        qsz.unlink()


def _prepare_game_zip(
    game_file: Path,
    output_zip: Path,
    config: dict[str, object],
    title: str,
    tags: list[str],
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        game_stage = temp_dir / "game"
        game_stage.mkdir()

        ext = game_file.suffix.lower()
        if ext in (".qst", ".qs1", ".qs2"):
            shutil.copyfile(game_file, game_stage / game_file.name)
        else:
            extract_archive(game_file, game_stage)
            _unpack_nested_qsz(game_stage)
            _flatten_single_dir(game_stage)

        # Collect quest text to analyze encoding & mode
        quest_files = sorted(
            [
                p
                for p in game_stage.rglob("*")
                if p.is_file() and p.suffix.lower() in (".qst", ".qs1", ".qs2")
            ],
            key=lambda p: (0 if p.name.startswith("_") else 1, p.name),
        )

        sample_bytes = b""
        for qf in quest_files:
            if qf.suffix.lower() == ".qst":
                sample_bytes += qf.read_bytes()[:32768]
                if len(sample_bytes) > 65536:
                    break

        detected_enc = (
            detect_encoding(sample_bytes) if sample_bytes else "CP1251"
        )
        if detected_enc == "CP866":
            # Transcode .qst files from CP866 to UTF-8 for UrqW
            for qf in quest_files:
                if qf.suffix.lower() == ".qst":
                    try:
                        content_866 = qf.read_bytes().decode("cp866")
                        qf.write_text(content_866, encoding="utf-8")
                    except Exception:
                        pass
            resolved_encoding = "UTF-8"
        else:
            resolved_encoding = detected_enc

        if "game_encoding" in config:
            resolved_encoding = str(config["game_encoding"])

        # Decode sample text for mode detection
        if sample_bytes:
            try:
                sample_text = sample_bytes.decode(
                    resolved_encoding.lower(), "replace"
                )
            except Exception:
                sample_text = sample_bytes.decode("cp1251", "replace")
        else:
            sample_text = ""

        if "urq_mode" in config:
            resolved_mode = str(config["urq_mode"])
        else:
            resolved_mode, _ = detect_urq_mode(tags=tags, content=sample_text)

        manifest: dict[str, object] = {
            "manifest_version": 1,
            "urqw_title": title,
            "urq_mode": resolved_mode,
            "game_encoding": resolved_encoding,
            "html_support": bool(config.get("html_support", True)),
        }

        (game_stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output_zip, "w", compression=ZIP_DEFLATED) as zf:
            for file_path in sorted(game_stage.rglob("*")):
                if file_path.is_file():
                    arcname = file_path.relative_to(game_stage)
                    zf.write(file_path, arcname=str(arcname))


def _publish(stage: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    stage.rename(destination)


def generate(spec: GenerateSpec) -> GenerateResult:
    for key in spec.config:
        if key not in VALID_CONFIG_KEYS:
            raise ValueError(
                f"UrqW generation does not support config key: {key}"
            )

    if (
        "urq_mode" in spec.config
        and spec.config["urq_mode"] not in VALID_MODES
    ):
        raise ValueError(f"Invalid urq_mode: {spec.config['urq_mode']}")

    if (
        "game_encoding" in spec.config
        and spec.config["game_encoding"] not in VALID_ENCODINGS
    ):
        raise ValueError(
            f"Invalid game_encoding: {spec.config['game_encoding']}"
        )

    if "html_support" in spec.config and not isinstance(
        spec.config["html_support"], bool
    ):
        raise ValueError(
            f"html_support must be a boolean: {spec.config['html_support']}"
        )

    releases = _release_paths()
    if spec.version not in releases:
        raise ValueError(f"Unknown UrqW version: {spec.version}")
    runtime_path = releases[spec.version]

    resolved_title = str(
        spec.config.get("title") or spec.title or spec.game_file.stem
    )

    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{spec.destination.name}.", dir=spec.destination.parent
        )
    )
    try:
        _write_runtime(runtime_path, stage, resolved_title)
        quests_dir = stage / "quests"
        _prepare_game_zip(
            game_file=spec.game_file,
            output_zip=quests_dir / "game.zip",
            config=spec.config,
            title=resolved_title,
            tags=spec.tags,
        )
        _publish(stage, spec.destination)
        return GenerateResult(
            player_name="UrqW",
            player_url="https://urqw.github.io/UrqW/",
        )
    finally:
        if stage.exists():
            shutil.rmtree(stage)
