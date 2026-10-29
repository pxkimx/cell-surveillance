"""Quit completely when the app's window is closed.

The app is a small local server with a browser tab as its window. Left alone, the
server keeps running after the tab is closed. This module makes the two end together:

* The page tells the server when it is being closed (a "beacon" sent as the tab goes
  away). If no tab is connected a few seconds later, the server stops. Reloading the
  page reconnects within that time, so it does not stop the app.
* If every tab has been disconnected for three minutes without such a message (the
  browser crashed or was force-quit), the server stops as well.
* If the launcher that started the server is gone (the app was quit or force-quit from
  the Dock), the server stops.
* Whatever the reason, an analysis still running is stopped with it, together with its
  worker processes. Nothing is left behind.
"""
from __future__ import annotations

import atexit
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHECK_S = 2.0            # how often the server looks at who is connected
AFTER_CLOSE = 3          # checks with nobody connected after the page said it was closing (about 6 s)
AFTER_SILENCE = 90       # checks with nobody connected and no such message (about 3 min)
LAUNCHER_ENV = "CELL_SURVEILLANCE_LAUNCHER_PID"
APP_ENV = "CELL_SURVEILLANCE_APP_PID"          # set for an analysis the app starts: the pid it must not outlive

_lock = threading.Lock()
_state = {"url": None, "closing": False, "children": []}


def _log(text: str) -> None:
    print(f"[{time.strftime('%F %T')}] {text}", file=sys.stderr, flush=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def register_child(proc) -> None:
    """A process started by the app (in its own process group) that must not outlive it."""
    with _lock:
        _state["children"] = [p for p in _state["children"] if p.poll() is None] + [proc]


def stop_children() -> None:
    with _lock:
        children, _state["children"] = _state["children"], []
    for proc in children:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)       # the analysis and its workers share one group
            except (ProcessLookupError, PermissionError):
                pass


def should_quit(connected: int, seen: bool, empty: int, closing: bool) -> tuple:
    """One step of the rule. Returns (quit now?, seen, empty checks, closing)."""
    if connected > 0:
        return False, True, 0, False
    if not seen:                                           # nobody has opened the app yet
        return False, False, 0, closing
    empty += 1
    return (closing and empty >= AFTER_CLOSE) or empty >= AFTER_SILENCE, True, empty, closing


def _quit(reason: str) -> None:
    _log(f"quitting: {reason}")
    stop_children()
    os.kill(os.getpid(), signal.SIGTERM)                   # Streamlit stops its server on this signal
    time.sleep(6)
    os._exit(0)                                            # and if it did not, stop anyway


def _watch() -> None:
    from streamlit.runtime import get_instance
    launcher = int(os.environ.get(LAUNCHER_ENV, "0") or 0)
    seen, empty = False, 0
    while True:
        time.sleep(CHECK_S)
        if launcher and not _alive(launcher):
            _quit("the launcher was closed")
        try:
            connected = get_instance()._session_mgr.num_active_sessions()
        except Exception:                                  # a Streamlit without this: leave the app running
            continue
        quit_now, seen, empty, closing = should_quit(connected, seen, empty, _state["closing"])
        _state["closing"] = closing
        if quit_now:
            _quit("its window was closed" if closing else "no window has been connected for three minutes")


class _Beacon(BaseHTTPRequestHandler):
    def _answer(self):
        if self.path.startswith("/closing"):
            _state["closing"] = True
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    do_GET = do_POST = do_OPTIONS = _answer

    def log_message(self, *args):                          # keep the log quiet
        pass


def start() -> str:
    """Start watching (once per server). Returns the address the page reports its closing to."""
    with _lock:
        if _state["url"] is None:
            listener = ThreadingHTTPServer(("127.0.0.1", 0), _Beacon)     # any free port; only this computer can reach it
            threading.Thread(target=listener.serve_forever, daemon=True).start()
            threading.Thread(target=_watch, daemon=True).start()
            atexit.register(stop_children)
            _state["url"] = f"http://127.0.0.1:{listener.server_address[1]}/closing"
        return _state["url"]


def relaunch(port: int, headless: bool) -> None:
    """Start this server again in place, keeping the pid. Used when the user changes the look: Streamlit reads its
    widget theme only at start-up. The browser reconnects by itself a few seconds later."""
    _log("relaunching to apply the chosen look")
    stop_children()
    sys.stdout.flush(); sys.stderr.flush()
    argv = [sys.executable, "-W", "ignore", "-m", "cellsurveillance", "app", "--port", str(port)] + (["--headless"] if headless else [])
    os.execv(sys.executable, argv)


def die_with_parent(parent: int = 0) -> None:
    """For a process started by another: stop if that one disappears, however it went.

    `parent` is the pid of the process that started this one. Pass it whenever it is known: a process
    that reads its parent only once it is up can already have lost it (starting takes seconds), would
    then take the system for its parent, and would never stop.
    """
    def leave():
        if os.getpgrp() == os.getpid():                    # own group: take the worker processes along
            os.killpg(os.getpgrp(), signal.SIGTERM)
        os._exit(1)

    parent = parent or os.getppid()
    if os.getppid() != parent:                             # it was gone before this process was ready
        leave()

    def watch():
        while True:
            time.sleep(CHECK_S)
            if os.getppid() != parent:
                leave()

    threading.Thread(target=watch, daemon=True).start()


def worker_start(parent: int) -> None:
    """Start-up hook for worker processes: a worker never outlives the process that owns it."""
    die_with_parent(parent)
