from logging import root
from typing import Dict

import asyncio
import uvloop
import logger
import sys
import yaml
import argparse
import pyopensprinkler
import aiocron
import signal
import functools
import traceback

import leak
import report


class Leak:
    def __init__(self, root_logger: logger.Logger, args: argparse.Namespace):
        self._logger = root_logger
        self._leak_detector = None
        self._report_generator = None

        # create logger
        self._logger.debug_with(
            "Reading configuration", config_file_path=args.config_path
        )

        with open(args.config_path, "r") as config_file:
            self._config = yaml.load(config_file, Loader=yaml.Loader)

        # create a controller
        root_logger.debug_with(
            "Creating controller", url=self._config["controller"]["url"]
        )
        self._controller = pyopensprinkler.Controller(
            self._config["controller"]["url"], self._config["controller"]["password"]
        )

    async def start(self) -> None:
        self._logger.debug("Starting")

        # do the initial refresh
        await self._controller.refresh()

        # detect leaks
        asyncio.create_task(self._detect_leaks())

        # create reports
        asyncio.create_task(self._generate_periodic_reports())

    async def stop(self) -> None:
        self._logger.debug("Stopping")
        await self._controller.session_close()

    async def _detect_leaks(self) -> None:

        self._logger.debug_with("Starting leak detection")

        # create a leak detector
        detector = leak.Detector(self._logger, self._controller, self._config)

        # start detection
        await detector.start()

    async def _generate_periodic_reports(self) -> None:
        temporary_file_name = "/tmp/os-temp.pdf"
        self._logger.debug_with(
            "Periodically creating reports", schedule=self._config["report"]["schedule"]
        )

        # create a report generator and emailer
        generator = report.Generator(self._controller)
        emailer = report.Emailer(
            self._config["sendgrid"]["from_email_address"],
            self._config["sendgrid"]["api_key"],
        )

        while True:

            # wait until next schedule
            await aiocron.crontab(self._config["report"]["schedule"]).next()

            self._logger.debug_with(
                "Sending report",
                history=self._config["report"]["generator"]["history_days"],
                to=self._config["report"]["emailer"]["to_email_address"],
            )

            # generate a report @ tmp file and create a description
            weekly_description = await generator.generate(
                self._config["report"]["generator"]["history_days"], temporary_file_name
            )

            # email the report
            await emailer.send_report(
                temporary_file_name,
                self._config["report"]["emailer"]["to_email_address"],
                contents=weekly_description,
            )


async def _shutdown(
    root_logger: logger.Logger,
    loop: asyncio.BaseEventLoop,
    leak_instance: Leak,
    shutdown_signal=None,
) -> None:
    root_logger.debug_with(
        "Shutting down",
        signal_name=shutdown_signal.name if shutdown_signal is not None else "N/A",
    )
    await leak_instance.stop()

    tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    root_logger.debug_with("Waiting for cancelled tasks", num=len(tasks))
    await asyncio.gather(*tasks, return_exceptions=True)

    loop.stop()


def _handle_exception(
    root_logger: logger.Logger,
    leak_instance: Leak,
    loop: asyncio.BaseEventLoop,
    context,
) -> None:
    msg = context.get("exception", context["message"])
    try:
        tb = str(traceback.format_tb(context["exception"].__traceback__))
    except Exception as e:
        tb = f"Could not extract traceback: {e}"

    root_logger.warn_with("Caught unhandled exception", msg=msg, tb=tb)
    asyncio.create_task(_shutdown(root_logger, loop, leak_instance))


def _register_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--config-path", required=True)

    return parser


if __name__ == "__main__":
    root_logger = logger.Logger(level="DEBUG")
    root_logger.set_handler("stdout", sys.stdout, logger.HumanReadableFormatter())

    parser = _register_arguments(argparse.ArgumentParser())
    uvloop.install()

    loop = asyncio.get_event_loop()
    leak_instance = Leak(root_logger, parser.parse_args())

    # register common signals
    shutdown_signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for shutdown_signal in shutdown_signals:
        loop.add_signal_handler(
            shutdown_signal,
            lambda shutdown_signal=shutdown_signal: asyncio.create_task(
                _shutdown(root_logger, loop, leak_instance, shutdown_signal)
            ),
        )

    # register global exception handling
    loop.set_exception_handler(
        functools.partial(_handle_exception, root_logger, leak_instance)
    )

    try:
        root_logger.debug("Running")
        loop.create_task(leak_instance.start())
        loop.run_forever()
    finally:
        root_logger.debug("Shutting down")
        loop.close()
