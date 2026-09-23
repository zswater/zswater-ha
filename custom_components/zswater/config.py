"""Configuration helpers for the Zhongshan Water integration."""

from __future__ import annotations

import socket

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HISTORY_DAYS,
    CONF_IP_FAMILY,
    CONF_SETTINGS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_IP_FAMILY,
    DEFAULT_UPDATE_INTERVAL,
    IP_FAMILY_AUTO,
    IP_FAMILY_IPV4,
    IP_FAMILY_IPV6,
)

IP_FAMILY_TO_SOCKET: dict[str, int] = {
    IP_FAMILY_IPV4: socket.AF_INET,
    IP_FAMILY_AUTO: socket.AF_UNSPEC,
    IP_FAMILY_IPV6: socket.AF_INET6,
}


def get_configured_ip_family(entry: ConfigEntry | None) -> str:
    """Return the configured address-family mode, defaulting to the safe value."""
    if entry is None:
        return DEFAULT_IP_FAMILY
    mode = entry.options.get(CONF_IP_FAMILY, DEFAULT_IP_FAMILY)
    if mode not in IP_FAMILY_TO_SOCKET:
        return DEFAULT_IP_FAMILY
    return mode


def get_configured_update_interval(entry: ConfigEntry) -> int:
    """Return the refresh interval in seconds."""
    legacy_settings = entry.data.get(CONF_SETTINGS, {}) or {}
    return int(
        entry.options.get(
            CONF_UPDATE_INTERVAL,
            legacy_settings.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
    )


def get_configured_history_days(entry: ConfigEntry) -> int:
    """Return how many days of billing history to request per 户号."""
    legacy_settings = entry.data.get(CONF_SETTINGS, {}) or {}
    return int(
        entry.options.get(
            CONF_HISTORY_DAYS,
            legacy_settings.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS),
        )
    )


def _socket_family(ip_family: str) -> int:
    """Map an IP-family mode to a socket family."""
    return IP_FAMILY_TO_SOCKET.get(ip_family, IP_FAMILY_TO_SOCKET[DEFAULT_IP_FAMILY])


def async_get_zswater_clientsession(
    hass: HomeAssistant, entry: ConfigEntry | None = None
) -> aiohttp.ClientSession:
    """Return the HA-managed session bound to the configured address family.

    Some Chinese ISP networks resolve the portal to an IPv6 address that is not
    actually routable, which shows up as a connect timeout rather than an error,
    so the family is a user-visible option instead of a hard-coded choice.
    """
    return async_get_clientsession(
        hass, family=_socket_family(get_configured_ip_family(entry))
    )


def async_get_zswater_clientsession_for_family(
    hass: HomeAssistant, ip_family: str
) -> aiohttp.ClientSession:
    """Return the HA-managed session for an explicit address-family mode."""
    return async_get_clientsession(hass, family=_socket_family(ip_family))
