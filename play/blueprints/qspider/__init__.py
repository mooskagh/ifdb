import html
import os
import re
import shutil
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from core.archives import (
    ArchiveError,
    extract_archive,
    open_archive,
)
from play.blueprint import BlueprintSpec, Compatibility, GenerateSpec
from play.blueprints.qspider.detection import (
    ALL_QSP_EXTENSIONS,
    LEGACY_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    detect_qsp_mode,
    find_primary_qsp_file,
    is_ignored,
    is_qsp_header,
    is_tads2_header,
    split_clean_parts,
)

ASSETS_DIR = Path(__file__).parent / "assets"

_RELEASE_NAME = re.compile(
    r"^qspider-(?:player-standalone-)?(?P<version>\d+(?:[-.]\d+)*)\.zip$"
)
_TITLE_TAG = re.compile(rb"<title>[^<]*</title>", re.IGNORECASE)

VALID_CONFIG_KEYS = frozenset((
    "mode",
    "title",
    "entrypoint",
    "save_slots",
    "width",
    "height",
))
VALID_MODES = frozenset(("classic", "aero"))


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
    return BlueprintSpec(name="qSpider", versions=versions)


def _check_direct_file_compatibility(
    filename: Path, tags: list[str] | None = None
) -> Compatibility:
    ext = filename.suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return Compatibility.FULL

    if ext in LEGACY_EXTENSIONS:
        try:
            with filename.open("rb") as f:
                header = f.read(64)
        except OSError:
            header = b""

        if is_tads2_header(header):
            return Compatibility.NONE
        if tags:
            lower_tags = [t.lower() for t in tags]
            if any("tads" in t for t in lower_tags):
                return Compatibility.NONE
            if any("qsp" in t for t in lower_tags):
                return Compatibility.FULL

        if is_qsp_header(header):
            return Compatibility.FULL

    return Compatibility.NONE


def _check_archive_compatibility(
    filename: Path, tags: list[str] | None = None
) -> Compatibility:
    try:
        with open_archive(filename) as archive:
            members = archive.namelist()
    except (ArchiveError, OSError):
        return Compatibility.NONE

    has_qsp = False
    has_legacy_gam = False
    has_cfg = False

    for m in members:
        if m.endswith("/"):
            continue
        parts = split_clean_parts(m)
        if is_ignored(parts):
            continue
        m_lower = parts[-1].lower()
        if any(m_lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            has_qsp = True
        elif any(m_lower.endswith(ext) for ext in LEGACY_EXTENSIONS):
            has_legacy_gam = True
        elif m_lower == "game.cfg":
            has_cfg = True

    if has_qsp or has_cfg:
        return Compatibility.FULL

    if has_legacy_gam:
        if tags:
            lower_tags = [t.lower() for t in tags]
            if any("tads" in t for t in lower_tags):
                return Compatibility.NONE
            if any("qsp" in t for t in lower_tags):
                return Compatibility.FULL
        if is_zipfile(filename):
            try:
                with ZipFile(filename) as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(".gam"):
                            header = zf.read(name)[:64]
                            if is_tads2_header(header):
                                return Compatibility.NONE
                            if is_qsp_header(header):
                                return Compatibility.FULL
            except Exception:
                pass
        return (
            Compatibility.FULL
            if (tags and any("qsp" in t.lower() for t in tags))
            else Compatibility.NONE
        )

    if tags and any(
        k in t.lower() for t in tags for k in ("qsp", "aeroqsp", "qspider")
    ):
        return Compatibility.FULL

    return Compatibility.NONE


def accepts(
    filename: Path, *, tags: list[str] | None = None, **kwargs: object
) -> Compatibility:
    if not filename.is_file():
        return Compatibility.NONE

    if filename.suffix.lower() in ALL_QSP_EXTENSIONS:
        return _check_direct_file_compatibility(filename, tags=tags)

    return _check_archive_compatibility(filename, tags=tags)


def _patch_index_html(html_bytes: bytes, title: str) -> bytes:
    escaped_title = html.escape(title).encode("utf-8")
    title_replacement = b"<title>" + escaped_title + b"</title>"
    return _TITLE_TAG.sub(title_replacement, html_bytes, count=1)


def _write_runtime(runtime_path: Path, stage: Path, title: str) -> None:
    with ZipFile(runtime_path) as runtime:
        for member in runtime.infolist():
            if member.filename.startswith("game/"):
                continue
            if member.is_dir():
                (stage / member.filename).mkdir(parents=True, exist_ok=True)
                continue

            target_path = stage / member.filename
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if member.filename == "index.html":
                index_raw = runtime.read(member.filename)
                target_path.write_bytes(_patch_index_html(index_raw, title))
            else:
                with (
                    runtime.open(member) as src,
                    target_path.open("wb") as dst,
                ):
                    shutil.copyfileobj(src, dst)


def _flatten_single_dir(directory: Path) -> None:
    """If directory contains only one sub-directory, move its contents up."""
    while True:
        entries = [p for p in directory.iterdir() if p.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            sub = entries[0]
            temp_move = directory.parent / f".tmp_{sub.name}"
            sub.rename(temp_move)
            for item in temp_move.iterdir():
                shutil.move(str(item), str(directory / item.name))
            temp_move.rmdir()
        else:
            break


def _unpack_nested_aqsp(directory: Path) -> None:
    for aqsp in list(directory.rglob("*.aqsp")):
        extract_dir = aqsp.parent
        with ZipFile(aqsp) as zf:
            zf.extractall(extract_dir)
        aqsp.unlink()


def _fix_mojibake_names(directory: Path) -> None:
    """Fix Cyrillic filenames misdecoded as CP437 by Python's zipfile."""
    for path in sorted(
        directory.rglob("*"), key=lambda p: len(p.parts), reverse=True
    ):
        try:
            raw = path.name.encode("cp437")
            fixed_name: str | None = None
            try:
                fixed_name = raw.decode("cp866")
            except UnicodeDecodeError:
                try:
                    fixed_name = raw.decode("cp1251")
                except UnicodeDecodeError:
                    pass
            if fixed_name and fixed_name != path.name:
                target = path.parent / fixed_name
                if not target.exists():
                    path.rename(target)
        except (UnicodeEncodeError, OSError):
            pass


def _generate_game_cfg(
    game_id: str,
    title: str,
    entrypoint: str,
    mode: str,
    save_slots: int | None = None,
    aero_width: int | None = None,
    aero_height: int | None = None,
) -> str:
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_file = entrypoint.replace("\\", "/")
    lines = [
        "[[game]]",
        f'id = "{game_id}"',
        f'title = "{safe_title}"',
        f'file = "{safe_file}"',
        f'mode = "{mode}"',
    ]
    if save_slots is not None:
        lines.append(f"save_slots = {int(save_slots)}")
    if mode == "aero" and aero_width is not None and aero_height is not None:
        lines.extend([
            "",
            "[game.aero]",
            f"width = {int(aero_width)}",
            f"height = {int(aero_height)}",
        ])
    return "\n".join(lines) + "\n"


_ASSET_EXTENSIONS = (
    r"\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg|"
    r"mp3|ogg|wav|mid|midi|mod|s3m|xm|it|"
    r"avi|mp4|webm|ogv|qsp|qsps)"
)
_ASSET_PATTERN = re.compile(
    rf"[\w\d_\-\\/.]+{_ASSET_EXTENSIONS}", re.IGNORECASE
)
_ASSET_BYTES_PATTERN = re.compile(
    rf"[\w\d_\-\\/.]+{_ASSET_EXTENSIONS}".encode("ascii"), re.IGNORECASE
)


def _extract_qsp_referenced_paths(data: bytes) -> list[str]:
    paths: list[str] = []
    if data.startswith(b"Q\x00S\x00P\x00G\x00A\x00M\x00E\x00"):
        try:
            raw_text = data.decode("utf-16le")
            dec_text = "".join(chr((ord(c) + 5) % 65536) for c in raw_text)
            paths.extend(_ASSET_PATTERN.findall(dec_text))
        except Exception:
            pass

    for m in _ASSET_BYTES_PATTERN.findall(data):
        try:
            paths.append(m.decode("ascii", errors="ignore"))
        except Exception:
            pass

    return paths


def _create_case_insensitive_aliases(game_stage: Path) -> None:
    # 1. Directory lowercase symlinks
    for root, dirs, _ in os.walk(game_stage, followlinks=False):
        for d in list(dirs):
            if d.lower() != d:
                lower_dir = Path(root) / d.lower()
                if not lower_dir.exists() and not lower_dir.is_symlink():
                    try:
                        os.symlink(d, lower_dir)
                    except OSError:
                        pass

    # 2. File lowercase and lower-extension symlinks
    for root, _, files in os.walk(game_stage, followlinks=False):
        for f in files:
            file_path = Path(root) / f
            if file_path.is_symlink():
                continue
            lower_name = f.lower()
            if lower_name != f:
                lower_file = Path(root) / lower_name
                if not lower_file.exists() and not lower_file.is_symlink():
                    try:
                        os.symlink(f, lower_file)
                    except OSError:
                        pass
            suffix = Path(f).suffix
            if suffix and suffix.lower() != suffix:
                ext_lower = f"{Path(f).stem}{suffix.lower()}"
                if ext_lower != f and ext_lower != lower_name:
                    ext_file = Path(root) / ext_lower
                    if not ext_file.exists() and not ext_file.is_symlink():
                        try:
                            os.symlink(f, ext_file)
                        except OSError:
                            pass

    # 3. Match any explicit referenced paths from .qsp files
    actual_files: dict[str, Path] = {}
    for p in game_stage.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                rel = p.relative_to(game_stage).as_posix().lower()
                actual_files[rel] = p
            except ValueError:
                pass

    for qsp_file in game_stage.rglob("*"):
        if not qsp_file.is_file() or qsp_file.is_symlink():
            continue
        if qsp_file.suffix.lower() != ".qsp":
            continue
        try:
            content = qsp_file.read_bytes()
        except OSError:
            continue
        for ref in _extract_qsp_referenced_paths(content):
            norm_ref = ref.replace("\\", "/").lstrip("/")
            ref_lower = norm_ref.lower()
            if ref_lower in actual_files:
                target_path = actual_files[ref_lower]
                link_path = game_stage / norm_ref
                if not link_path.exists() and not link_path.is_symlink():
                    try:
                        link_path.parent.mkdir(parents=True, exist_ok=True)
                        rel_target = os.path.relpath(
                            target_path, link_path.parent
                        )
                        os.symlink(rel_target, link_path)
                    except OSError:
                        pass


def _decode_xml(raw: bytes) -> str | None:
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16le", errors="replace")
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16be", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if b"\x00" in raw[:100]:
        try:
            return raw.decode("utf-16le")
        except Exception:
            pass
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("latin-1")
    except Exception:
        return None


def _extract_aero_dimensions(xml_text: str) -> tuple[int | None, int | None]:
    width: int | None = None
    height: int | None = None
    try:
        root = ET.fromstring(xml_text)
        game_tag = root if root.tag.lower() == "game" else root.find(".//game")
        if game_tag is not None:
            for k, v in game_tag.attrib.items():
                if k.lower() == "width":
                    try:
                        width = int(v)
                    except ValueError:
                        pass
                elif k.lower() == "height":
                    try:
                        height = int(v)
                    except ValueError:
                        pass
    except ET.ParseError:
        pass

    if width is None:
        m_w = re.search(
            r'\bwidth\s*=\s*["\'](\d+)["\']', xml_text, re.IGNORECASE
        )
        if m_w:
            width = int(m_w.group(1))
    if height is None:
        m_h = re.search(
            r'\bheight\s*=\s*["\'](\d+)["\']', xml_text, re.IGNORECASE
        )
        if m_h:
            height = int(m_h.group(1))

    return (width, height)


def _process_config_xml(game_stage: Path) -> tuple[int | None, int | None]:
    """Find, decode, normalize to UTF-8, and extract Aero dimensions."""
    config_paths = [
        p
        for p in game_stage.rglob("*")
        if p.is_file() and p.name.lower() == "config.xml"
    ]
    if not config_paths:
        return (None, None)

    config_path = next(
        (p for p in config_paths if p.parent == game_stage),
        config_paths[0],
    )

    try:
        raw = config_path.read_bytes()
    except OSError:
        return (None, None)

    decoded = _decode_xml(raw)
    if not decoded:
        return (None, None)

    dims = _extract_aero_dimensions(decoded)

    try:
        normalized = re.sub(
            r'(<\?xml[^>]*?encoding\s*=\s*["\'])[^"\']+(["\'])',
            r"\g<1>utf-8\g<2>",
            decoded,
            flags=re.IGNORECASE,
        )
        config_path.write_text(normalized, encoding="utf-8")
    except OSError:
        pass

    root_config = game_stage / "config.xml"
    if not root_config.exists() and not root_config.is_symlink():
        try:
            rel = os.path.relpath(config_path, game_stage)
            os.symlink(rel, root_config)
        except OSError:
            pass

    return dims


def _prepare_game_dir(
    game_file: Path,
    game_stage: Path,
    config: dict[str, object],
    title: str,
    tags: list[str],
) -> None:
    game_stage.mkdir(parents=True, exist_ok=True)
    ext = game_file.suffix.lower()

    if ext == ".aqsp":
        with ZipFile(game_file) as zf:
            zf.extractall(game_stage)
        _fix_mojibake_names(game_stage)
        _flatten_single_dir(game_stage)
    elif ext in ALL_QSP_EXTENSIONS:
        shutil.copyfile(game_file, game_stage / game_file.name)
    else:
        extract_archive(game_file, game_stage)
        _unpack_nested_aqsp(game_stage)
        _fix_mojibake_names(game_stage)
        _flatten_single_dir(game_stage)

    xml_width, xml_height = _process_config_xml(game_stage)

    # Check if a valid game.cfg already exists
    existing_cfg = game_stage / "game.cfg"
    if existing_cfg.is_file():
        try:
            cfg_data = tomllib.loads(existing_cfg.read_text(encoding="utf-8"))
            if cfg_data.get("game") and isinstance(cfg_data["game"], list):
                first_game = cfg_data["game"][0]
                if (
                    isinstance(first_game, dict)
                    and "file" in first_game
                    and (game_stage / str(first_game["file"])).is_file()
                ):
                    _create_case_insensitive_aliases(game_stage)
                    return
        except Exception:
            pass

    # Resolve entrypoint
    if "entrypoint" in config:
        entrypoint = str(config["entrypoint"])
    else:
        candidates = [
            str(p.relative_to(game_stage))
            for p in game_stage.rglob("*")
            if p.is_file() and p.suffix.lower() in ALL_QSP_EXTENSIONS
        ]
        primary = find_primary_qsp_file(
            candidates, preferred_stem=game_file.stem
        )
        if not primary:
            raise ValueError(f"No QSP game file found for {game_file.name}")
        entrypoint = primary

    # Resolve mode
    if "mode" in config:
        resolved_mode = str(config["mode"])
    else:
        all_relative = [
            str(p.relative_to(game_stage)) for p in game_stage.rglob("*")
        ]
        resolved_mode = detect_qsp_mode(game_file, all_relative, tags)

    save_slots = (
        int(str(config["save_slots"])) if "save_slots" in config else None
    )

    aero_width: int | None = None
    aero_height: int | None = None
    if resolved_mode == "aero":
        if "width" in config:
            aero_width = int(str(config["width"]))
        elif xml_width is not None:
            aero_width = xml_width

        if "height" in config:
            aero_height = int(str(config["height"]))
        elif xml_height is not None:
            aero_height = xml_height

    cfg_text = _generate_game_cfg(
        game_id="game",
        title=title,
        entrypoint=entrypoint,
        mode=resolved_mode,
        save_slots=save_slots,
        aero_width=aero_width,
        aero_height=aero_height,
    )
    (game_stage / "game.cfg").write_text(cfg_text, encoding="utf-8")
    _create_case_insensitive_aliases(game_stage)


def _publish(stage: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    stage.rename(destination)


def generate(spec: GenerateSpec) -> None:
    for key in spec.config:
        if key not in VALID_CONFIG_KEYS:
            raise ValueError(
                f"qSpider generation does not support config key: {key}"
            )

    if "mode" in spec.config and spec.config["mode"] not in VALID_MODES:
        raise ValueError(f"Invalid mode: {spec.config['mode']}")

    if "save_slots" in spec.config:
        try:
            val = int(str(spec.config["save_slots"]))
            if val < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(
                "save_slots must be a positive integer: "
                f"{spec.config['save_slots']}"
            )

    for dim_key in ("width", "height"):
        if dim_key in spec.config:
            try:
                val = int(str(spec.config[dim_key]))
                if val < 1:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError(
                    f"{dim_key} must be a positive integer: "
                    f"{spec.config[dim_key]}"
                )

    releases = _release_paths()
    if spec.version not in releases:
        raise ValueError(f"Unknown qSpider version: {spec.version}")
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
        _prepare_game_dir(
            game_file=spec.game_file,
            game_stage=stage / "game",
            config=spec.config,
            title=resolved_title,
            tags=spec.tags,
        )
        _publish(stage, spec.destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
