from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules

from . import blueprints


class BlueprintBase(ABC):
    @abstractmethod
    def name(self) -> str:
        pass


@dataclass(frozen=True, slots=True)
class BlueprintInfo:
    name: str
    blueprint: type[BlueprintBase]


def discover_blueprints() -> list[BlueprintInfo]:
    discovered = []

    for module_info in sorted(
        iter_modules(blueprints.__path__), key=lambda x: x.name
    ):
        if not module_info.ispkg:
            continue

        module = import_module(f"{blueprints.__name__}.{module_info.name}")
        blueprint = getattr(module, "Blueprint", None)
        if (
            not isinstance(blueprint, type)
            or blueprint.__module__ != module.__name__
            or not issubclass(blueprint, BlueprintBase)
        ):
            continue

        discovered.append(BlueprintInfo(module_info.name, blueprint))

    return discovered
