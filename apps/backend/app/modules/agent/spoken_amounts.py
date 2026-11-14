"""Naira figures in what the user said, for checking the one the model chose.

A figure nobody said is a figure nobody agreed to, so `pay_bill` only charges an
amount that is in the utterance. Read by splitting the words, not by pattern.
"""

from __future__ import annotations


class SpokenAmounts:
    """Reads "₦5,000", "5000", "5k", "1.5k" and spoken numbers up to the thousands
    ("five thousand", "two thousand five hundred"). Numbers longer than nine digits
    are meter and phone numbers, not amounts."""

    _ONES = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19,
    }
    _TENS = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }
    _LONGEST_AMOUNT_DIGITS = 9

    @classmethod
    def figures(cls, text: str) -> list[int]:
        """Every figure said, in the order said. Each run of number words is one
        figure: "home with 5000 and office with three thousand" is two."""
        heard = text.lower().replace(",", "").replace("₦", " ").replace("naira", " ")
        words = cls._words(heard)
        found: list[int] = []
        total = current = 0
        counting = False
        for index, word in enumerate(words):
            if word in cls._ONES:
                current += cls._ONES[word]
            elif word in cls._TENS:
                current += cls._TENS[word]
            elif word == "hundred":
                current = max(current, 1) * 100
            elif word == "thousand":
                total += max(current, 1) * 1000
                current = 0
            elif word == "and" and counting:
                continue
            else:
                if total + current > 0:
                    found.append(total + current)
                total = current = 0
                counting = False
                following = words[index + 1] if index + 1 < len(words) else ""
                figure = cls._figure(word, following)
                if figure is not None:
                    found.append(figure)
                continue
            counting = True
        if total + current > 0:
            found.append(total + current)
        return found

    @staticmethod
    def _words(text: str) -> list[str]:
        """Runs of letters, digits and dots. A dot at either end is punctuation."""
        words: list[str] = []
        current: list[str] = []
        for char in text:
            if char.isalnum() or char == ".":
                current.append(char)
                continue
            if current:
                words.append("".join(current).strip("."))
                current = []
        if current:
            words.append("".join(current).strip("."))
        return [word for word in words if word]

    @classmethod
    def _figure(cls, word: str, following: str) -> int | None:
        """A written figure: "5000", "5k", or "1.5" when the next word is "k".
        A bare decimal is not an amount: naira are whole."""
        if word.endswith("k"):
            number, thousands = word[:-1], True
        else:
            number, thousands = word, following == "k"
        whole, dot, fraction = number.partition(".")
        if not whole.isdecimal() or (dot and not fraction.isdecimal()):
            return None
        if thousands:
            return round(float(number) * 1000)
        if dot or len(whole) > cls._LONGEST_AMOUNT_DIGITS:
            return None
        return int(whole)
