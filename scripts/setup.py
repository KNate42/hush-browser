"""
Downloads Firefox ESR, verifies integrity, unpacks the browser core and runs build.py.
This work made by KNate42
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cache_folder = os.path.join(root, ".cache")
app_folder = os.path.join(root, "app")
app_tmp = os.path.join(root, "app-tmp")
build_script = os.path.join(root, "scripts", "build.py")


def download_file(address, target_path):
    # There I stream remote content to disk chunk by chunk.
    request = urllib.request.Request(address, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as source, open(target_path, "wb") as target:
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            target.write(chunk)


def calculate_digest(path):
    # There I compute sha256 checksum of a file on disk.
    hasher = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def find_checksum(sums_path, entry_name):
    # There I search for a file checksum line in SHA256SUMS.
    if not os.path.exists(sums_path):
        return None
    with open(sums_path, "r", encoding="utf-8", errors="replace") as source:
        for line in source:
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                candidate = parts[1].strip().lstrip("./").replace("\\", "/")
                if candidate == entry_name or candidate.endswith("/" + entry_name):
                    return parts[0].strip().lower()
    return None


def setup():
    os.makedirs(cache_folder, exist_ok=True)
    versions_url = "https://product-details.mozilla.org/1.0/firefox_versions.json"
    try:
        request = urllib.request.Request(versions_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        version = payload.get("FIREFOX_ESR")
        if not version:
            print("Ooops.. Ключ FIREFOX_ESR не найден в ответе Mozilla")
            sys.exit(1)
        version = version.strip()
    except Exception as error:
        print("Ooops.. Не удалось получить версию Firefox ESR: " + str(error))
        sys.exit(1)

    installer_name = "Firefox Setup " + version + ".exe"
    installer_path = os.path.join(cache_folder, installer_name)
    installer_url = "https://releases.mozilla.org/pub/firefox/releases/" + version + "/win64/ru/Firefox%20Setup%20" + version + ".exe"
    sums_path = os.path.join(cache_folder, "SHA256SUMS")
    sums_url = "https://releases.mozilla.org/pub/firefox/releases/" + version + "/SHA256SUMS"
    target_entry = "win64/ru/" + installer_name

    expected_hash = None
    try:
        download_file(sums_url, sums_path)
        expected_hash = find_checksum(sums_path, target_entry)
    except Exception as error:
        if os.path.exists(sums_path):
            expected_hash = find_checksum(sums_path, target_entry)
        if not expected_hash:
            print("Ooops.. Не удалось получить SHA256SUMS: " + str(error))
            sys.exit(1)

    if not expected_hash:
        print("Ooops.. Не найден хеш для " + target_entry + " в SHA256SUMS")
        sys.exit(1)

    need_download = True
    if os.path.exists(installer_path):
        current_hash = calculate_digest(installer_path)
        if current_hash == expected_hash:
            need_download = False
        else:
            os.remove(installer_path)

    if need_download:
        try:
            download_file(installer_url, installer_path)
        except Exception as error:
            print("Ooops.. Не удалось скачать установщик Firefox: " + str(error))
            sys.exit(1)

    current_hash = calculate_digest(installer_path)
    if current_hash != expected_hash:
        if os.path.exists(installer_path):
            os.remove(installer_path)
        print("Ooops.. Хеш установщика не совпал с SHA256SUMS")
        sys.exit(1)

    should_unpack = True
    if os.path.exists(app_folder):
        reply = input("Заменить app/ новой версией? (y/n)").strip().lower()
        if reply not in ("y", "yes", "д", "да"):
            should_unpack = False

    if should_unpack:
        if os.path.exists(app_tmp):
            shutil.rmtree(app_tmp, ignore_errors=True)
        extract_arg = "/ExtractDir=" + os.path.normpath(app_tmp)
        result = subprocess.run([os.path.normpath(installer_path), extract_arg])
        if result.returncode != 0:
            print("Ooops.. Ошибка при распаковке Firefox")
            sys.exit(result.returncode)
        core_folder = os.path.join(app_tmp, "core")
        if not os.path.isdir(core_folder):
            print("Ooops.. Папка core не найдена в распакованном архиве")
            if os.path.exists(app_tmp):
                shutil.rmtree(app_tmp, ignore_errors=True)
            sys.exit(1)
        if os.path.exists(app_folder):
            shutil.rmtree(app_folder)
        shutil.move(core_folder, app_folder)
        if os.path.exists(app_tmp):
            shutil.rmtree(app_tmp, ignore_errors=True)

    ublock_url = "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi"
    ublock_path = os.path.join(cache_folder, "uBlock0@raymondhill.net.xpi")
    try:
        download_file(ublock_url, ublock_path)
    except Exception as error:
        print("Ooops.. Не удалось скачать uBlock Origin: " + str(error))
        sys.exit(1)

    build_result = subprocess.run([sys.executable, build_script])
    if build_result.returncode != 0:
        print("Ooops.. scripts/build.py завершился с ошибкой")
        sys.exit(build_result.returncode)


if __name__ == "__main__":
    setup()
