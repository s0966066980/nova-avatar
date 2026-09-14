"""Deterministic, post-protocol normalization for LLM output."""

from __future__ import annotations

import re

from opencc import OpenCC

_TW = OpenCC("s2twp")
_SELF_IDENTITY = re.compile(
    r"(?P<prefix>(?:我(?:是|叫)|我的名字是)\s*)(?P<name>[^，。！？\n]{1,80})"
)
_IDENTITY_QUESTION = re.compile(r"你是誰|你叫什麼|你的(?:名字|名稱|身份)|自我介紹|介紹你自己")


def strip_unsolicited_self_introduction(
    text: str, *, user_message: str, assistant_name: str
) -> str:
    """Remove only an opening self-introduction when the user did not ask for it."""
    if not text or not assistant_name or _IDENTITY_QUESTION.search(user_message or ""):
        return text
    name = re.escape(assistant_name.strip())
    if not name:
        return text
    leading_intro = re.compile(
        rf"^\s*(?:您好[，,！!。\s]*)?(?:我(?:是|叫)|我的名字是)\s*{name}"
        r"(?:[，,。！!、\s]+(?:很高興(?:為您)?服務|很高興認識您|我可以協助您)[，,。！!、\s]*)?"
    )
    stripped = leading_intro.sub("", text).lstrip("，,。！!、 \n")
    return stripped or text


def normalize_output_text(text: str, *, locale: str = "zh-TW", enabled: bool = True) -> str:
    """Convert human-readable output after protocol parsing, not raw LLM output."""
    if not text or not enabled or locale.lower() != "zh-tw":
        return text
    # OpenCC's Taiwan phrase dictionary chooses 「影片」 for 视频. The product
    # output convention is 「視訊」, so apply that deterministic final term map.
    return _TW.convert(text).replace("影片", "視訊")


def normalize_assistant_identity(
    text: str, *, assistant_name: str, forbidden_names: list[str]
) -> str:
    """Replace forbidden names only in an explicit first-person identity claim."""
    if not text or not assistant_name:
        return text
    forbidden = [name.strip() for name in forbidden_names if str(name).strip()]
    if not forbidden:
        return text

    def replace(match: re.Match[str]) -> str:
        claimed = match.group("name").strip()
        if any(name in claimed for name in forbidden):
            return f"{match.group('prefix')}{assistant_name}"
        return match.group(0)

    return _SELF_IDENTITY.sub(replace, text)
