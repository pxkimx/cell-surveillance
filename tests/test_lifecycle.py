"""The app must not leave anything running after it is closed."""
import os
import signal
import subprocess
import sys
import textwrap
import time

from cellsurveillance import lifecycle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def wait_gone(pid, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_rule_for_quitting():
    step = lifecycle.should_quit
    state = (False, False, 0, False)
    for _ in range(500):                                   # nobody has opened the app: it waits
        state = step(0, *state[1:])
        assert not state[0]
    quit_now, seen, empty, closing = step(1, False, 0, False)
    for i in range(lifecycle.AFTER_CLOSE):                 # the page said it was closing
        quit_now, seen, empty, closing = step(0, seen, empty, True)
        assert quit_now == (i == lifecycle.AFTER_CLOSE - 1)
    assert step(1, True, 2, True) == (False, True, 0, False)   # a reload reconnects and cancels it
    empty = 0
    for i in range(lifecycle.AFTER_SILENCE):               # disconnected without a word
        quit_now, seen, empty, closing = step(0, True, empty, False)
        assert quit_now == (i == lifecycle.AFTER_SILENCE - 1)


def test_quitting_stops_a_running_analysis_and_its_workers():
    code = "import subprocess, sys, time; subprocess.Popen(['sleep', '60']); print('up', flush=True); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
    assert proc.stdout.readline().strip() == "up"
    workers = subprocess.run(["pgrep", "-g", str(proc.pid)], capture_output=True, text=True).stdout.split()
    assert len(workers) == 2                               # the analysis and its worker share one group
    lifecycle.register_child(proc)
    lifecycle.stop_children()
    proc.wait(timeout=10)
    assert all(wait_gone(int(pid)) for pid in workers)


def test_an_analysis_does_not_outlive_the_app():
    child = textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {ROOT!r})
        from cellsurveillance import lifecycle
        lifecycle.CHECK_S = 0.2
        lifecycle.die_with_parent()
        print(os.getpid(), flush=True)
        time.sleep(60)
    """)
    parent = ("import subprocess, sys, time; "
              f"p = subprocess.Popen([sys.executable, '-c', {child!r}], stdout=subprocess.PIPE, text=True, start_new_session=True); "
              "print(p.stdout.readline().strip(), flush=True); time.sleep(60)")
    app = subprocess.Popen([sys.executable, "-c", parent], stdout=subprocess.PIPE, text=True)
    analysis = int(app.stdout.readline())
    assert alive(analysis)
    app.send_signal(signal.SIGKILL)                        # the app dies without a chance to clean up
    app.wait()
    assert wait_gone(analysis)


def test_an_analysis_started_after_the_app_died_stops_at_once():
    code = (f"import sys; sys.path.insert(0, {ROOT!r}); from cellsurveillance import lifecycle; "
            "lifecycle.die_with_parent(999999); print('still here', flush=True)")   # a pid that is not its parent
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert out.returncode == 1 and "still here" not in out.stdout


def test_workers_do_not_outlive_a_killed_analysis(tmp_path):
    script = tmp_path / "pool.py"
    script.write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {ROOT!r})
        from concurrent.futures import ProcessPoolExecutor
        from cellsurveillance import lifecycle

        def start(parent):
            lifecycle.CHECK_S = 0.2
            lifecycle.worker_start(parent)

        def whoami(_):
            time.sleep(0.3)
            return os.getpid()

        if __name__ == "__main__":
            with ProcessPoolExecutor(3, initializer=start, initargs=(os.getpid(),)) as pool:
                print(" ".join(map(str, sorted(set(pool.map(whoami, range(9)))))), flush=True)
                list(pool.map(time.sleep, [60] * 3))
    """))
    analysis = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    workers = [int(pid) for pid in analysis.stdout.readline().split()]
    assert workers and all(alive(pid) for pid in workers)
    analysis.send_signal(signal.SIGKILL)                   # killed alone, as from Activity Monitor
    analysis.wait()
    assert all(wait_gone(pid) for pid in workers)

