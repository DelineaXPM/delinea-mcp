"""Session management for Delinea API."""

from __future__ import annotations

from delinea_api import DelineaSession


class SessionManager:
    """Manages the Delinea API session lifecycle.

    This class provides a centralized way to manage the DelineaSession instance,
    making it easier to initialize, access, and mock in tests.
    """

    _session: DelineaSession | None = None

    @classmethod
    def init(cls, session: DelineaSession) -> None:
        """Initialize the session manager with a DelineaSession instance.

        Parameters
        ----------
        session : DelineaSession
            The authenticated Delinea API session to use.
        """
        cls._session = session

    @classmethod
    def get(cls) -> DelineaSession:
        """Get the current session instance.

        Returns
        -------
        DelineaSession
            The active Delinea API session.

        Raises
        ------
        RuntimeError
            If the session has not been initialized via init().
        """
        if cls._session is None:
            raise RuntimeError("Delinea session not initialised")
        return cls._session
