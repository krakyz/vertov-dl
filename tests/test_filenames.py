import pytest
from media_loader.filenames import download_filename


@pytest.mark.parametrize("title", ["CON", "nul.txt", "LPT1", "COM9.any"])
def test_windows_reserved_names(title):
    assert download_filename(title, ".mp4", "1234567890").startswith("media-")


def test_unicode_symbols_and_length():
    title = "АУК В 21:45. Общаемся (кто ставит лайк того благодарю от души❤️)"
    name = download_filename(title, ".mp4", "1234567890")
    assert name == "АУК В 21 — 45. Общаемся (кто ставит лайк того благодарю от души) [12345678].mp4"
    assert download_filename("e\u0301", ".mp3", "abc") == "é [abc].mp3"
    name = download_filename("я" * 500 + "👨‍👩‍👧‍👦", ".mp4", "12345678")
    assert len(name.encode()) <= 220 and name.endswith("[12345678].mp4")
    assert "_" not in name


def test_unsafe_names_never_change_server_path():
    for title in ['../a\\b|c:*?<>"', "\x00\r\n", "  ... ", "👩🏽‍💻"]:
        result = download_filename(title, ".mp4", "abcdef12")
        assert not any(char in result for char in '/\\:*?<>"\x00\r\n')
        assert not result.endswith((" ", "."))
        assert result.endswith("[abcdef12].mp4")
