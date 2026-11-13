"""Which browser origins may call the API: local dev on any port, and hellostark.xyz
with any of its subdomains over https. Shared by the CORS middleware and the 500
handler, which answers from outside that middleware."""

from __future__ import annotations

import re

ALLOWED_ORIGIN = re.compile(
    r"http://(localhost|127\.0\.0\.1)(:\d+)?|https://([a-z0-9-]+\.)*hellostark\.xyz"
)
