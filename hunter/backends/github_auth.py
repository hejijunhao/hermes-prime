"""GitHub App authentication — JWT → installation access token exchange.

Generates short-lived (1 hour) installation tokens from a GitHub App's
private key.  Tokens are cached and automatically refreshed when they
expire (with a 5-minute safety margin).

Environment variables:
    GITHUB_APP_ID              — numeric App ID
    GITHUB_APP_PRIVATE_KEY     — PEM-encoded RSA private key (newlines as \\n)
    GITHUB_APP_INSTALLATION_ID — numeric installation ID
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import jwt
import requests

logger = logging.getLogger(__name__)

# Refresh tokens 5 minutes before they actually expire.
_EXPIRY_MARGIN_S = 300


@dataclass
class _CachedToken:
    token: str
    expires_at: float  # time.time() epoch


class GitHubAppAuth:
    """Manages GitHub App authentication and token lifecycle."""

    def __init__(
        self,
        app_id: str,
        private_key: str,
        installation_id: str,
    ):
        self.app_id = app_id
        self.private_key = private_key.replace("\\n", "\n")
        self.installation_id = installation_id
        self._cached: Optional[_CachedToken] = None

    @classmethod
    def from_env(cls) -> "GitHubAppAuth":
        """Create from environment variables.

        Raises:
            ValueError: If any required variable is missing.
        """
        required = {
            "GITHUB_APP_ID": "GitHub App numeric ID",
            "GITHUB_APP_PRIVATE_KEY": "PEM-encoded private key",
            "GITHUB_APP_INSTALLATION_ID": "Installation ID",
        }
        missing = [
            f"  {var} — {desc}"
            for var, desc in required.items()
            if not os.environ.get(var)
        ]
        if missing:
            raise ValueError(
                "Missing GitHub App environment variables:\n"
                + "\n".join(missing)
            )
        return cls(
            app_id=os.environ["GITHUB_APP_ID"],
            private_key=os.environ["GITHUB_APP_PRIVATE_KEY"],
            installation_id=os.environ["GITHUB_APP_INSTALLATION_ID"],
        )

    def _create_jwt(self) -> str:
        """Create a short-lived JWT signed with the App's private key."""
        now = int(time.time())
        payload = {
            "iat": now - 60,  # clock skew tolerance
            "exp": now + 600,  # 10 minute max
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def get_token(self) -> str:
        """Return a valid installation access token, refreshing if needed."""
        if self._cached and time.time() < self._cached.expires_at:
            return self._cached.token

        token_jwt = self._create_jwt()
        resp = requests.post(
            f"https://api.github.com/app/installations/{self.installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {token_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        self._cached = _CachedToken(
            token=data["token"],
            # GitHub returns ISO timestamp but we just use 1hr minus margin
            expires_at=time.time() + 3600 - _EXPIRY_MARGIN_S,
        )
        logger.info("GitHub App installation token refreshed (valid ~55min)")
        return self._cached.token
