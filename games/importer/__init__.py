from .tools import Import, ImportAuthor, REGISTERED_IMPORTERS
from .plut import PlutImporter
from .ifwiki import IfwikiImporter
from .qspsu import QspsuImporter
from .apero import AperoImporter

REGISTERED_IMPORTERS.append(PlutImporter())
REGISTERED_IMPORTERS.append(IfwikiImporter())
REGISTERED_IMPORTERS.append(QspsuImporter())
REGISTERED_IMPORTERS.append(AperoImporter())
Import
ImportAuthor
