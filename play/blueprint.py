from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Protocol, cast

from . import blueprints


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


class BlueprintModule(Protocol):
    def get_spec(self) -> BlueprintSpec: ...

    def accepts(self, filename: Path) -> bool: ...

    def generate(self, spec: GenerateSpec) -> None: ...


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
