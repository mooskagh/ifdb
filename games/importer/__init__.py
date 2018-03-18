from .tools import Importer, REGISTERED_IMPORTERS
from .plut import PlutImporter
from .ifwiki import IfwikiImporter
from .qspsu import QspsuImporter
from .apero import AperoImporter
from .rilarhiv import RilarhivImporter
from .insteadgames import InsteadGamesImporter

REGISTERED_IMPORTERS.append(PlutImporter)
REGISTERED_IMPORTERS.append(IfwikiImporter)
REGISTERED_IMPORTERS.append(QspsuImporter)
REGISTERED_IMPORTERS.append(AperoImporter)
REGISTERED_IMPORTERS.append(RilarhivImporter)
REGISTERED_IMPORTERS.append(InsteadGamesImporter)
Importer
