import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.action_state_machine import ActionState
from core.intent_arbiter import IntentDecision, IntentOwner
from gui import main_window
from platform_services.contracts import ActionResult


def test_arbitrated_drag_request_keeps_core_pointer_semantics_during_raw_pose_noise():
    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    dispatched = []
    try:
        window.control_session.state = main_window.SessionState.POINTER
        window.action_machine.state = ActionState.DRAGGING
        window.action_coordinator.dispatch = lambda request: dispatched.append(request) or ActionResult(True)
        decision = IntentDecision(
            owner=IntentOwner.POINTER,
            effective_pointer_gesture="pinch_hold",
            allow_pointer=True,
            allow_combo=False,
            allow_dynamic=False,
        )

        window.execute_action(
            "peace",
            (100, 100),
            (480, 640, 3),
            {"distance": 20, "velocity": 0, "is_approaching": False},
            intent_decision=decision,
        )

        assert dispatched[-1].action == "drag"
        assert dispatched[-1].gesture == "pinch_hold"
        assert dispatched[-1].core_pointer is True
    finally:
        window.close()
