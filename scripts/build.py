"""
Builds page-world bundles of the extension, packs it to an .xpi and copies the configuration to app/.
This work made by KNate42
"""

import json
import os
import shutil
import sys
import zipfile

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
extension = os.path.join(root, "extension")
app = os.path.join(root, "app")


def bundle(level):
    # There I glue core, modules and entry into one closure so nothing leaks to the page.
    parts = []
    for name in ("core.js", "modules.js", "entry.js"):
        with open(os.path.join(extension, "src", name), encoding="utf-8") as source:
            parts.append(source.read())
    body = "\n".join(parts)
    text = "(() => {\nconst HUSH_LEVEL = " + json.dumps(level) + ";\n" + body + "\n})();\n"
    os.makedirs(os.path.join(extension, "dist"), exist_ok=True)
    with open(os.path.join(extension, "dist", level + ".js"), "w", encoding="utf-8", newline="\n") as target:
        target.write(text)


def pack(destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, folders, files in os.walk(extension):
            folders[:] = [item for item in folders if item != "src"]
            for name in files:
                path = os.path.join(folder, name)
                archive.write(path, os.path.relpath(path, extension).replace(os.sep, "/"))


def deploy():
    # There I put prefs, policies and bundled extensions where Firefox reads them on start.
    shutil.copy(os.path.join(root, "config", "autoconfig.js"), os.path.join(app, "defaults", "pref", "autoconfig.js"))
    shutil.copy(os.path.join(root, "config", "hush.cfg"), os.path.join(app, "hush.cfg"))
    distribution = os.path.join(app, "distribution")
    addons = os.path.join(distribution, "extensions")
    os.makedirs(addons, exist_ok=True)
    shutil.copy(os.path.join(root, "config", "policies.json"), os.path.join(distribution, "policies.json"))
    pack(os.path.join(addons, "hush@local.xpi"))
    blocker = os.path.join(root, ".cache", "uBlock0@raymondhill.net.xpi")
    if os.path.exists(blocker):
        shutil.copy(blocker, os.path.join(addons, "uBlock0@raymondhill.net.xpi"))
    else:
        print("Ooops.. uBlock Origin is not downloaded yet, skipping it")


if __name__ == "__main__":
    bundle("normal")
    bundle("strict")
    if not os.path.isdir(app):
        print("Ooops.. app/ folder is missing, run scripts/setup.py first")
        sys.exit(1)
    deploy()
    print("Done")
