"""Portable browser attachment names; never changes worker paths."""

import re
import unicodedata

RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def download_filename(title, extension, identifier):
    title = unicodedata.normalize("NFC", title)
    title = re.sub(r"[:/\\|]+", " — ", title)
    title = title.translate(
        str.maketrans(
            {'"': "'", "“": "'", "”": "'", "«": "'", "»": "'", "<": "(", ">": ")", "?": "", "*": ""}
        )
    )
    title = "".join(
        char
        for char in title
        if unicodedata.category(char) not in {"Cc", "Cf", "Cs", "So"}
        and char not in {"\ufe0e", "\ufe0f", "\u20e3"}
        and not 0x1F3FB <= ord(char) <= 0x1F3FF
    )
    title = re.sub(r"\s+", " ", title).strip(" .") or "media"
    if title.split(".")[0].upper() in RESERVED:
        title = "media-" + title
    extension = extension.lower() if re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", extension) else ".bin"
    suffix = f" [{identifier[:8]}]{extension}"
    while len((title + suffix).encode("utf-8")) > 220:
        title = title[:-1]
    return title.rstrip(" .") + suffix
