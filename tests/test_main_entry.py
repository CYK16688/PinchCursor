import main as app_entry


def test_second_application_instance_exits_nonzero_before_creating_qapplication(monkeypatch):
    created = []

    class RejectedGuard:
        def acquire(self):
            return False

        def release(self):
            raise AssertionError("a rejected guard must not be released")

    monkeypatch.setattr(app_entry, "SingleInstanceGuard", RejectedGuard)
    monkeypatch.setattr(app_entry, "QApplication", lambda *_args: created.append(True))

    assert app_entry.main() == 1
    assert created == []
