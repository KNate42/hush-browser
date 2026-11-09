"""
Measures private memory of an isolated Firefox process tree on public sites.
This work made by KNate42
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
import time
from urllib.parse import urlsplit

import psutil
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.firefox.service import Service

from test_signals import browser_options, installed_extension


root = Path(__file__).resolve().parent.parent


def parse_pref(text):
    name, value = text.split("=", 1)
    if not name:
        raise ValueError
    if value in ("true", "false"):
        return name, value == "true"
    try:
        return name, int(value)
    except ValueError:
        return name, value


def arguments():
    parser = argparse.ArgumentParser(description="Measure Firefox private bytes in fresh headless profiles.")
    parser.add_argument("--browser", required=True, help="Path to the Firefox executable")
    parser.add_argument("--label", required=True, help="Report filename label: letters, digits, dot, dash, underscore")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--extension-off", action="store_true", help="Disable hush@local in the temporary profile")
    parser.add_argument("--unload-wait", type=int, default=0, help="Set the idle limit to 1 minute and wait this many extra seconds")
    parser.add_argument("--pref", action="append", default=[], help="Extra preference as name=value, can be repeated")
    options = parser.parse_args()
    if options.runs < 1:
        parser.error("Ooops.. --runs must be positive")
    try:
        options.pref = [parse_pref(text) for text in options.pref]
    except ValueError:
        parser.error("Ooops.. --pref must look like name=value")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", options.label):
        parser.error("Ooops.. unsafe --label")
    options.browser = Path(options.browser).resolve()
    if not options.browser.is_file():
        parser.error("Ooops.. browser executable does not exist")
    return options


def load_sites():
    sites = [line.strip() for line in (root / "tests/sites.txt").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if len(sites) != 20 or len(set(sites)) != 20:
        raise RuntimeError("Ooops.. sites.txt must contain 20 different URLs")
    for site in sites:
        parsed = urlsplit(site)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise RuntimeError("Ooops.. sites.txt contains an invalid public URL")
    return sites


def disable_extension(driver):
    with driver.context(driver.CONTEXT_CHROME):
        response = driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            const {AddonManager} = ChromeUtils.importESModule(
                'resource://gre/modules/AddonManager.sys.mjs');
            (async () => {
                const addon = await AddonManager.getAddonByID('hush@local');
                if (!addon) return {installed: false, active: false};
                await addon.disable();
                return {installed: true, active: addon.isActive, disabled: addon.userDisabled};
            })().then(done, error => done({error: String(error)}));
        """)
    if response.get("error") or response.get("active") is not False:
        raise RuntimeError(f"Ooops.. cannot disable Hush: {response}")
    return response


def set_unload_minutes(driver, minutes):
    uuid = installed_extension(driver).get("uuid")
    if not uuid:
        raise RuntimeError("Ooops.. Hush is not installed, cannot set the idle limit")
    driver.get(f"moz-extension://{uuid}/popup/popup.html")
    response = driver.execute_async_script("""
        const done = arguments[arguments.length - 1];
        browser.runtime.sendMessage({type: 'set-unload-minutes', minutes: arguments[0]})
            .then(done, error => done({error: String(error)}));
    """, minutes)
    if not response or not response.get("ok"):
        raise RuntimeError(f"Ooops.. cannot set the idle limit: {response}")


def tab_states(driver):
    # There I ask the browser window directly, because a discarded tab has no content process to answer.
    with driver.context(driver.CONTEXT_CHROME):
        return driver.execute_script("""
            const window = Services.wm.getMostRecentWindow('navigator:browser');
            const tabs = window.gBrowser.tabs;
            return {total: tabs.length,
                    discarded: tabs.filter(tab => !tab.linkedPanel || tab.hasAttribute('pending')).length};
        """)


def find_browser(driver, service, browser):
    # There I anchor the browser identity to this geckodriver instead of searching system processes.
    owner = psutil.Process(service.process.pid)
    browser_identity = driver.capabilities.get("moz:processID")
    matches = []
    for process in owner.children(recursive=True):
        try:
            if process.pid == browser_identity and Path(process.exe()).resolve() == browser:
                matches.append(process)
        except psutil.NoSuchProcess:
            continue
    if len(matches) != 1:
        raise RuntimeError("Ooops.. cannot identify this geckodriver's Firefox process")
    return owner, matches[0]


def private_sample(owner, browser):
    if not owner.is_running() or not browser.is_running():
        raise RuntimeError("Ooops.. geckodriver or Firefox exited during measurement")
    if browser not in owner.children(recursive=True):
        raise RuntimeError("Ooops.. Firefox no longer belongs to this geckodriver")
    total = 0
    identities = []
    for process in [browser] + browser.children(recursive=True):
        try:
            info = process.memory_info()
            if not hasattr(info, "private"):
                raise RuntimeError("Ooops.. psutil private memory is unavailable on this platform")
            total += info.private
            identities.append({"pid": process.pid, "created": process.create_time()})
        except psutil.NoSuchProcess:
            if process == browser:
                raise RuntimeError("Ooops.. Firefox exited during measurement")
    if total <= 0:
        raise RuntimeError("Ooops.. empty private memory sample")
    return {"private_bytes": total, "processes": identities}


def run_once(options, sites, number):
    service = None
    driver = None
    with tempfile.TemporaryDirectory(prefix="hush-memory-") as profile:
        try:
            service = Service(executable_path=str(root / ".cache/gd/geckodriver.exe"),
                              service_args=["--allow-system-access"], log_output=os.devnull)
            firefox_options = browser_options(options.browser, profile)
            for name, value in options.pref:
                firefox_options.set_preference(name, value)
            driver = webdriver.Firefox(service=service, options=firefox_options)
            driver.set_script_timeout(20)
            driver.set_page_load_timeout(45)
            owner, browser = find_browser(driver, service, options.browser)
            extension = disable_extension(driver) if options.extension_off else installed_extension(driver)
            if extension.get("error"):
                raise RuntimeError(f"Ooops.. cannot determine Hush state: {extension}")
            if options.unload_wait:
                set_unload_minutes(driver, 1)
            loads = []
            for index, site in enumerate(sites):
                if index:
                    driver.switch_to.new_window("tab")
                started = time.monotonic()
                status = "loaded"
                try:
                    driver.get(site)
                except TimeoutException:
                    driver.execute_script("window.stop()")
                    status = "timeout"
                except WebDriverException:
                    status = "error"
                loads.append({"url": site, "status": status, "final_url": driver.current_url,
                              "title": driver.title, "seconds": time.monotonic() - started})
            if len(driver.window_handles) != len(sites):
                raise RuntimeError("Ooops.. the tab count differs from sites.txt")
            time.sleep(60 + options.unload_wait)
            samples = []
            started = time.monotonic()
            for index in range(30):
                remaining = started + index + 1 - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                sample = private_sample(owner, browser)
                sample["elapsed_seconds"] = time.monotonic() - started
                samples.append(sample)
            tabs = tab_states(driver)
            final_extension = installed_extension(driver)
            if options.extension_off and final_extension.get("active") is not False:
                raise RuntimeError("Ooops.. Hush became active during an extension-off run")
            values = [sample["private_bytes"] for sample in samples]
            return {"run": number, "geckodriver_pid": owner.pid, "firefox_pid": browser.pid,
                    "browser_version": driver.capabilities.get("browserVersion"),
                    "extension": extension, "extension_after": final_extension,
                    "tabs": tabs, "process_count": len(samples[-1]["processes"]),
                    "not_loaded": sorted(page["url"] for page in loads if page["status"] != "loaded"),
                    "pages": loads, "samples": samples,
                    "median_private_bytes": statistics.median(values),
                    "peak_private_bytes": max(values)}
        finally:
            try:
                if driver is not None:
                    driver.quit()
            finally:
                if service is not None:
                    service.stop()


def main():
    options = arguments()
    report_path = root / "reports" / f"memory-{options.label}.json"
    report = {"label": options.label, "browser": str(options.browser),
              "extension_off": options.extension_off, "requested_runs": options.runs,
              "prefs": dict(options.pref), "unload_wait": options.unload_wait,
              "created_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
              "warmup_seconds": 60, "sample_seconds": 30, "sample_interval_seconds": 1,
              "metric": "sum of private bytes: Firefox root and all its descendants, excluding geckodriver",
              "runs": []}
    status = 0
    try:
        sites = load_sites()
        report["sites"] = sites
        for number in range(1, options.runs + 1):
            report["runs"].append(run_once(options, sites, number))
        values = [sample["private_bytes"] for run in report["runs"] for sample in run["samples"]]
        report["median_private_bytes"] = statistics.median(values)
        report["peak_private_bytes"] = max(values)
        report["status"] = "complete"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = "Ooops.. " + str(error).removeprefix("Ooops.. ")
        status = 1
    try:
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"Ooops.. cannot write memory report: {error}")
        return 1
    if status:
        print(f"{report['error']} report={report_path}")
    else:
        median = report["median_private_bytes"] / (1024 * 1024)
        peak = report["peak_private_bytes"] / (1024 * 1024)
        # There I print the failed pages, because two series compare fairly only with the same set of loaded pages.
        not_loaded = sorted({url for run in report["runs"] for url in run["not_loaded"]})
        print(f"{options.label}: median={median:.2f} MiB peak={peak:.2f} MiB "
              f"runs={options.runs} not_loaded={not_loaded} report={report_path}")
    return status


if __name__ == "__main__":
    sys.exit(main())
