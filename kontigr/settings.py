import os.path

from ifdb.settings import *

SITE_ID = 2
ROOT_URLCONF = "kontigr.urls"
TEMPLATES[0]["DIRS"].append(os.path.join(BASE_DIR, "kontigr/templates"))
