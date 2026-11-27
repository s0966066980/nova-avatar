# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Expand Arabic digits in training transcripts to Chinese characters.

Training text becomes tokens through a lexicon that has no number rules (the
inference engine applies ``number-zh.fst`` and friends, training does not), so
any digit left in a transcript would be silently dropped and the text would no
longer match the audio. This module turns digits into Chinese characters before
the administrator reviews a line, and reports everything it cannot decide
instead of guessing.

``normalize_digits`` is deterministic and pure. Its conventions:

Resolved (expanded):

- Integers are quantities: ``15`` -> ``十五``, ``101`` -> ``一百零一``, ``110`` ->
  ``一百一十``, ``0`` -> ``零``. The digit 2 is always ``二`` (never ``兩``); a
  recording that says ``兩個`` is fixed by editing the line text.
- Comma-grouped integers (``1,234``) are quantities, up to 12 digits.
- Exactly four digits followed by ``年`` are a year read digit by digit:
  ``2026年`` -> ``二零二六年``. One to three digits before ``年`` are a
  quantity (``3年``, ``民國115年`` -> ``民國一百一十五年``).
- One or two digits before ``月``, ``日`` or ``號`` are a quantity and drop leading
  zeros: ``11月24日`` -> ``十一月二十四日``, ``05月`` -> ``五月``.
- Decimals read the integer part as a quantity and the fraction digit by digit
  after ``點``: ``3.5`` -> ``三點五``, ``3.50`` -> ``三點五零``.
- ``N%`` is ``百分之`` plus the number: ``50%`` -> ``百分之五十``.
- Phone-like strings are read digit by digit, with ``零一二三四五六七八九`` (1 is
  ``一``, not ``幺``) and hyphens dropped: Taiwan formats such as
  ``02-2345-6789`` and ``0912-345-678``, any digit run with a leading zero and
  at least two digits (``007``), and any plain digit run of eight or more digits.
- Full-width digits are read as ASCII digits.

Unresolved (the text keeps the original characters and the span is reported
with a reason code, so the review table can flag it):

- ``currency``: ``$50``, ``NT$300``, ``300USD``, ``USD 5``.
- ``time_or_ratio``: ``12:30``, ``3:2`` (a time and a ratio read differently).
- ``numeric_date``: ``2026-11-24``, ``11/24/2026``.
- ``slash``: ``1/2`` (fraction or date).
- ``range``: ``10-20``, ``5~8``.
- ``mixed_unit``: digits stuck to Latin letters, such as ``5kg``, ``3.5GHz``,
  ``GPT4``, ``RTX4090``, ``COVID-19``, ``3x4``.
- ``dotted``: ``1.2.3`` (version or date).
- ``signed``: a sign right before a digit, such as ``-5`` or ``+886``.
- ``degree``: ``20°C``; ``permille``: ``5‰``.
- ``ambiguous_year``: a bare four-digit number from 1900 to 2099 without ``年``
  (a year or a quantity).
- ``ambiguous_long_number``: five to seven plain digits (a quantity or a code),
  and any ``%`` number whose digits cannot be read as a quantity.
- ``ambiguous_decimal``: a decimal whose integer part has a leading zero
  (``007.5``) or more than eight digits.

An unresolved token is never partly expanded, and no digit is ever dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS = "零一二三四五六七八九"
_FULL_WIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_MAX_QUANTITY_DIGITS = 12
_MAX_DECIMAL_INTEGER_DIGITS = 8

_PATTERN = re.compile(
    r"""
    (?P<phone>(?<![\d.])0\d{1,3}-\d{3,4}-\d{3,4}(?!\d)|(?<![\d.])0\d{1,3}-\d{6,8}(?!\d))
    |(?P<currency>
        (?:NT\$|US\$|HK\$|USD|NTD|TWD|RMB|CNY|EUR|JPY|[$¥￥€£])\s?\d[\d,]*(?:\.\d+)?
        |\d[\d,]*(?:\.\d+)?\s?(?:NT\$|US\$|HK\$|USD|NTD|TWD|RMB|CNY|EUR|JPY|[$¥￥€£])
    )
    |(?P<mixed_unit>
        \d+(?:[.,]\d+)*[A-Za-z][A-Za-z0-9]*
        |[A-Za-z][A-Za-z0-9]*-?\d[A-Za-z0-9]*
    )
    |(?P<numeric_date>\d{1,4}[/-]\d{1,2}[/-]\d{1,4})
    |(?P<slash>\d+/\d+)
    |(?P<time_or_ratio>\d+[:：]\d+(?:[:：]\d+)?)
    |(?P<range>\d+(?:\.\d+)?\s?[-~～–—]\s?\d+(?:\.\d+)?)
    |(?P<signed>(?<![A-Za-z0-9])[+\-−]\d+(?:\.\d+)?)
    |(?P<degree>\d+(?:\.\d+)?\s?(?:°[CFcf]?|[℃℉]))
    |(?P<permille>\d+(?:\.\d+)?\s?‰)
    |(?P<dotted>\d+(?:\.\d+){2,})
    |(?P<percent>\d+(?:,\d{3})*(?:\.\d+)?[%％])
    |(?P<number>\d+(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Unresolved:
    """A token the normaliser would not guess.

    ``start`` and ``end`` index the original input text; ``reason`` is one of the
    codes in the module docstring.
    """

    text: str
    start: int
    end: int
    reason: str


@dataclass(frozen=True)
class NormalizedText:
    """The expanded text and the tokens left as written."""

    text: str
    unresolved: tuple[Unresolved, ...] = ()

    @property
    def resolved(self) -> bool:
        return not self.unresolved


def normalize_digits(text: str) -> NormalizedText:
    """Expand digits and dates in ``text`` to Chinese characters; see module docs."""
    source = text.translate(_FULL_WIDTH)
    pieces: list[str] = []
    unresolved: list[Unresolved] = []
    cursor = 0
    for match in _PATTERN.finditer(source):
        pieces.append(source[cursor : match.start()])
        token = match.group()
        group = match.lastgroup or ""
        following = source[match.end() : match.end() + 1]
        expanded, reason = _expand(group, token, following)
        if expanded is None:
            pieces.append(token)
            unresolved.append(Unresolved(token, match.start(), match.end(), reason))
        else:
            pieces.append(expanded)
        cursor = match.end()
    pieces.append(source[cursor:])
    return NormalizedText("".join(pieces), tuple(unresolved))


def _expand(group: str, token: str, following: str) -> tuple[str | None, str]:
    """The Chinese reading of one matched token, or ``(None, reason)``."""
    if group == "phone":
        return _digit_by_digit(token.replace("-", "")), ""
    if group == "percent":
        expanded, reason = _read_number(token[:-1], "")
        return (None, reason) if expanded is None else ("百分之" + expanded, "")
    if group == "number":
        return _read_number(token, following)
    return None, group


def _read_number(token: str, following: str) -> tuple[str | None, str]:
    """Read a plain, grouped or decimal number; ``following`` is the next character."""
    if "." in token:
        whole, fraction = token.replace(",", "").split(".")
        if (len(whole) > 1 and whole.startswith("0")) or len(whole) > _MAX_DECIMAL_INTEGER_DIGITS:
            return None, "ambiguous_decimal"
        return _quantity(int(whole)) + "點" + _digit_by_digit(fraction), ""
    if "," in token:
        digits = token.replace(",", "")
        if len(digits) > _MAX_QUANTITY_DIGITS:
            return None, "ambiguous_long_number"
        return _quantity(int(digits)), ""
    length = len(token)
    if following == "年" and length == 4:
        return _digit_by_digit(token), ""
    if following in "月日號" and following and length <= 2:
        return _quantity(int(token)), ""
    if (length > 1 and token.startswith("0")) or length >= 8:
        return _digit_by_digit(token), ""
    if length >= 5:
        return None, "ambiguous_long_number"
    if length == 4 and 1900 <= int(token) <= 2099:
        return None, "ambiguous_year"
    return _quantity(int(token)), ""


def _digit_by_digit(digits: str) -> str:
    return "".join(_DIGITS[int(digit)] for digit in digits)


def _group(value: int) -> str:
    """One to four digits (1..9999) as Chinese, with inner zeros as ``零``."""
    out = ""
    pending_zero = False
    for digit, unit in zip(f"{value:04d}", ("千", "百", "十", ""), strict=True):
        if digit == "0":
            pending_zero = bool(out)
            continue
        if pending_zero:
            out += "零"
            pending_zero = False
        out += _DIGITS[int(digit)] + unit
    return out


def _quantity(value: int) -> str:
    """A non-negative integer below 10**12 read as a quantity."""
    if value == 0:
        return "零"
    out = ""
    pending_zero = False
    for part, unit in ((value // 10**8, "億"), (value // 10**4 % 10**4, "萬"), (value % 10**4, "")):
        if part == 0:
            pending_zero = bool(out)
            continue
        if out and (pending_zero or part < 1000):
            out += "零"
        pending_zero = False
        out += _group(part) + unit
    # 10..19 and 100000 start with 十, not 一十.
    return out[1:] if out.startswith("一十") else out
