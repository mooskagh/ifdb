import os.path

from ifdb.settings import *

SITE_ID = 3
ROOT_URLCONF = "zok.urls"
TEMPLATES[0]["DIRS"].append(os.path.join(BASE_DIR, "zok/templates"))
