from typing import List, Dict, Optional
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot
import matplotlib.backends.backend_pdf
import datetime
import asyncio
import sendgrid
import sendgrid.helpers.mail
import base64

import pyopensprinkler


class Emailer:
    def __init__(self, from_email: str, api_key: str):
        self._from_email = from_email
        self._email_client = sendgrid.SendGridAPIClient(api_key)

    async def send_report(
        self,
        report_path: str,
        to_email: str,
        subject: Optional[str] = None,
        contents: Optional[str] = None,
    ) -> None:

        # client is blocking, so wrap it in a non blocking call
        await asyncio.get_running_loop().run_in_executor(
            None, self._send_report, report_path, to_email, subject, contents
        )

    def _send_report(
        self,
        report_path: str,
        to_email: str,
        subject: Optional[str] = None,
        contents: Optional[str] = None,
    ) -> None:
        today = str(datetime.date.today())

        message = sendgrid.helpers.mail.Mail(
            from_email=self._from_email,
            to_emails=to_email,
            subject=subject or f"OpenSprinkler Report for {today}",
            html_content=contents or "See attached OpenSprinkler report <3",
        )

        with open(report_path, "rb") as report_file:
            report_contents = report_file.read()

        encoded_file = base64.b64encode(report_contents).decode()

        attachedFile = sendgrid.helpers.mail.Attachment(
            sendgrid.helpers.mail.FileContent(encoded_file),
            sendgrid.helpers.mail.FileName(f"os-report-{today}.pdf"),
            sendgrid.helpers.mail.FileType("application/pdf"),
            sendgrid.helpers.mail.Disposition("attachment"),
        )

        message.attachment = attachedFile
        response = self._email_client.send(message)


class Generator:
    def __init__(self, controller: pyopensprinkler.Controller):
        self._controller = controller

        # use non-interactive matplot backend so that it doens't try to pop up
        # gui and explode if not running in the main thread
        matplotlib.use("Agg")

    async def generate(self, days: int, output_path: str) -> str:
        await self._controller.refresh()

        # get logs from controller
        logs = await self._controller.get_logs(days)

        # create a dataframe from the logs
        logs_df = self._get_logs_dataframe(self._controller.stations, logs)

        # generate weekly totals, needed both for plotting and creating a textual
        # report
        weekly_total_df = self._get_weekly_total_dataframe(logs_df, "liters")

        # generate the pdf in a thread as to not block the event loop
        await asyncio.get_running_loop().run_in_executor(
            None, self._generate_pdf, output_path, logs_df, weekly_total_df
        )

        # generate string report about weekly totals
        return self._generate_weekly_total_description(weekly_total_df)

    def _generate_pdf(
        self, output_path: str, logs_df: pd.DataFrame, weekly_total_df: pd.DataFrame
    ) -> None:

        # create a pdf output
        pdf = matplotlib.backends.backend_pdf.PdfPages(output_path)

        # plot the data
        for figure in [
            self._get_line_figure(
                self._get_weekly_total_dataframe(logs_df, "liters"),
                "Liters",
                "Weekly totals",
            ),
            self._get_line_figure(
                self._get_pivot_dataframe(logs_df, "liters_per_minute"),
                "Liters/Min",
                "Rate over Time",
            ),
            self._get_line_figure(
                self._get_pivot_dataframe(logs_df, "liters"),
                "Liters",
                "Volume over Time",
            ),
        ]:
            pdf.savefig(figure, dpi=600, bbox_inches="tight")

        # flush
        pdf.close()

    def _print_dataframe(self, df: pd.DataFrame) -> None:
        with pd.option_context(
            "display.max_rows", None, "display.max_columns", None, "display.width", 1000
        ):
            print(df)

    def _sanitize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        # replace all zeros with NaN
        columns = list(df.columns.values)
        df[columns] = df[columns].replace({0.0: np.nan})

        # drop all columns (stations) whose values are all NaN, or it borks the x axis
        return df.dropna(axis=1, how="all")

    def _get_pivot_dataframe(self, logs_df: pd.DataFrame, value: str) -> pd.DataFrame:
        # pivot on the value
        pivot_df = logs_df.pivot(
            values=value, index=["start_time"], columns=["station_name"]
        )

        # sum all values for a given day
        pivot_df = pivot_df.groupby(pivot_df.index.date).sum()

        return self._sanitize_dataframe(pivot_df)

    def _get_weekly_total_dataframe(
        self, logs_df: pd.DataFrame, value: str
    ) -> pd.DataFrame:
        # pivot on the value
        pivot_df = logs_df.pivot(
            values=value, index=["start_time"], columns=["station_name"]
        )

        pivot_df = pivot_df.groupby(pd.Grouper(freq="W-SAT")).sum()
        pivot_df["Total"] = pivot_df.sum(axis=1)

        # round everything down
        columns = list(pivot_df.columns.values)
        pivot_df[columns] = pivot_df[columns].round(decimals=2)

        return self._sanitize_dataframe(pivot_df)

    def _get_line_figure(self, df: pd.DataFrame, y_label: str, title: str) -> object:
        plot = df.interpolate(method="linear").plot.line(
            marker="o", markersize=2, rot=45
        )

        plot.set_xlabel("Date")
        plot.set_ylabel(y_label)
        plot.set_title(title)

        return plot.legend(loc="center left", bbox_to_anchor=(1, 0.5)).get_figure()

    def _get_logs_dataframe(
        self, stations: Dict[int, pyopensprinkler.Station], logs: List
    ) -> pd.DataFrame:
        filtered_logs = []

        # ignore ad hoc
        for log in logs:
            if log[0] == 99:
                continue

            filtered_logs.append(log)

        logs = filtered_logs

        logs_dataframe = pd.DataFrame(
            columns=[
                "station_name",
                "liters",
                "liters_per_minute",
                "duration_seconds",
                "start_time",
                "end_time",
            ],
            index=range(len(logs)),
        )

        # force types
        logs_dataframe = logs_dataframe.astype(
            {
                "station_name": "object",
                "liters": "float64",
                "liters_per_minute": "float64",
                "duration_seconds": "float64",
                "start_time": "datetime64",
                "end_time": "datetime64",
            }
        )

        for log_index, log in enumerate(logs):

            # skip rain delay
            if log[1] == "rd":
                continue

            station_name = stations[log[1]].name
            duration_seconds = log[2]
            start_time = datetime.datetime.fromtimestamp(log[3] - duration_seconds)
            end_time = datetime.datetime.fromtimestamp(log[3])
            flow_sensor_ticks_per_minute = log[4]

            logs_dataframe.loc[log_index] = {
                "station_name": station_name,
                "liters": 10.0 * flow_sensor_ticks_per_minute * duration_seconds / 60.0,
                "liters_per_minute": 10 * flow_sensor_ticks_per_minute,
                "duration_seconds": duration_seconds,
                "start_time": start_time,
                "end_time": end_time,
            }

        return logs_dataframe

    def _generate_weekly_total_description(self, weekly_total_df: pd.DataFrame) -> str:
        weekly_total_description = "Summary for this week:<br/>"

        # columns are station names
        for column in weekly_total_df:
            penultimate_value = weekly_total_df[column].iloc[-2]
            last_value = weekly_total_df[column].iloc[-1]

            diff_percent = (100 * last_value / penultimate_value) - 100

            # get arrow
            if abs(diff_percent) < 3:
                arrow = "-"
            elif diff_percent < 0:
                arrow = "↓"
            else:
                arrow = "↑"

            if column == "Total":
                weekly_total_description += "<br/>"

            weekly_total_description += f"{arrow} {column}: {last_value:,}L (Last week: {penultimate_value:,}L; {diff_percent:.2f}% change)<br/>"

        return weekly_total_description
