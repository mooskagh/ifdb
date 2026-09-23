from .apero import AperoImporter
from .axma import AxmaImporter
from .ifiction import IfictionImporter
from .ifwiki import IfwikiImporter
from .insteadgames import InsteadGamesImporter
from .questbook import QuestBookImporter
from .rilarhiv import RilarhivImporter
from .tools import REGISTERED_IMPORTERS, Importer

# REGISTERED_IMPORTERS.append(PlutImporter)
REGISTERED_IMPORTERS.append(IfwikiImporter)
# REGISTERED_IMPORTERS.append(QspsuImporter)
REGISTERED_IMPORTERS.append(AperoImporter)
REGISTERED_IMPORTERS.append(RilarhivImporter)
REGISTERED_IMPORTERS.append(InsteadGamesImporter)
REGISTERED_IMPORTERS.append(QuestBookImporter)
REGISTERED_IMPORTERS.append(IfictionImporter)
REGISTERED_IMPORTERS.append(AxmaImporter)
Importer
