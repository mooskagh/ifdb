import hashlib
import json
import os
import os.path
import re
import zipfile
from os import listdir

F = re.compile(r"(\d{4})\.txt")

for ff in listdir("."):
    m = F.match(ff)
    if not m:
        continue
    print(ff)

    src = os.path.abspath(m.group(1))
    with zipfile.ZipFile(
        "cabs/%s.zip" % m.group(1), "w", zipfile.ZIP_DEFLATED
    ) as z:
        for root, subFolders, files in os.walk(src):
            rel = os.path.relpath(root, src)
            for f in files:
                z.write(os.path.join(root, f), os.path.join(rel, f))

    md5 = hashlib.md5
    with open("cabs/%s.zip" % m.group(1), "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()

    with open("%s.txt" % m.group(1), encoding="utf-8") as f:
        j = json.loads(f.read())
    j["md5"] = md5
    with open("%s.txt" % m.group(1), "w", encoding="utf-8") as f:
        f.write(json.dumps(j, indent=2, ensure_ascii=False))
    try:
        os.rename("cabs/%s.zip" % m.group(1), "cabs/%s" % md5)
    except FileExistsError:
        os.rename("%s.txt" % m.group(1), "%sd.txt" % m.group(1))
