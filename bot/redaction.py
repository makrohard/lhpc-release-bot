"""Nothing this bot writes anywhere may carry a credential.

There is a complete path from the token to a public page: the clone URL embeds it, git repeats
the failing command in its error, and the catch-all handler puts that error into an issue. Closing
it at each call site would only hold until the next one, so it is closed at the boundary — where
text leaves this process.
"""
from __future__ import annotations

import os
import re

PLACEHOLDER = "***"

# A credential reaches text two ways: as itself, or inside the URL it was interpolated into. The
# second is matched by SHAPE, because a run may hold a credential this process never read.
_URL_CREDENTIAL = re.compile(r"(https?://)[^\s/@]+(?::[^\s/@]*)?@")

# Short values are refused as secrets: an empty or one-character variable would otherwise redact
# every occurrence of that character and destroy the report it was meant to protect.
_MIN_SECRET = 8


def secrets() -> list:
    return [v for v in (os.environ.get("AUTO_RELEASE_TOKEN", ""),
                        os.environ.get("GITHUB_TOKEN", ""))
            if len(v) >= _MIN_SECRET]


def scrub(text) -> str:
    """`text` with every known secret and every URL-embedded credential replaced."""
    out = str(text)
    for value in secrets():
        out = out.replace(value, PLACEHOLDER)
    return _URL_CREDENTIAL.sub(rf"\1{PLACEHOLDER}@", out)
