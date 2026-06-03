"""Data coordinator for PVHub 2.0."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PVHubClient, PVHubError, extract_sensor_data
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN


class PVHubDataUpdateCoordinator(DataUpdateCoordinator[dict[str, object]]):
    """Fetch PVHub data and fan it out to sensors."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = PVHubClient.from_config(dict(entry.data))

    async def _async_update_data(self) -> dict[str, object]:
        try:
            raw = await self.hass.async_add_executor_job(self.client.get_analysis)
        except PVHubError as exc:
            raise UpdateFailed(str(exc)) from exc

        data = extract_sensor_data(raw)
        if not data:
            raise UpdateFailed("PVHub response did not contain recognised sensor data")
        return data
