from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Protocol, cast

from . import blueprints


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
