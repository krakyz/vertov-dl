import pytest
from media_loader.task import error_details


@pytest.mark.parametrize(
    "message,code",
    [
        ("Sign in to confirm you're not a bot", "authentication"),
        ("not a bot", "challenge"),
        ("captcha required", "challenge"),
        ("login required", "authentication"),
    ],
)
def test_cookie_recovery_message_keeps_error_category(message, code):
    assert error_details(message) == (
        code,
        "Обновите файл cookies.txt в настройках и повторите загрузку.",
    )


def test_network_and_forbidden_are_not_automatically_cookie_errors():
    assert error_details("HTTP Error 403")[0] == "access_denied"
    assert error_details("Connection timed out")[0] == "network"
