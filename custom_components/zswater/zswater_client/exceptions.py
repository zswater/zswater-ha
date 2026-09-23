"""Exceptions raised by the Zhongshan Water client."""

from __future__ import annotations

from typing import Any


class ZSWaterError(Exception):
    """Base class for every error raised by this package."""


class ZSWaterTransportError(ZSWaterError):
    """The portal could not be reached, or answered with a non-JSON body."""


class ZSWaterAuthError(ZSWaterError):
    """The portal rejected our credentials or the stored token expired.

    The web client treats envelope ``status == 11`` as "session gone, send the
    user back to the login page", which is exactly the semantics of this class.
    """


class ZSWaterApiError(ZSWaterError):
    """The portal understood the request but refused it.

    Carries the portal's own ``status``/``errcode``/``message`` fields so the
    user sees the operator's wording rather than a generic failure.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        errcode: Any | None = None,
        payload: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.errcode = errcode
        self.payload = payload
