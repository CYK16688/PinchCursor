from platform_services.contracts import ActionRequest
from platform_services.null import UnavailableInputController


def test_unavailable_controller_never_reports_execution():
    result = UnavailableInputController("Not supported").execute(
        ActionRequest(action="move_cursor")
    )

    assert result.executed is False
    assert result.reason == "Not supported"
