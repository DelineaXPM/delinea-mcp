import logging
import os
import threading
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)
if os.getenv("DELINEA_DEBUG") and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG)  # pragma: no cover - config

DEFAULT_TIMEOUT = 10


@dataclass
class DelineaSession:
    """Session for interacting with Delinea Secret Server.

    Credentials are read from ``DELINEA_USERNAME`` and ``DELINEA_PASSWORD``
    environment variables. Authentication is performed automatically on
    creation, storing the bearer token for subsequent requests.
    """

    # base_url is read at runtime so that tests may override the environment
    # variable after importing this module.
    base_url: str = ""
    username: str = ""
    platform_hostname: str = ""
    # Tools run on parallel worker threads; serialise re-authentication so
    # concurrent 401s don't race on token/header state.
    _auth_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.base_url = self.base_url or os.getenv(
            "DELINEA_BASE_URL", "https://localhost/SecretServer"
        )
        self.platform_hostname = self.platform_hostname or os.getenv(
            "PLATFORM_HOSTNAME", ""
        )
        logger.debug("Initialising session for %s", self.base_url)
        self.session = requests.Session()
        self.token: str | None = None
        # Automatically authenticate using the provided username or environment
        # variables so that requests may be sent immediately.
        if self.platform_hostname:
            self.authenticate_platform()
        else:
            self.authenticate(username=self.username or None)

    def authenticate(
        self, username: str | None = None, password: str | None = None
    ) -> str:
        """Authenticate and store bearer token.

        Parameters
        ----------
        username: optional username, defaults to ``DELINEA_USERNAME`` env var.
        password: optional password, defaults to ``DELINEA_PASSWORD`` env var.

        Returns
        -------
        str
            Access token returned by the server.
        """
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

    def authenticate_platform(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> str:
        """Authenticate via Delinea Platform client credentials.

        Calls ``POST https://<platform>/identity/api/oauth2/token/xpmplatform``
        with ``grant_type=client_credentials`` and ``scope=xpmheadless``.

        Parameters
        ----------
        client_id: defaults to ``DELINEA_USERNAME`` / ``DELINEA_USER`` env var.
        client_secret: defaults to ``DELINEA_PASSWORD`` env var.

        Returns
        -------
        str
            Access token issued by the Platform identity service.
        """
        client_id = (
            client_id
            or self.username
            or os.getenv("DELINEA_USERNAME")
            or os.getenv("DELINEA_USER")
        )
        client_secret = client_secret or os.getenv("DELINEA_PASSWORD")
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret required")
        hostname = self.platform_hostname.rstrip("/")
        if not hostname.startswith("http"):
            hostname = f"https://{hostname}"
        url = f"{hostname}/identity/api/oauth2/token/xpmplatform"
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "xpmheadless",
        }
        logger.debug("Authenticating via Platform at %s", url)
        response = self.session.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("No token returned from Platform")
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        logger.debug("Platform authentication succeeded, token stored")
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
            with self._auth_lock:
                if self.platform_hostname:
                    self.authenticate_platform()
                else:
                    self.authenticate()
            response = self.session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
