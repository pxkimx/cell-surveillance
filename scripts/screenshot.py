"""Take a full-resolution screenshot of a page with headless Chrome.

    python3 scripts/screenshot.py URL OUT.png [--width 1500] [--height 1000] [--wait 12] [--scale 1.5]
                                  [--click TEXT] [--js CODE]

Used for the website card. Chrome is driven over its debugging port, so the page
can be left to finish loading and animating before the picture is taken.
"""
import argparse
import base64
import json
import os
import subprocess
import tempfile
import time

import requests
import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1500)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--wait", type=float, default=12)
    ap.add_argument("--click", action="append", default=[], help="click the first element with exactly this text")
    ap.add_argument("--js", action="append", default=[])
    ap.add_argument("--after", type=float, default=4, help="seconds to wait after each click or script")
    ap.add_argument("--port", type=int, default=9377)
    a = ap.parse_args()

    profile = tempfile.mkdtemp(prefix="cs-shot-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={a.port}", "--remote-allow-origins=*",
                             f"--user-data-dir={profile}", "--hide-scrollbars", "--mute-audio", "--no-first-run",
                             f"--window-size={a.width},{a.height}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = requests.get(f"http://127.0.0.1:{a.port}/json", timeout=1).json()
                break
            except Exception:
                time.sleep(0.25)
        page = next(t for t in tabs if t.get("type") == "page")
        ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60)
        n = [0]

        def call(method, **params):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == n[0]:
                    return msg.get("result", {})

        call("Emulation.setDeviceMetricsOverride", width=a.width, height=a.height, deviceScaleFactor=a.scale, mobile=False)
        call("Page.enable")
        call("Page.navigate", url=a.url)
        time.sleep(a.wait)
        for text in a.click:
            js = ("(() => { const t = %s; const el = [...document.querySelectorAll('button, [role=radio], label, p, span')]"
                  ".find(e => e.textContent.trim() === t); if (el) { el.click(); return true } return false })()") % json.dumps(text)
            print("click", text, call("Runtime.evaluate", expression=js).get("result", {}).get("value"))
            time.sleep(a.after)
        for code in a.js:
            call("Runtime.evaluate", expression=code)
            time.sleep(a.after)
        shot = call("Page.captureScreenshot", format="png")
        with open(a.out, "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))
        print("wrote", a.out, os.path.getsize(a.out) // 1024, "kB")
        ws.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
