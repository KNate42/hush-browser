"""
Checks Hush signals with trusted browser actions and a local HTTP stand.
This work made by KNate42
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait


root = Path(__file__).resolve().parent.parent
stand = Path(__file__).resolve().parent / "stand"


class signal_results:
    def __init__(self):
        self.rows = []

    def check(self, signal, mode, expected, actual):
        passed = actual == expected
        self.rows.append((signal, mode, expected, actual, passed))
        return passed

    def show(self):
        print("signal | mode | expected | actual | result")
        print("-" * 100)
        for signal, mode, expected, actual, passed in self.rows:
            print(f"{signal} | {mode} | {json.dumps(expected)} | "
                  f"{json.dumps(actual)} | {'PASS' if passed else 'FAIL'}")
        failed = sum(not row[4] for row in self.rows)
        print(f"{len(self.rows) - failed} passed, {failed} failed")
        return failed == 0 and bool(self.rows)


class stand_handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path
        files = {"/": "index.html", "/index.html": "index.html", "/frame.html": "frame.html"}
        if path not in files:
            self.send_error(404)
            return
        body = (stand / files[path]).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/beacon":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        token = parse_qs(parsed.query).get("token", [""])[0]
        with self.server.beacon_lock:
            self.server.beacons.setdefault(token, []).append(body.decode("utf-8"))
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


def browser_options(browser, profile):
    options = Options()
    options.binary_location = str(browser)
    for argument in ("-headless", "-no-remote", "-profile", str(profile)):
        options.add_argument(argument)
    options.set_preference("browser.shell.checkDefaultBrowser", False)
    options.set_preference("browser.startup.homepage_override.mstone", "ignore")
    options.set_preference("browser.startup.page", 0)
    options.set_preference("browser.tabs.warnOnClose", False)
    options.set_preference("browser.sessionstore.resume_from_crash", False)
    options.set_preference("extensions.autoDisableScopes", 0)
    options.set_preference("extensions.enabledScopes", 15)
    options.set_preference("extensions.installDistroAddons", True)
    return options


def installed_extension(driver):
    with driver.context(driver.CONTEXT_CHROME):
        return driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            const {AddonManager} = ChromeUtils.importESModule(
                'resource://gre/modules/AddonManager.sys.mjs');
            AddonManager.getAddonByID('hush@local').then(addon => {
                const mapping = JSON.parse(Services.prefs.getStringPref(
                    'extensions.webextensions.uuids', '{}'));
                done({installed: Boolean(addon), active: Boolean(addon && addon.isActive),
                      uuid: mapping['hush@local'] || null});
            }).catch(error => done({error: String(error)}));
        """)


def set_modes(driver, extension_uuid, settings):  # uuid = universally unique identifier
    driver.get(f"moz-extension://{extension_uuid}/popup/popup.html")
    response = driver.execute_async_script("""
        const settings = arguments[0], done = arguments[arguments.length - 1];
        (async () => {
            if (browser.runtime.id !== 'hush@local') throw new Error('Wrong extension');
            for (const [host, mode] of Object.entries(settings)) {
                const result = await browser.runtime.sendMessage({type: 'set-site', host, mode});
                if (!result || result.ok !== true) throw new Error('set-site failed: ' + host);
            }
            return {ok: true};
        })().then(done, error => done({error: String(error)}));
    """, settings)
    if response != {"ok": True}:
        raise RuntimeError(f"Ooops.. extension message failed: {response}")


def phase(driver, name):
    driver.execute_script("window.hushPhase = arguments[0]", name)


def shortcut(driver, key):
    ActionChains(driver).key_down(Keys.CONTROL).send_keys(key).key_up(Keys.CONTROL).perform()


def events(log, name, target=None, phase_name=None, scope="main", listener="window"):
    return [row for row in log if row["type"] == name and row.get("scope") == scope
            and (target is None or row.get("target") == target)
            and (phase_name is None or row.get("phase") == phase_name)
            and (listener is None or row.get("listener") == listener)]


def trusted(log, name, target=None, phase_name=None, scope="main", listener="window"):
    return any(row.get("trusted") is True
               for row in events(log, name, target, phase_name, scope, listener))


def exercise(driver, server, host, mode, results):
    label = f"{host}/{mode}"
    port = server.server_address[1]
    address = f"http://{host}:{port}/index.html?case={uuid4().hex}"
    driver.get(address)
    WebDriverWait(driver, 10).until(
        lambda browser: browser.execute_script("return Boolean(window.hushLog && "
                                               "document.querySelector('#editor'))"))
    driver.set_window_size(1200, 900)
    source = driver.find_element(By.ID, "source")
    plain = driver.find_element(By.ID, "plain")
    editor = driver.find_element(By.ID, "editor")
    marker = source.get_property("value")

    phase(driver, "copy")
    source.click()
    shortcut(driver, "a")
    shortcut(driver, "c")
    phase(driver, "plain-paste")
    plain.click()
    shortcut(driver, "v")
    results.check("plain pasted value", label, marker, plain.get_property("value"))
    phase(driver, "plain-cut")
    shortcut(driver, "a")
    shortcut(driver, "x")
    results.check("plain cut value", label, "", plain.get_property("value"))
    phase(driver, "plain-restore")
    shortcut(driver, "v")
    results.check("plain restored value", label, marker, plain.get_property("value"))
    phase(driver, "editor-paste")
    editor.click()
    shortcut(driver, "v")
    results.check("editor pasted value", label, marker, editor.get_property("textContent"))

    phase(driver, "activity")
    frame = driver.find_element(By.ID, "pointer-frame")
    ActionChains(driver).move_to_element(frame).pause(0.2).move_to_element(source).perform()
    shortcut(driver, "a")
    driver.execute_script("performance.mark('hush-activity')")
    ActionChains(driver).scroll_by_amount(0, 650).perform()
    time.sleep(0.5)

    token = uuid4().hex
    accepted = driver.execute_script("return window.hushBeacon(arguments[0])", token)
    results.check("sendBeacon return", label, True, accepted)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with server.beacon_lock:
            received = list(server.beacons.get(token, []))
        if received:
            break
        time.sleep(0.05)
    results.check("sendBeacon server body", label, ["hush"] if mode == "off" else [], received)

    phase(driver, "background")
    plain.click()
    driver.execute_script("window.hushBackgroundProbe()")
    original = driver.current_window_handle
    driver.switch_to.new_window("tab")
    try:
        driver.get("about:blank")
        time.sleep(4)
    finally:
        driver.close()
        driver.switch_to.window(original)
    time.sleep(0.3)
    log = driver.execute_script("return window.hushLog")
    protected = mode != "off"
    strict = mode == "strict"

    for listener in ("window", "document"):
        results.check(f"visibilitychange ({listener})", label, not protected,
                      trusted(log, "visibilitychange", listener=listener))
    for name in ("blur", "focus"):
        results.check(f"window {name}", label, not protected,
                      trusted(log, name, "window", "background"))
    results.check("plain focus preserved", label, True, trusted(log, "focus", "plain"))
    results.check("plain blur preserved", label, True, trusted(log, "blur", "plain"))
    probes = events(log, "background-probe", listener=None)
    results.check("background probe ran", label, 1, len(probes))
    if probes:
        results.check("document.hidden in background", label, not protected, probes[0]["hidden"])
        results.check("visibilityState in background", label,
                      "hidden" if mode == "off" else "visible", probes[0]["visibilityState"])
        results.check("hasFocus in background", label, protected, probes[0]["hasFocus"])
        results.check("synchronous iframe hidden", label, not protected, probes[0]["iframeHidden"])
    results.check("any hidden=true leak", label, not protected,
                  any(row.get("hidden") is True for row in log if row["scope"] == "main"))
    results.check("any hasFocus=false leak", label, not protected,
                  any(row.get("hasFocus") is False for row in log if row["scope"] == "main"))

    for name, target, phase_name in (("copy", "source", "copy"),
                                     ("cut", "plain", "plain-cut"),
                                     ("paste", "plain", "plain-paste")):
        results.check(f"plain {name}", label, not protected,
                      trusted(log, name, target, phase_name))
    for name in ("input", "beforeinput"):
        rows = events(log, name, "plain", "plain-paste")
        results.check(f"plain {name} trusted", label, True,
                      any(row.get("trusted") is True for row in rows))
        results.check(f"plain {name} inputType", label,
                      ["insertFromPaste" if mode == "off" else "insertText"],
                      sorted({row["inputType"] for row in rows}))
    results.check("editor paste", label, not strict,
                  trusted(log, "paste", "editor", "editor-paste"))
    if not strict:
        results.check("editor paste data", label, [marker],
                      [row.get("data") for row in events(log, "paste", "editor", "editor-paste")])
    if mode == "off":
        results.check("plain paste data", label, [marker],
                      [row.get("data") for row in events(log, "paste", "plain", "plain-paste")])
    for name in ("mousemove", "scroll", "selectionchange"):
        results.check(name, label, not strict, trusted(log, name))
    results.check("mouseout relatedTarget=null", label, not protected,
                  any(row.get("relatedTargetNull") and row.get("trusted")
                      for row in events(log, "mouseout", scope="frame", listener=None)))
    results.check("PerformanceObserver mark", label, not strict,
                  any(row.get("name") == "hush-activity"
                      for row in events(log, "performance", listener=None)))
    # There I evaluate in the page realm: execute_script has its own Function.prototype.
    native = driver.execute_script("return window.eval(\"Function.prototype.toString.call("
                                   "Object.getOwnPropertyDescriptor(Document.prototype, 'hidden').get)\")")
    results.check("hidden getter native code", label, True, "[native code]" in native)
    clean_frame = driver.execute_script("return window.eval(\"(() => { const f = document.createElement('iframe');"
                                        " document.body.append(f); const v = f.contentWindow;"
                                        " const text = v.Function.prototype.toString.call("
                                        "v.Object.getOwnPropertyDescriptor(v.Document.prototype, 'hidden').get);"
                                        " f.remove(); return text; })()\")")
    results.check("clean iframe getter native code", label, True, "[native code]" in clean_frame)

    phase(driver, "leave")
    driver.get(address + "&next=1")
    previous = driver.execute_script("return window.hushPreviousLog")
    results.check("pagehide", label, not strict,
                  trusted(previous, "pagehide", phase_name="leave"))


def main():
    results = signal_results()
    server = None
    thread = None
    driver = None
    service = None
    try:
        with tempfile.TemporaryDirectory(prefix="hush-signals-") as profile:
            try:
                server = ThreadingHTTPServer(("127.0.0.1", 0), stand_handler)
                server.beacons = {}
                server.beacon_lock = threading.Lock()
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                service = Service(executable_path=str(root / ".cache/gd/geckodriver.exe"),
                                  service_args=["--allow-system-access"], log_output=os.devnull)
                driver = webdriver.Firefox(service=service, options=browser_options(
                    root / "app/firefox.exe", profile))
                driver.set_script_timeout(15)
                driver.set_page_load_timeout(30)
                deadline = time.monotonic() + 12
                extension = installed_extension(driver)
                while not (extension.get("active") and extension.get("uuid")) and time.monotonic() < deadline:
                    time.sleep(0.25)
                    extension = installed_extension(driver)
                if not results.check("hush@local installed and active", "startup", True,
                                     bool(extension.get("installed") and extension.get("active")
                                          and extension.get("uuid"))):
                    raise RuntimeError(f"Ooops.. Hush is not installed and active: {extension}. "
                                       "Run scripts/build.py before the test.")
                for host, other in (("127.0.0.1", "localhost"), ("localhost", "127.0.0.1")):
                    for mode in ("off", "normal", "strict"):
                        label = f"{host}/{mode}"
                        try:
                            print(f"Running {label}", flush=True)
                            set_modes(driver, extension["uuid"],
                                      {other: "strict" if mode == "off" else "off", host: mode})
                            exercise(driver, server, host, mode, results)
                        except Exception as error:
                            results.check("case completed", label, "success",
                                          "Ooops.. " + str(error).removeprefix("Ooops.. "))
            finally:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception as error:
                        results.check("browser cleanup", "cleanup", "success", f"Ooops.. {error}")
                if service is not None:
                    service.stop()
                if server is not None:
                    server.shutdown()
                    server.server_close()
                if thread is not None:
                    thread.join(timeout=5)
    except Exception as error:
        results.check("test completed", "startup", "success",
                      "Ooops.. " + str(error).removeprefix("Ooops.. "))
    return 0 if results.show() else 1


if __name__ == "__main__":
    sys.exit(main())
