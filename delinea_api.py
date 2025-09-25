import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)
if os.getenv("DELINEA_DEBUG") and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG)  # pragma: no cover - config

DEFAULT_TIMEOUT = 10


def _get_token_from_cli(timeout=10):
    """Get token from the tss CLI directly"""
    exe = shutil.which("tss")
    if not exe:
        raise RuntimeError("Command 'tss' not found in PATH!")

    try:
        proc = subprocess.run(
            [exe, "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(
            "The tss command has not responded in the allotted time."
        ) from err
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        raise RuntimeError(
            f"'The tss command threw an error (code {e.returncode}). {err}'"
        ) from e

    token = (proc.stdout or "").strip().strip('"').strip("'")
    if not token:
        raise RuntimeError("'The tss command didn't return any token.")

    return token


@dataclass
class DelineaSession:
    """Session for interacting with Delinea Secret Server.

    Credentials are read from ``DELINEA_USERNAME`` and ``DELINEA_PASSWORD``
    environment variables. Authentication is performed automatically on
    creation, storing the bearer token for subsequent requests.
    """

    # base_url is read at runtime so that tests may override the environment
    # variable after importing this module.
    use_sdk: bool = None
    base_url: str = ""
    username: str = ""

    def __post_init__(self) -> None:
        self.base_url = self.base_url or os.getenv(
            "DELINEA_BASE_URL", "https://localhost/SecretServer"
        )
        logger.debug("Initialising session for %s", self.base_url)
        self.session = requests.Session()
        self.token: str | None = None
        # Automatically authenticate using the provided username or environment
        # variables so that requests may be sent immediately.
        self.authenticate(use_sdk=self.use_sdk or False, username=self.username or None)

    def authenticate(
        self,
        use_sdk: bool | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """Authenticate and store bearer token.

        Parameters
        ----------
        use_sdk: optional use SDK CLI flag, defaults to False
        username: optional username, defaults to ``DELINEA_USERNAME`` env var.
        password: optional password, defaults to ``DELINEA_PASSWORD`` env var.

        Returns
        -------
        str
            Access token returned by the server.
        """

        if use_sdk:
            logger.debug("Authenticating using sdk CLI")
            token = _get_token_from_cli()
            self.token = token
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            logger.debug("Authentication using sdk CLI succeeded, token stored")
            return token

        username = (
            username or os.getenv("DELINEA_USERNAME") or os.getenv("DELINEA_USER")
        )
        password = password or os.getenv("DELINEA_PASSWORD")
        if not username or not password:
            raise ValueError("username and password required")
        url = self.base_url.rstrip("/") + "/oauth2/token"
        data = {"username": username, "password": password, "grant_type": "password"}
        logger.debug("Authenticating against %s", url)
        response = self.session.post(url, data=data)
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token") or payload.get("generatedToken")
        if not token:
            raise RuntimeError("No token returned")
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        logger.debug("Authentication succeeded, token stored")
        return token

    def request(
        self, method: str, path: str, timeout: float | None = None, **kwargs
    ) -> requests.Response:
        """Perform an authenticated request with a default timeout."""
        url = self.base_url.rstrip("/") + "/api" + path
        if timeout is None:
            timeout = float(os.getenv("DELINEA_TIMEOUT", DEFAULT_TIMEOUT))
        logger.debug("Request %s %s", method, url)
        response = self.session.request(method, url, timeout=timeout, **kwargs)
        if response.status_code == 401:
            logger.info("Authentication expired, re-authenticating")
            self.authenticate()
            response = self.session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
