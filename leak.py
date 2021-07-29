from typing import List, Dict, Optional, Union

import asyncio
import logger
import pyopensprinkler
import aiogram

import station_flow


class Detector:
    def __init__(
        self,
        logger_instance: logger.Logger,
        controller: pyopensprinkler.Controller,
        config: Dict,
    ):
        self._logger = logger_instance
        self._controller = controller
        self._config = config
        self._station_averages = None
        self._station_flow_monitor = None
        self._telegram_bot = self._create_telegram_bot(self._config)

    async def start(self) -> None:

        # initialize averages now
        await self._update_station_averages()

        # periodically update averages so
        asyncio.create_task(self._periodically_update_station_averages())

        await self._monitor_running_station()

    async def _update_station_averages(self):

        # start by getting the averages immediately so that we can monitor any running stations
        logs = await self._controller.get_logs(
            self._config["detector"]["averages_history_days"]
        )

        # get average uses across stations
        self._station_averages = self._get_station_averages(logs)

        self._logger.debug_with(
            "Updated averages", station_averages=self._station_averages
        )

    async def _periodically_update_station_averages(self):

        while True:

            # wait (in seconds)
            await asyncio.sleep(self._config["detector"]["averages_update_interval_hours"] * 60 * 60)
            
            # do the update
            await self._update_station_averages()

    def _get_running_station(
        self,
        controller: pyopensprinkler.Controller,
    ) -> Optional[pyopensprinkler.Station]:
        for station in controller.stations.values():
            if station.is_running and not station.is_master:
                return station

        return None

    async def _monitor_running_station(self) -> None:
        while True:

            # read all program/station data
            await self._controller.refresh()

            # get the flow monitor for the specific running station
            self._station_flow_monitor = self._get_station_flow_monitor(
                self._get_running_station(self._controller)
            )

            if self._station_flow_monitor is not None:
                ticks_per_minute = (
                    self._controller.flow_rate
                    / self._config["controller"]["liters_per_tick"]
                )

                await self._station_flow_monitor.add_measurement(ticks_per_minute)

            await asyncio.sleep(
                self._config["detector"]["running_station_interval_seconds"]
            )

    def _get_station_averages(self, logs: List) -> Dict:
        station_averages = {}

        # iterate over logs and group the measurements into (program_id, station_id)
        # averaging them along the way
        for log in logs:

            # get items from log record
            (
                _,
                station_index,
                _,
                _,
                flow_sensor_ticks_per_minute,
            ) = log

            # get program/station average by program/station ids
            station_average = station_averages.setdefault(
                self._get_station_key(self._controller.stations[station_index]),
                {"average_flow_sensor_ticks_per_minute": 0.0, "num_measurements": 0},
            )

            # update the moving average
            station_average["average_flow_sensor_ticks_per_minute"] = (
                (
                    station_average["average_flow_sensor_ticks_per_minute"]
                    * station_average["num_measurements"]
                )
                + flow_sensor_ticks_per_minute
            ) / (station_average["num_measurements"] + 1)

            # add to number of measurements
            station_average["num_measurements"] += 1

        return station_averages

    def _get_station_flow_monitor(
        self, station: Optional[pyopensprinkler.Station]
    ) -> Optional[station_flow.Monitor]:

        # if there's not running station, return no monitor
        if station is None:
            return None

        # if we're already monitoring this station, return the previously created monitor
        if (
            self._station_flow_monitor is not None
            and self._station_flow_monitor.station.index == station.index
        ):
            return self._station_flow_monitor

        station_key = self._get_station_key(station)

        # create a monitor
        self._station_flow_monitor = station_flow.Monitor(
            self._logger,
            station,
            int(
                self._get_station_config_field_or_default(
                    station_key, "num_inrush_measurements"
                )
            ),
            self._get_station_config_field_or_default(
                station_key, "allowed_flow_rate_max"
            ),
            self._get_station_config_field_or_default(
                station_key, "allowed_flow_rate_diff_from_average"
            ),
            float(
                self._station_averages[station_key][
                    "average_flow_sensor_ticks_per_minute"
                ]
            ),
            int(
                self._get_station_config_field_or_default(
                    station_key, "flow_rate_average_history_meansurements"
                )
            ),
            self._on_station_flow_monitor_event,
        )

        return self._station_flow_monitor

    def _get_station_config_field_or_default(
        self, station_key: str, field_name: str
    ) -> Union[float, int]:
        default_station_config = self._config["detector"]["stations"].get("default")
        station_config = (
            self._config["detector"]["stations"].get(station_key)
            or default_station_config
        )

        if station_config.get(field_name) is None:
            return default_station_config[field_name]

        return station_config[field_name]

    def _get_station_key(self, station) -> str:
        return station.name.lower().replace(" ", "_")

    def _create_telegram_bot(self, config: Dict) -> Optional[aiogram.Bot]:
        if "telegram" in config:
            self._logger.debug("Creating Telegram bot")
            return aiogram.Bot(config["telegram"]["token"])

        return None

    async def _on_station_flow_monitor_event(self, event: object) -> None:

        # if there's a telegram bot configured, sent the message
        if self._telegram_bot is not None:
            self._logger.debug_with("Sending message to Telegram", msg=str(event))
            await self._telegram_bot.send_message(
                chat_id=self._config["telegram"]["chat_id"], text=str(event)
            )
