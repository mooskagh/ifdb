from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules
from typing import Protocol, cast

from . import blueprints


@dataclass(frozen=True, slots=True)
class BlueprintSpec:
    name: str
    version: str


class BlueprintModule(Protocol):
    spec: BlueprintSpec


@dataclass(frozen=True, slots=True)
class BlueprintInfo:
    name: str
    blueprint: BlueprintModule


def discover_blueprints() -> list[BlueprintInfo]:
    discovered = []

    for module_info in sorted(
        iter_modules(blueprints.__path__), key=lambda x: x.name
    ):
        if not module_info.ispkg:
            continue

        module = import_module(f"{blueprints.__name__}.{module_info.name}")
        if not isinstance(getattr(module, "spec", None), BlueprintSpec):
            continue

        discovered.append(
            BlueprintInfo(module_info.name, cast(BlueprintModule, module))
        )

    return discovered
