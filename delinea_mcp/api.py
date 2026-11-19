import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)
if os.getenv("DELINEA_DEBUG") and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG)  # pragma: no cover - config

DEFAULT_TIMEOUT = 10

# Lists the vaults connected to a Platform tenant, each with its URL. Readable
# with the same xpmheadless token the Platform sign-in returns.
VAULT_BROKER_PATH = "/vaultbroker/api/vaults"


def platform_host(value: str | None) -> str:
    """Return the bare hostname (and port) of a Platform hostname or URL.

    The setting may be pasted from a browser's address bar, so
    ``https://example.delinea.app/`` and ``example.delinea.app`` both give
    ``example.delinea.app``. Callers always connect with ``https://``.
    """
    value = (value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value if "://" in value else f"https://{value}")
    return parts.netloc.rpartition("@")[2]


def select_vault_url(vaults: list[Any], platform: str) -> str:
    """Pick the Secret Server URL from a vault broker ``vaults`` list.

    Uses the active Secret Server vault marked as the tenant's default (then
    the global default), or the only active one. Only ``https`` URLs are
    accepted, since the Platform token is sent there.
    """
    candidates = []
    for vault in vaults:
        if not isinstance(vault, dict) or vault.get("isActive") is False:
            continue
        kind = str(vault.get("type") or "")
        if kind and "secretserver" not in kind.lower():
            continue
        url = str((vault.get("connection") or {}).get("url") or "").strip()
        if url.lower().startswith("https://"):
            candidates.append((vault, url.rstrip("/")))
    for flag in ("isDefault", "isGlobalDefault"):
        for vault, url in candidates:
            if vault.get(flag):
                return url
    if len(candidates) == 1:
        return candidates[0][1]
    override = (
        "Set the Secret Server URL override in the plugin settings "
        "(DELINEA_BASE_URL or delinea_base_url for the standalone server)"
    )
    if not candidates:
        raise ValueError(
            f"The Delinea Platform tenant {platform} has no active Secret "
            f"Server vault. {override}."
        )
    listed = ", ".join(url for _, url in candidates)
    raise ValueError(
        f"The Delinea Platform tenant {platform} has several Secret Server "
        f"vaults and none is marked as the default ({listed}). {override} to "
        "the one to use."
    )


# What the caller can do about each failure class. Tool errors are read by
# the model, so a status code alone ("400 Client Error") is not enough to
# pick a next step.
_STATUS_HINTS = {
    400: "The request was rejected as invalid; check parameter names and values.",
    401: (
        "Authentication failed even after re-authenticating; verify the "
        "configured Delinea credentials."
    ),
    403: (
        "The configured account lacks permission for this object or action; "
        "an administrator must grant it."
    ),
    404: (
        "The object does not exist or is not visible to the configured "
        "account; verify the ID with a search tool."
    ),
    409: "The request conflicts with the object's current state.",
    429: "The API is rate limiting requests; wait and retry.",
}


# Secret Server's errorCode is more precise than the HTTP status: it answers
# a missing secret with 400 API_AccessDenied and invalid report SQL with 500.
_ERROR_CODE_HINTS = {
    "API_AccessDenied": (
        "The object doesn't exist or the configured account can't access it; "
        "verify the ID with a search tool, or ask an administrator for access."
    ),
    "API_InvalidSql": (
        "The SQL isn't valid for Secret Server reporting; build it from the "
        "tables and examples in list_example_reports."
    ),
}


# Secret Server 12.1+ turns on "Prevent direct API authentication" for new
# installations (on-premises and Cloud). It rejects the /oauth2/token password
# grant used by ``DelineaSession.authenticate`` unless the account is an
# Application Account or holds the "Bypass Direct API Authentication
# Restriction" role permission, so say that instead of a bare 400.
_DIRECT_API_AUTH_HINT = (
    "Check the username and password. If they're correct, check that the "
    "account is a Secret Server Application Account or holds the 'Bypass "
    "Direct API Authentication Restriction' permission: Secret Server 12.1+ "
    "enables 'Prevent direct API authentication' by default on new "
    "installations, which rejects /oauth2/token password logins for "
    "interactive user accounts."
)
_SIGN_IN_HINTS = dict.fromkeys((400, 401, 403), _DIRECT_API_AUTH_HINT)


def redact(message: str, value: str | None) -> str:
    """Mask *value* wherever it appears in *message*.

    Error text built from API responses must never carry a secret the caller
    just submitted, even if a server echoes it in a validation message.
    """
    if value and len(value) >= 4:
        message = message.replace(value, "********")
    return message


class DelineaAPIError(requests.HTTPError):
    """HTTP error whose message carries the API's explanation and a hint."""

    def __init__(self, message: str, response: requests.Response) -> None:
        super().__init__(message, response=response)
        self.status_code = response.status_code


def _api_error_detail(response: requests.Response) -> str:
    """Extract the human-readable reason from a Delinea error body."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:300]
    if not isinstance(body, dict):
        return str(body)[:300]
    parts = [
        str(body[k])
        for k in ("message", "Message", "messageDetail", "error_description", "error")
        if body.get(k)
    ]
    model_state = body.get("modelState")
    if isinstance(model_state, dict):
        for field_name, errors in model_state.items():
            if isinstance(errors, list):
                errors = "; ".join(str(e) for e in errors)
            parts.append(f"{field_name}: {errors}")
    if body.get("errorCode"):
        parts.append(f"(errorCode {body['errorCode']})")
    # De-duplicate while keeping order (message and messageDetail often match).
    return " ".join(dict.fromkeys(parts))[:500]


def raise_for_status(
    response: requests.Response, action: str, hints: dict[int, str] | None = None
) -> None:
    """Raise :class:`DelineaAPIError` with an actionable message on failure.

    *hints* overrides the next-step hint for specific status codes.
    """
    if response.status_code < 400:
        return
    reason = getattr(response, "reason", "") or ""
    message = f"{action} failed: HTTP {response.status_code} {reason}".rstrip()
    detail = _api_error_detail(response)
    if detail:
        message += f" - {detail}"
    code_hint = next((h for c, h in _ERROR_CODE_HINTS.items() if c in detail), None)
    if hints and response.status_code in hints:
        hint = hints[response.status_code]
    elif code_hint:
        hint = code_hint
    elif response.status_code >= 500:
        hint = "The server reported an internal error; retry, or run health_check."
    else:
        hint = _STATUS_HINTS.get(response.status_code, "")
    if hint:
        message += f". {hint}"
    raise DelineaAPIError(message, response)


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
        self.base_url = (self.base_url or os.getenv("DELINEA_BASE_URL") or "").strip()
        self.platform_hostname = platform_host(
            self.platform_hostname or os.getenv("PLATFORM_HOSTNAME", "")
        )
        if not self.base_url and not self.platform_hostname:
            self.base_url = "https://localhost/SecretServer"
        logger.debug(
            "Initialising session for %s",
            self.base_url or f"the vault of {self.platform_hostname}",
        )
        self.session = requests.Session()
        self.token: str | None = None
        # Automatically authenticate using the provided username or environment
        # variables so that requests may be sent immediately.
        if self.platform_hostname:
            self.authenticate_platform()
            # The Secret Server URL is optional with a Platform tenant: an
            # explicit one overrides the vault the Platform reports.
            if not self.base_url:
                self.base_url = self.discover_vault_url()
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
        raise_for_status(
            response, f"Secret Server sign-in as {username!r}", _SIGN_IN_HINTS
        )
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
        url = f"https://{self.platform_hostname}/identity/api/oauth2/token/xpmplatform"
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
        raise_for_status(response, f"Platform sign-in as {client_id!r}")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("No token returned from Platform")
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        logger.debug("Platform authentication succeeded, token stored")
        return token

    def discover_vault_url(self) -> str:
        """Return the Secret Server URL the Platform tenant reports.

        Asks the Platform's vault broker (``GET /vaultbroker/api/vaults``)
        for the vaults connected to the tenant and picks the default one, so
        only the Platform URL needs configuring. Requires a Platform token.
        """
        url = f"https://{self.platform_hostname}{VAULT_BROKER_PATH}"
        logger.debug("Looking up the Secret Server vault at %s", url)
        response = self.session.get(
            url, timeout=float(os.getenv("DELINEA_TIMEOUT", DEFAULT_TIMEOUT))
        )
        raise_for_status(
            response,
            f"Secret Server vault lookup on {self.platform_hostname}",
            dict.fromkeys(
                (403, 404),
                "Set the Secret Server URL override in the plugin settings to "
                "skip the lookup.",
            ),
        )
        try:
            vaults = response.json().get("vaults") or []
        except (ValueError, AttributeError):
            vaults = []
        vault_url = select_vault_url(vaults, self.platform_hostname)
        logger.info("Using Secret Server %s from the Delinea Platform", vault_url)
        return vault_url

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
        raise_for_status(response, f"{method} {path}")
        return response
