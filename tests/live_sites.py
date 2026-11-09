"""
Tests public live websites with Hush and measures tab restore durations.
This work made by KNate42
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service

from test_signals import browser_options, installed_extension


root = Path(__file__).resolve().parent.parent


def is_blocked_url(url):
    target = (url or "").lower()
    return "consent." in target or target.startswith("about:neterror")


def discard_background_tab(driver, saved_url, initial_url):
    # There I discard the background tab via chrome privileges and verify it became pending.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with driver.context(driver.CONTEXT_CHROME):
            outcome = driver.execute_script("""
                const targetUrl = arguments[0];
                const initialUrl = arguments[1];
                const window = Services.wm.getMostRecentWindow('navigator:browser');
                const tabs = Array.from(window.gBrowser.tabs);
                const clean = url => url ? url.replace(/\\/+$/, '') : '';
                const tab = tabs.find(item => {
                    if (!item.linkedBrowser || !item.linkedBrowser.currentURI) return false;
                    const spec = item.linkedBrowser.currentURI.spec;
                    return spec === targetUrl || spec === initialUrl ||
                           clean(spec) === clean(targetUrl) || clean(spec) === clean(initialUrl);
                });
                if (!tab) return {ok: false, error: 'Tab not found for ' + targetUrl};
                window.gBrowser.discardBrowser(tab);
                const isDiscarded = Boolean(!tab.linkedPanel || tab.hasAttribute('pending'));
                return {ok: true, discarded: isDiscarded};
            """, saved_url, initial_url)
        if not outcome.get("ok"):
            raise RuntimeError(f"Ooops.. cannot find tab to discard: {outcome.get('error')}")
        if outcome.get("discarded"):
            return
        time.sleep(0.1)
    raise RuntimeError("Ooops.. tab was not discarded")


def measure_restore_runs(driver, target_handle, saved_url, initial_url, selector, repeats=3):
    durations = []
    for _ in range(repeats):
        blank_handle = None
        try:
            driver.switch_to.new_window("tab")
            blank_handle = driver.current_window_handle
            driver.get("about:blank")
            discard_background_tab(driver, saved_url, initial_url)

            # There I switch back to the discarded tab and poll readyState and the selector every 50 ms.
            timer_start = time.monotonic()
            driver.switch_to.window(target_handle)
            deadline = timer_start + 30
            restored = False
            while time.monotonic() < deadline:
                try:
                    ready = driver.execute_script("return document.readyState")
                    has_selector = driver.execute_script(
                        "return Boolean(document.querySelector(arguments[0]))", selector
                    )
                    if ready == "complete" and has_selector:
                        restored = True
                        break
                except WebDriverException:
                    pass
                time.sleep(0.05)
            if not restored:
                raise RuntimeError(f"Ooops.. tab restore timed out after 30s for selector '{selector}'")
            durations.append(time.monotonic() - timer_start)
        finally:
            if blank_handle and blank_handle in driver.window_handles:
                try:
                    driver.switch_to.window(blank_handle)
                    driver.close()
                except WebDriverException:
                    pass
            driver.switch_to.window(target_handle)
    return durations


def verify_site_condition(driver, name, selector):
    deadline = time.monotonic() + 25
    if name == "youtube-page":
        while time.monotonic() < deadline:
            if is_blocked_url(driver.current_url):
                return "blocked", f"page redirected to {driver.current_url}"
            try:
                if driver.execute_script("return Boolean(document.querySelector(arguments[0]))", selector):
                    return "ok", f"{selector} found"
            except WebDriverException:
                pass
            time.sleep(0.25)
        raise RuntimeError(f"Ooops.. {selector} not found within 25s")

    if name == "youtube-video":
        found = False
        while time.monotonic() < deadline:
            if is_blocked_url(driver.current_url):
                return "blocked", f"page redirected to {driver.current_url}"
            try:
                if driver.execute_script("return Boolean(document.querySelector('video'))"):
                    found = True
                    break
            except WebDriverException:
                pass
            time.sleep(0.25)
        if not found:
            raise RuntimeError("Ooops.. video element not found within 25s")

        # There I mute and play the video, then track currentTime growth over a 10-second period.
        driver.execute_script("""
            const video = document.querySelector('video');
            if (video) {
                video.muted = true;
                video.play();
            }
        """)
        samples = []
        video_deadline = time.monotonic() + 10
        while time.monotonic() < video_deadline:
            time.sleep(0.5)
            try:
                pos = driver.execute_script("""
                    const video = document.querySelector('video');
                    if (video && video.paused) {
                        video.muted = true;
                        video.play();
                    }
                    return video ? video.currentTime : null;
                """)
                if pos is not None:
                    samples.append(pos)
            except WebDriverException:
                pass
        if len(samples) < 2 or samples[-1] <= samples[0]:
            start_pos = samples[0] if samples else "none"
            end_pos = samples[-1] if samples else "none"
            raise RuntimeError(f"Ooops.. video currentTime did not advance (start={start_pos}, end={end_pos})")
        return "ok", f"video playing (currentTime {samples[0]:.2f}s -> {samples[-1]:.2f}s)"

    if name == "github-repo":
        while time.monotonic() < deadline:
            if is_blocked_url(driver.current_url):
                return "blocked", f"page redirected to {driver.current_url}"
            try:
                has_main = driver.execute_script("return Boolean(document.querySelector('main'))")
                title = driver.title or ""
                if has_main and title.strip():
                    return "ok", f"main found and title is '{title.strip()}'"
            except WebDriverException:
                pass
            time.sleep(0.25)
        raise RuntimeError("Ooops.. main element or non-empty title not found within 25s")

    if name == "wikipedia":
        while time.monotonic() < deadline:
            if is_blocked_url(driver.current_url):
                return "blocked", f"page redirected to {driver.current_url}"
            try:
                if driver.execute_script("return Boolean(document.querySelector(arguments[0]))", selector):
                    return "ok", f"{selector} found"
            except WebDriverException:
                pass
            time.sleep(0.25)
        raise RuntimeError(f"Ooops.. {selector} not found within 25s")

    if name == "monaco-editor":
        editor_found = False
        while time.monotonic() < deadline:
            if is_blocked_url(driver.current_url):
                return "blocked", f"page redirected to {driver.current_url}"
            try:
                if driver.execute_script("return Boolean(document.querySelector('.monaco-editor'))"):
                    editor_found = True
                    break
            except WebDriverException:
                pass
            time.sleep(0.25)
        if not editor_found:
            raise RuntimeError("Ooops.. .monaco-editor element not found within 25s")

        textarea = driver.find_element(By.CSS_SELECTOR, ".monaco-editor textarea")
        textarea.send_keys("hushcheck")

        text_deadline = time.monotonic() + 25
        while time.monotonic() < text_deadline:
            try:
                lines_text = driver.execute_script("""
                    const el = document.querySelector('.view-lines');
                    return el ? el.textContent : '';
                """)
                if "hushcheck" in lines_text:
                    return "ok", "typed hushcheck and verified in .view-lines"
            except WebDriverException:
                pass
            time.sleep(0.25)
        raise RuntimeError("Ooops.. text 'hushcheck' did not appear in .view-lines within 25s")

    raise RuntimeError(f"Ooops.. unknown case name: {name}")


def run_cases(driver):
    case_definitions = [
        {"name": "youtube-page", "url": "https://www.youtube.com/", "selector": "ytd-app", "restore": True},
        {"name": "youtube-video", "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw", "selector": "video", "restore": False},
        {"name": "github-repo", "url": "https://github.com/mozilla-firefox/firefox", "selector": "main", "restore": True},
        {"name": "wikipedia", "url": "https://en.wikipedia.org/wiki/Main_Page", "selector": "#content", "restore": True},
        {"name": "monaco-editor", "url": "https://microsoft.github.io/monaco-editor/playground.html", "selector": ".monaco-editor", "restore": False},
    ]

    records = []
    for item in case_definitions:
        name = item["name"]
        url = item["url"]
        selector = item["selector"]
        status = "fail"
        details = ""
        restore_stats = None

        driver.switch_to.new_window("tab")
        target_handle = driver.current_window_handle
        try:
            try:
                driver.get(url)
            except TimeoutException:
                try:
                    driver.execute_script("window.stop()")
                except WebDriverException:
                    pass
            except WebDriverException:
                pass

            if is_blocked_url(driver.current_url):
                status = "blocked"
                details = f"page redirected to {driver.current_url}"
            else:
                condition_status, condition_details = verify_site_condition(driver, name, selector)
                if condition_status == "blocked":
                    status = "blocked"
                    details = condition_details
                else:
                    status = "ok"
                    details = condition_details
                    if item["restore"]:
                        saved_url = driver.current_url
                        runs = measure_restore_runs(driver, target_handle, saved_url, url, selector, repeats=3)
                        min_run = min(runs)
                        median_run = statistics.median(runs)
                        max_run = max(runs)
                        details += f"; restore min={min_run:.2f}s median={median_run:.2f}s max={max_run:.2f}s"
                        restore_stats = {"runs": runs, "min": min_run, "median": median_run, "max": max_run}
        except Exception as error:
            try:
                if is_blocked_url(driver.current_url):
                    status = "blocked"
                    details = f"page redirected to {driver.current_url}"
                else:
                    status = "fail"
                    details = "Ooops.. " + str(error).removeprefix("Ooops.. ")
            except Exception:
                status = "fail"
                details = "Ooops.. " + str(error).removeprefix("Ooops.. ")

        print(f"{name} | {status} | {details}", flush=True)
        record = {"name": name, "url": url, "status": status, "details": details}
        if restore_stats:
            record["restore"] = restore_stats
        records.append(record)

    return records


def main():
    service = None
    driver = None
    records = []
    overall_status = 0
    report_path = root / "reports/live-sites.json"

    with tempfile.TemporaryDirectory(prefix="hush-live-") as profile:
        try:
            service = Service(executable_path=str(root / ".cache/gd/geckodriver.exe"),
                              service_args=["--allow-system-access"], log_output=os.devnull)
            firefox_options = browser_options(root / "app/firefox.exe", profile)
            driver = webdriver.Firefox(service=service, options=firefox_options)
            driver.set_script_timeout(20)
            driver.set_page_load_timeout(45)

            deadline = time.monotonic() + 12
            extension = installed_extension(driver)
            while not (extension.get("active") and extension.get("uuid")) and time.monotonic() < deadline:
                time.sleep(0.25)
                extension = installed_extension(driver)
            if not (extension.get("active") and extension.get("uuid")):
                raise RuntimeError(f"Ooops.. Hush extension is not active or missing uuid: {extension}")

            records = run_cases(driver)
        except Exception as error:
            overall_status = 1
            print(f"Ooops.. startup failed: {error}", flush=True)
        finally:
            try:
                if driver is not None:
                    driver.quit()
            finally:
                if service is not None:
                    service.stop()

    ok_count = sum(item["status"] == "ok" for item in records)
    blocked_count = sum(item["status"] == "blocked" for item in records)
    fail_count = sum(item["status"] == "fail" for item in records)
    if overall_status and not records:
        fail_count = 1

    print(f"{ok_count} ok, {blocked_count} blocked, {fail_count} fail")

    report_data = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "ok": ok_count,
            "blocked": blocked_count,
            "fail": fail_count,
        },
        "cases": records,
    }
    if overall_status and not records:
        report_data["error"] = "Ooops.. startup failed before running cases"

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"Ooops.. cannot write live sites report: {error}")
        return 1

    return 1 if (fail_count > 0 or overall_status != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
