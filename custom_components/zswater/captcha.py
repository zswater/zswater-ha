"""Short-lived HTTP endpoint that serves 图形验证码 images to a config flow.

Home Assistant's config-flow forms are text-only, so there is no way to render
the login captcha inline. Instead the flow registers the fetched PNG here under
a random single-use token and puts a link to it in the step description; the
user opens the link in the same browser and types the four digits back.

``requires_auth`` is ``False`` on purpose: the frontend authenticates API calls
with a bearer token, which a plain link click does not carry, so an
authenticated route would always answer 401. The random token, the five-minute
TTL and the fact that the entry is consumed on first read are what keep the
endpoint from leaking anything.
"""

from __future__ import annotations

import logging
import time

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CAPTCHA_TTL, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_CAPTCHA = "captcha_store"
DATA_CAPTCHA_VIEW = "captcha_view_registered"

#: ``{token: (stored_at, image_bytes)}``
CaptchaStore = dict[str, "tuple[float, bytes]"]


def _store(hass: HomeAssistant) -> CaptchaStore:
    return hass.data.setdefault(DOMAIN, {}).setdefault(DATA_CAPTCHA, {})


def _prune(store: CaptchaStore) -> None:
    """Drop expired images so the store cannot grow without bound."""
    deadline = time.monotonic() - CAPTCHA_TTL
    for token in [key for key, (stored_at, _) in store.items() if stored_at < deadline]:
        store.pop(token, None)


def async_store_captcha(hass: HomeAssistant, token: str, image: bytes) -> None:
    """Publish ``image`` under ``token`` for :data:`CAPTCHA_TTL` seconds."""
    store = _store(hass)
    _prune(store)
    store[token] = (time.monotonic(), image)


class ZSWaterCaptchaView(HomeAssistantView):
    """Serve a captcha image exactly once."""

    url = "/api/zswater/captcha/{token}"
    name = "api:zswater:captcha"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return the stored PNG, then forget it."""
        store = _store(self._hass)
        _prune(store)
        stored = store.pop(token, None)
        if stored is None:
            return web.Response(status=404, text="captcha not found or expired")
        _stored_at, image = stored
        return web.Response(
            body=image,
            content_type="image/png",
            headers={"Cache-Control": "no-store"},
        )


def async_register_captcha_view(hass: HomeAssistant) -> None:
    """Register the captcha view once per Home Assistant instance."""
    if hass.data.setdefault(DOMAIN, {}).get(DATA_CAPTCHA_VIEW):
        return
    hass.http.register_view(ZSWaterCaptchaView(hass))
    hass.data[DOMAIN][DATA_CAPTCHA_VIEW] = True
    _LOGGER.debug("Registered captcha endpoint at %s", ZSWaterCaptchaView.url)


__all__ = [
    "DATA_CAPTCHA",
    "ZSWaterCaptchaView",
    "async_register_captcha_view",
    "async_store_captcha",
]
