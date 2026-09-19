import re
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Protocol, cast, overload

from . import blueprints

TELEMETRY_SCRIPT = (
    '<script src="https://db.crem.xyz/static/play-overlay.js" defer></script>'
)
TELEMETRY_SCRIPT_BYTES = TELEMETRY_SCRIPT.encode("utf-8")

_BODY_TAG_RE = re.compile(r"</body\s*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"</html\s*>", re.IGNORECASE)
_BODY_TAG_BYTES_RE = re.compile(rb"</body\s*>", re.IGNORECASE)
_HTML_TAG_BYTES_RE = re.compile(rb"</html\s*>", re.IGNORECASE)


@overload
def insert_telemetry(html: str) -> str: ...


@overload
def insert_telemetry(html: bytes) -> bytes: ...


def insert_telemetry(html: str | bytes) -> str | bytes:
    if isinstance(html, str):
        if TELEMETRY_SCRIPT in html:
            return html
        matches = list(_BODY_TAG_RE.finditer(html))
        if matches:
            pos = matches[-1].start()
            return html[:pos] + TELEMETRY_SCRIPT + html[pos:]
        matches = list(_HTML_TAG_RE.finditer(html))
        if matches:
            pos = matches[-1].start()
            return html[:pos] + TELEMETRY_SCRIPT + html[pos:]
        return html + TELEMETRY_SCRIPT
    elif isinstance(html, bytes):
        if TELEMETRY_SCRIPT_BYTES in html:
            return html
        matches_bytes = list(_BODY_TAG_BYTES_RE.finditer(html))
        if matches_bytes:
            pos = matches_bytes[-1].start()
            return html[:pos] + TELEMETRY_SCRIPT_BYTES + html[pos:]
        matches_bytes = list(_HTML_TAG_BYTES_RE.finditer(html))
        if matches_bytes:
            pos = matches_bytes[-1].start()
            return html[:pos] + TELEMETRY_SCRIPT_BYTES + html[pos:]
        return html + TELEMETRY_SCRIPT_BYTES
    raise TypeError(f"Expected str or bytes, got {type(html).__name__}")


class Compatibility(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"

    def __bool__(self) -> bool:
        return self != Compatibility.NONE


@dataclass(frozen=True, slots=True)
class BlueprintSpec:
    name: str
    versions: list[str]


@dataclass(frozen=True, slots=True)
class GenerateSpec:
    version: str
    config: dict[str, object]
    destination: Path
    game_file: Path
    title: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GenerateResult:
    player_name: str | None = None
    player_url: str | None = None


class BlueprintModule(Protocol):
    def get_spec(self) -> BlueprintSpec: ...

    def accepts(
        self, filename: Path, **kwargs: object
    ) -> Compatibility | bool: ...

    def generate(self, spec: GenerateSpec) -> GenerateResult | None: ...


def check_compatibility(
    blueprint: BlueprintModule,
    filename: Path,
    *,
    tags: list[str] | None = None,
) -> Compatibility:
    try:
        result = blueprint.accepts(filename, tags=tags)
    except TypeError:
        result = blueprint.accepts(filename)

    if isinstance(result, Compatibility):
        return result
    return Compatibility.FULL if result else Compatibility.NONE


@dataclass(frozen=True, slots=True)
class BlueprintInfo:
    name: str
    blueprint: BlueprintModule


def discover_blueprints() -> list[BlueprintInfo]:
    discovered: list[BlueprintInfo] = []

    for module_info in sorted(
        iter_modules(blueprints.__path__), key=lambda x: x.name
    ):
        if not module_info.ispkg:
            continue

        module = import_module(f"{blueprints.__name__}.{module_info.name}")
        get_spec = getattr(module, "get_spec", None)
        generate = getattr(module, "generate", None)
        if not callable(get_spec) or not callable(generate):
            continue

        spec = get_spec()
        if not isinstance(spec, BlueprintSpec):
            continue

        discovered.append(
            BlueprintInfo(module_info.name, cast(BlueprintModule, module))
        )

    return discovered
