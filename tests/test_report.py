from typing import Dict
import pytest
import os
import report
import yaml

import pyopensprinkler


@pytest.fixture
def config():
    with open("etc/leak.yaml", "r") as config_file:
        return yaml.load(config_file, Loader=yaml.Loader)


@pytest.fixture
@pytest.mark.asyncio
async def controller(config):
    controller = pyopensprinkler.Controller(
        config["controller"]["url"], config["controller"]["password"]
    )
    yield controller

    await controller.session_close()


@pytest.fixture
def generator(controller):
    return report.Generator(controller)


@pytest.fixture
def emailer(config):
    return report.Emailer(
        config["sendgrid"]["from_email_address"],
        config["sendgrid"]["api_key"],
    )


class TestReportGenerator:
    @pytest.mark.asyncio
    async def test_generate(
        self,
        generator: report.Generator,
        controller: pyopensprinkler.Controller,
        config: Dict,
    ):
        await generator.generate(
            config["report"]["generator"]["history_days"], "/tmp/t1.pdf"
        )

    @pytest.mark.asyncio
    async def test_generate_and_email(
        self,
        generator: report.Generator,
        controller: pyopensprinkler.Controller,
        emailer: report.Emailer,
        config: Dict,
    ):
        temporary_pdf_path = "/tmp/t1.pdf"

        weekly_description = await generator.generate(
            config["report"]["generator"]["history_days"], temporary_pdf_path
        )

        await emailer.send_report(temporary_pdf_path, config["report"]["emailer"]["to_email_address"], contents=weekly_description)


class TestReportEmailer:
    @pytest.mark.asyncio
    async def test_send(self, emailer: report.Emailer):
        await emailer.send_report("/tmp/t1.pdf", "pavius@gmail.com")
