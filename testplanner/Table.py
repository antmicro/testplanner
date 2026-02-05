# Copyright (c) 2025-2026 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

r"""Utility for converting CSV tables"""

import csv
from html import escape
from importlib.resources import path
from pathlib import Path

from jinja2 import Template

import testplanner.template as html_templates


class Table:
    def __init__(
        self,
        csv_file_path: str,
    ):
        self.csv_file_path = csv_file_path

    def render_template(self, data):
        with path(html_templates, "performance_table.html") as resourcetemplatefile:
            with open(resourcetemplatefile, "r") as f:
                resourcetemplate = f.read()
        tm = Template(resourcetemplate)
        content = tm.render(data)
        return content

    def get_html(self, base_template_data):
        table_html = ""
        with open(self.csv_file_path, newline="") as csv_file:
            reader = csv.reader(csv_file)

            table_html += "<table border='1'>\n"
            for row_index, row in enumerate(reader):
                table_html += "<tr>"
                tag = "th" if row_index == 0 else "td"
                for cell in row:
                    table_html += f"<{tag}>{escape(cell)}</{tag}>"
                table_html += "</tr>\n"

            table_html += "</table>\n"
        data = base_template_data
        data["perf_results_table"] = table_html
        data["title"] = Path(self.csv_file_path).stem.replace("_", " ").title()
        return self.render_template(data)
