from typing import Callable, List
import asyncio
import statistics
import pyopensprinkler


class MaxMeasurementExceededEvent:
    def __init__(self, station: pyopensprinkler.Station, measurement: float, max: float):
        self.station = station
        self.measurement = measurement
        self.max = max

    def __repr__(self):
        return f"Measurement ({self.measurement}) for station {self.station.name} exceeded max ({self.max})"


class MeanDifferenceExceededEvent:
    def __init__(self, station, measurements: List[float], measured_mean: float, expected_mean: float, allowed_mean_diff: float):
        self.station = station
        self.measurements = measurements
        self.measured_mean = measured_mean
        self.expected_mean = expected_mean
        self.allowed_mean_diff = allowed_mean_diff

    def __repr__(self):
        return f"Measured mean ({self.measured_mean}, from {self.measurements}) for station {self.station.name} too far from mean ({self.expected_mean} ±{self.allowed_mean_diff})"


class Monitor:
    def __init__(
        self,
        logger_instance,
        station: pyopensprinkler.Station,
        inrush_measurements: int,
        allowed_max: float,
        allowed_average_diff: float,
        expected_average_value: float,
        expected_average_history: int,
        on_event: Callable,
    ):
        self._logger = logger_instance
        self._station = station
        self._inrush_measurements = inrush_measurements
        self._allowed_max = allowed_max
        self._allowed_average_diff = allowed_average_diff
        self._expected_average_value = expected_average_value
        self._expected_average_history = expected_average_history
        self._measurements = []
        self._num_measurements = 0
        self._on_event = on_event

        # only raise one alert per run
        self._event_raised = False

        self._logger.debug_with(
            "Created flow monitor",
            station=station.name,
            inrush_measurements=inrush_measurements,
            allowed_max=allowed_max,
            allowed_average_diff=allowed_average_diff,
            expected_average_value=expected_average_value,
            expected_average_history=expected_average_history,
        )

    async def add_measurement(self, measurement: float) -> None:
        self._logger.debug_with(
            "Adding measurement",
            name=self._station.name,
            measurement=measurement,
            num_measurements=self._num_measurements,
        )

        self._num_measurements += 1

        # ignore the initial number of measurements because inrush
        # will be much higher than average
        if self._num_measurements < self._inrush_measurements:
            self._logger.debug_with(
                "Ignoring inrush measurement",
                measurement=measurement,
                measurements_left=self._inrush_measurements - self._num_measurements,
            )
            return

        # add to measurements
        self._measurements.append(measurement)

        # check if absolute maximum passed
        if measurement > self._allowed_max:
            await self._raise_event(
                MaxMeasurementExceededEvent(
                    self._station, measurement, self._allowed_max
                )
            )

        # if there's less than expected_average_history measurements, nothing to do
        if len(self._measurements) < self._expected_average_history:
            return

        measurements_for_mean = self._measurements[-self._expected_average_history :]

        self._logger.debug_with("Calculating mean", measurements=measurements_for_mean)

        # calculate average over the expected_average_history
        measured_mean = statistics.mean(measurements_for_mean)
        mean_diff = measured_mean - self._expected_average_value

        self._logger.debug_with(
            "Calculated mean", measured_mean=measured_mean, mean_diff=mean_diff, allowed_diff=self._allowed_average_diff
        )

        if mean_diff > abs(self._allowed_average_diff):
            await self._raise_event(
                MeanDifferenceExceededEvent(
                    self._station,
                    measurements_for_mean,
                    measured_mean,
                    self._expected_average_value,
                    self._allowed_average_diff,
                )
            )

    async def _raise_event(self, event: object) -> None:
        if self._event_raised:
            return

        self._event_raised = True

        # call the event
        asyncio.create_task(self._on_event(event))

    @property
    def station(self) -> pyopensprinkler.Station:
        return self._station
