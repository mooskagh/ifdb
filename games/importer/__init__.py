from .tools import Import, REGISTERED_IMPORTERS
from .plut import PlutImporter
from .ifwiki import IfwikiImporter

REGISTERED_IMPORTERS.append(PlutImporter())
REGISTERED_IMPORTERS.append(IfwikiImporter())
