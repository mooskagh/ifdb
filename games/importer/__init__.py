from .tools import Import, REGISTERED_IMPORTERS
from .plut import PlutImporter
from .ifwiki import IfwikiImporter
from .qspsu import QspsuImporter

REGISTERED_IMPORTERS.append(PlutImporter())
REGISTERED_IMPORTERS.append(IfwikiImporter())
REGISTERED_IMPORTERS.append(QspsuImporter())
