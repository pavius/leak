import pytest
from typing import List
import station_flow
import logger
import sys
import asyncio


class _Station:
    def __init__(self):
        self.name = "test"


@pytest.fixture
def events():
    return []


@pytest.fixture
def monitor(events):
    root_logger = logger.Logger(level="DEBUG")
    root_logger.set_handler("stdout", sys.stdout, logger.HumanReadableFormatter())

    async def _on_event(event):
        events.append(event)

    return station_flow.Monitor(
        root_logger,
        station=_Station(),
        inrush_measurements=6,
        allowed_max=6.0,
        allowed_average_diff=0.75,
        expected_average_value=1.8,
        expected_average_history=10,
        on_event=_on_event,
    )


class TestStationFlowMonitor:

    # verify that larger than expected values that happened in the beginning of
    # the run are ignored (inrush)
    @pytest.mark.asyncio
    async def test_inrush_ignore(self, monitor, events):
        await self._add_measurements_and_verify_alert(
            monitor,
            [8.0] * 5 + [2.0] * 10,
            [],
            events
        )

    # verify that larger than expected values that happened in the beginning of
    # the run and continue to exceed the allowed inrush raise a "max" error
    @pytest.mark.asyncio
    async def test_inrush_raise(self, monitor, events):
        await self._add_measurements_and_verify_alert(
            monitor,
            [8.0] * 10 + [2.0] * 10,
            [station_flow.MaxMeasurementExceededEvent],
            events
        )

    # verify that a mean exceeding the value raises
    @pytest.mark.asyncio
    async def test_exceed_mean(self, monitor, events):
        await self._add_measurements_and_verify_alert(
            monitor,
            [8.0] * 3 + [3.0] * 40,
            [station_flow.MeanDifferenceExceededEvent],
            events
        )

    # verify that with inrush happening for a short time and also a small burst of more
    # than expected, we're still not going to raise an alert
    @pytest.mark.asyncio
    async def test_no_alert(self, monitor, events):
        await self._add_measurements_and_verify_alert(
            monitor,
            [8.0] * 3 + [2.0] * 10 + [4.0] * 2 + [2.0] * 10,
            [],
            events
        )

    async def _add_measurements_and_verify_alert(
        self,
        monitor: station_flow.Monitor,
        measurements: List[float],
        expected_events: List[type],
        received_events: List[object]
    ) -> None:
        for meansurement in measurements:
            await monitor.add_measurement(meansurement)

        await asyncio.sleep(0.1)

        assert len(expected_events) == len(received_events)
        for received_event_idx, received_event in enumerate(received_events):
            assert isinstance(received_event, expected_events[received_event_idx])
