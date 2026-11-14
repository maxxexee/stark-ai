"""Durations said the way a person would say them, for replies read aloud."""

from __future__ import annotations


class Phrases:
    @staticmethod
    def ago(seconds: int) -> str:
        """"30 seconds" / "2 minutes"."""
        if seconds < 60:
            return f"{max(seconds, 1)} seconds"
        minutes = round(seconds / 60)
        return f"{minutes} minute" + ("s" if minutes != 1 else "")

    @staticmethod
    def window(minutes: int) -> str:
        """How long a request waits: "an hour", "2 days", "45 minutes"."""
        if minutes % 1440 == 0:
            days = minutes // 1440
            return "a day" if days == 1 else f"{days} days"
        if minutes % 60 == 0:
            hours = minutes // 60
            return "an hour" if hours == 1 else f"{hours} hours"
        return f"{minutes} minutes"
