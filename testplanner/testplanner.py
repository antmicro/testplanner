#!/usr/bin/env python3
# Copyright (c) 2019-2024 lowRISC <lowrisc.org>
# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0
r"""Command-line tool to parse and process testplan Hjson"""

import argparse
import logging
import os
import sys
from pathlib import Path
from shutil import copy2, copytree

import yaml
from tabulate import tabulate

from testplanner.Testplan import Testplan, parse_repo_data

STYLES_DIR = Path(Path(__file__).parent.resolve() / "template")
ASSETS_DIR = Path(Path(__file__).parent.resolve() / "template/assets")


def prepare_output_paths(output_path):
    if output_path is None:
        return False
    output_path_single = False
    if output_path and output_path.suffix in [".md", ".html"]:
        output_path_single = True
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
    else:
        output_path.mkdir(parents=True, exist_ok=True)
    return output_path_single


def main():
    """Supported calls:
    * Pass a list of testplans (at least 1) without simulation results:
        testplanner.py <testplan_0> ... <testplan_N>
                       -o <output_dir>

      Expected output:
      In the output directory, for each testplan HJSON file,
      there will be a corresponding Markdown file.

    * Pass an array of testplans with simulation results:
        * number of testplans must be the same as sim_results
        * mapping : testplan-sim_result will be done by list order
        testplanner.py <testplan_0> ... <testplan_N>
                       -s <sim_results_0> ... <sim_results_N>
                       -o <output_dir>

      Expected output:
      In the output directory, for each testplan HJSON file,
      there will be an HTML file, which consolidates testplans
      with the simulation results.

    You should always set the <output_dir> explicitly.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "testplans",
        metavar="<testplan-file>",
        nargs="+",
        help="input HJSON testplan files",
    )
    parser.add_argument(
        "-s",
        "--sim-results",
        metavar="<sim-results-file>",
        nargs="*",
        help="input HJSON simulation results file",
    )
    parser.add_argument(
        "-d",
        "--diagram-paths",
        metavar="testplan_file=diagram_path",
        nargs="*",
        help="input UVM testbench image file",
    )
    parser.add_argument(
        "-ot",
        "--output-testplan",
        help="Path to output directory for multiple files's output, path to file for single-file output",  # noqa: E501
        type=Path,
        required=not any([flag in sys.argv for flag in ["--sim-results", "-s"]]),
    )
    parser.add_argument(
        "--testplan-spreadsheet",
        help="Generate testplan document as an XLSX file based on included template",
        type=Path,
    )
    parser.add_argument(
        "--testplan-spreadsheet-template",
        help="Path to template XLSX file that should be used to generate spreadsheet with testplan",  # noqa: E501
        type=Path,
    )
    parser.add_argument(
        "-os",
        "--output-sim-results",
        help="Path to output directory for multiple files's output, path to file for single-file output",  # noqa: E501
        type=Path,
        required=any([flag in sys.argv for flag in ["--sim-results", "-s"]]),
    )
    parser.add_argument(
        "--sim-results-format",
        help="Format of the output, can be 'html' or 'md'",
        choices=["html", "md"],
    )
    parser.add_argument(
        "--project-root",
        help="Path to the project's root directory",
        type=Path,
    )
    parser.add_argument(
        "--testplan-file-map",
        help="Path to the file with path and resource mappings for testplans",
        type=Path,
    )
    parser.add_argument(
        "--comments-file",
        help="Path to the file with external comments to be added to testplans",
        type=Path,
    )
    parser.add_argument(
        "--source-url-prefix",
        help="Prefix for URLs to sources in generated files",
    )
    parser.add_argument(
        "--docs-url-prefix",
        help="Prefix for URLs to documentation in generated files",
    )
    parser.add_argument(
        "-osum",
        "--output-summary",
        help="Path to output HTML/Markdown file containing summary of executed tests",
        type=Path,
    )
    parser.add_argument(
        "--output-summary-title",
        help="Title of the output summary",
        default="Tests' summary",
        type=str,
    )
    parser.add_argument(
        "--output-sim-results-prefix",
        help="Prefix for tests' results to be used in testplan Markdown files",
        type=str,
    )
    parser.add_argument(
        "--repository-name",
        help="Display name for the processed repository",
        type=str,
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug prints."
    )

    args = parser.parse_args()

    format = "html" if args.sim_results else "md"
    if args.sim_results_format and args.sim_results:
        format = args.sim_results_format

    # Basic logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level)

    # Process args
    logging.debug("Args:")
    output_testplan = args.output_testplan.resolve() if args.output_testplan else None
    output_testplan_single = prepare_output_paths(output_testplan)
    output_sim_results = (
        args.output_sim_results.resolve() if args.output_sim_results else None
    )
    output_sim_results_single = prepare_output_paths(output_sim_results)

    testplans = [Path(os.path.abspath(s)) for s in args.testplans]
    logging.debug(f"testplans = {testplans}")

    if args.sim_results:
        sim_results = [Path(os.path.abspath(s)) for s in args.sim_results]
        if len(sim_results) != len(testplans):
            raise ValueError(
                "Incorrect number of arguments. Lengths of testplans and sim_results should be equal."  # noqa: E501
            )
        logging.debug(f"sim_results = {sim_results}")
    else:
        sim_results = None

    resource_map_data = None
    if args.testplan_file_map:
        with args.testplan_file_map.open() as file_map_fd:
            resource_map_data = yaml.safe_load(file_map_fd)

    repo_root = args.project_root if args.project_root else None

    source_url_prefix = args.source_url_prefix if args.source_url_prefix else ""
    docs_url_prefix = args.docs_url_prefix if args.docs_url_prefix else ""

    diagram_paths = {}
    if args.diagram_paths:
        for mapping in args.diagram_paths:
            key, path = mapping.split("=")
            diagram_paths[key] = path
        logging.debug(f"diagram_paths = {diagram_paths.items()}")

    tests_summary = []

    if args.testplan_spreadsheet:
        from shutil import copyfile

        from testplanner.xls import XLSX_writer

        template_path = Path(__file__).parent / "testplan-tpl.xlsx"
        if args.testplan_spreadsheet_template:
            template_path = args.testplan_spreadsheet_template

        copyfile(template_path, args.testplan_spreadsheet)
        xls = XLSX_writer(args.testplan_spreadsheet)

    # Process testplans
    for id, testplan in enumerate(testplans):
        logging.debug("Processing:")
        testplan_name = Path(testplan).name
        logging.debug(f"testplan_name = {testplan_name}")

        testplan_stem = Path(testplan).stem
        logging.debug(f"testplan_stem = {testplan_stem}")

        diagram_path = None
        if testplan_name in diagram_paths:
            diagram_path = diagram_paths[testplan_name]

        # Create the testplan object
        testplan_obj = Testplan(
            testplan,
            diagram_path=diagram_path,
            repo_top=repo_root,
            resource_map_data=resource_map_data,
            source_url_prefix=source_url_prefix,
            docs_url_prefix=docs_url_prefix,
            comments_file=args.comments_file,
        )

        sim_result = None
        output_sim_path = None

        if output_sim_results:
            sim_result = sim_results[id]
            output_sim_path = (
                output_sim_results
                if output_sim_results_single
                else Path(output_sim_results) / f"{testplan_stem}.{format}"
            )

        if output_testplan:
            if args.testplan_spreadsheet:
                testplan_obj.create_testplan_worksheet(xls)
            output_path = (
                output_testplan
                if output_testplan_single
                else Path(output_testplan) / f"{testplan_stem}.md"
            )
            with open(output_path, "a" if output_testplan_single else "w") as f:
                testplan_obj.write_testplan_doc(
                    f,
                    sim_result,
                    output_sim_path,
                    args.output_sim_results_prefix,
                )
                f.write("\n")

        if output_sim_results:
            with open(output_sim_path, "a" if output_sim_results_single else "w") as f:
                relative_url = None
                if args.output_summary:
                    relative_url = os.path.join(
                        os.path.relpath(
                            args.output_summary.parent, start=output_sim_path.parent
                        ),
                        args.output_summary.name,
                    )
                    f.write(
                        testplan_obj.get_sim_results(
                            sim_result,
                            relative_url,
                            repo_root,
                            args.repository_name,
                            fmt=format,
                        )
                    )
                    f.write("\n")
            copy2(STYLES_DIR / "main.css", output_sim_path.parent)
            copy2(STYLES_DIR / "cov.css", output_sim_path.parent)
            copytree(ASSETS_DIR, output_sim_path.parent / "assets", dirs_exist_ok=True)

        if args.output_summary:
            tests_summary.append(
                testplan_obj.get_testplan_summary(
                    args.output_summary,
                    sim_result,
                    output_sim_path,
                    html_links=args.output_summary.suffix == ".html",
                )
            )
        if output_sim_results and args.testplan_spreadsheet:
            testplan_obj.generate_xls_sim_results(xls)

    if args.output_summary:
        header = [
            "Name",
            "Passing tests",
            "Implemented tests",
            "Planned tests",
            "Implementation progress",
            "Pass Rate",
        ]
        colalign = ["center", "right", "right", "right", "right", "right"]
        if args.output_summary.suffix == ".html":
            sum_title = f"<h3> {args.output_summary_title}\n </h3>\n"
            summary = ""
            tablefmt = "unsafehtml"
        else:
            summary = f"# {args.output_summary_title}\n\n"
            tablefmt = "pipe"
        summary += tabulate(
            tests_summary, headers=header, tablefmt=tablefmt, colalign=colalign
        )
        summary += "\n"
        with args.output_summary.open("w") as f:
            if args.output_summary.suffix == ".html":
                data = {
                    "title": sum_title,
                    "test_results_table": summary,
                }
                if args.project_root:
                    data["git_repo"], data["git_branch"], data["git_sha"] = (
                        parse_repo_data(args.repository_name, args.project_root)
                    )
                f.write(Testplan.render_template(data))
            else:
                f.write(summary)

    return 0


if __name__ == "__main__":
    main(sys.argv[1:])
