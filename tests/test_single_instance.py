import subprocess
import sys

from utils.single_instance import SingleInstanceGuard


def test_second_process_guard_is_rejected_until_first_guard_releases(tmp_path):
    lock_path = tmp_path / "gesture-control.lock"
    first = SingleInstanceGuard(lock_path)
    second = SingleInstanceGuard(lock_path)

    try:
        assert first.acquire() is True
        assert second.acquire() is False

        first.release()
        assert second.acquire() is True
    finally:
        first.release()
        second.release()


def test_release_is_idempotent_for_a_guard_that_never_acquired(tmp_path):
    guard = SingleInstanceGuard(tmp_path / "gesture-control.lock")

    guard.release()
    assert guard.acquire() is True
    guard.release()
    guard.release()


def test_second_process_cannot_acquire_the_guard_until_the_holder_exits(tmp_path):
    lock_path = tmp_path / "gesture-control.lock"
    hold_code = (
        "from utils.single_instance import SingleInstanceGuard; "
        f"guard = SingleInstanceGuard({str(lock_path)!r}); "
        "assert guard.acquire(); print('locked', flush=True); input(); guard.release()"
    )
    acquire_code = (
        "from utils.single_instance import SingleInstanceGuard; "
        f"guard = SingleInstanceGuard({str(lock_path)!r}); "
        "print(guard.acquire()); guard.release()"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", hold_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        blocked = subprocess.run(
            [sys.executable, "-c", acquire_code], text=True, capture_output=True, check=True
        )
        assert blocked.stdout.strip() == "False"

        holder.stdin.write("\n")
        holder.stdin.flush()
        assert holder.wait(timeout=5) == 0

        acquired = subprocess.run(
            [sys.executable, "-c", acquire_code], text=True, capture_output=True, check=True
        )
        assert acquired.stdout.strip() == "True"
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)
