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
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from importlib.resources import path as ir_path
from pathlib import Path
from shutil import copy2, copytree

import yaml
from jinja2 import Template
from tabulate import tabulate

import testplanner.template as html_templates
from testplanner.Comments import Comments
from testplanner.Testplan import (
    COMPLETE_TESTPLAN_HEADER,
    SUMMARY_TOKEN,
    Testplan,
    get_percentage,
    get_percentage_color,
    parse_repo_data,
)

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

    def none_or_str(s):
        if s in ("None", "none"):
            return None
        return s

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
        help="Path to output directory for multiple files's output, path to file for single-file output",
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
        help="Path to template XLSX file that should be used to generate spreadsheet with testplan",
        type=Path,
    )
    parser.add_argument(
        "-os",
        "--output-sim-results",
        help="Path to output directory for multiple files's output, path to file for single-file output",
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
        "--testplan-file-map-search-engine",
        help="Type of engine to use for searching files. Can be glob or regex",
        choices=["glob", "regex"],
        default="glob",
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
        "--git-url-file-prefix",
        help="Prefix for source URLs to file URLs in the git host",
        type=none_or_str,
        default="",
    )
    parser.add_argument(
        "--git-url-branch-prefix",
        help="Prefix for source URLs to branch URLs in the git host",
        type=none_or_str,
        default="/tree",
    )
    parser.add_argument(
        "--git-url-commit-prefix",
        help="Prefix for source URLs to commit URLs in the git host",
        type=none_or_str,
        default="/commit",
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
        "-t",
        "--testpoint-summary",
        help="Path to output HTML/Markdown file containing a list of all testpoints",
        type=Path,
    )
    parser.add_argument(
        "--testpoint-summary-title",
        help="Title of the testpoint list",
        default="List of testpoints",
        type=str,
    )
    parser.add_argument(
        "--repository-name",
        help="Display name for the processed repository",
        type=str,
    )
    parser.add_argument(
        "--allow-test-level-metadata",
        help="Allows defining metadata (such as owner or status) at test level",
        action="store_true",
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

    git_file_prefix = args.git_url_file_prefix
    git_branch_prefix = args.git_url_branch_prefix
    git_commit_prefix = args.git_url_commit_prefix

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
                "Incorrect number of arguments. Lengths of testplans and sim_results should be equal."
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
    tests_all = []

    comments = None
    if args.comments_file and Path(args.comments_file).exists():
        comments = Comments(args.comments_file, args.allow_test_level_metadata)

    if args.testplan_spreadsheet:
        from shutil import copyfile

        from testplanner.xls import XLSX_writer

        template_path = Path(__file__).parent / "testplan-tpl.xlsx"
        if args.testplan_spreadsheet_template:
            template_path = args.testplan_spreadsheet_template

        copyfile(template_path, args.testplan_spreadsheet)
        xls = XLSX_writer(args.testplan_spreadsheet)

    stages_progress = None

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
            git_file_prefix=git_file_prefix,
            git_branch_prefix=git_branch_prefix,
            git_commit_prefix=git_commit_prefix,
            docs_url_prefix=docs_url_prefix,
            comments=comments,
            resource_search_engine=args.testplan_file_map_search_engine,
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

        relative_url = None
        if output_sim_results:
            try:
                with open(
                    output_sim_path, "a" if output_sim_results_single else "w"
                ) as f:
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
                copytree(
                    ASSETS_DIR, output_sim_path.parent / "assets", dirs_exist_ok=True
                )
            except RuntimeError as ex:
                print(ex)
                return 1

        if args.output_summary:
            tests_summary.append(
                testplan_obj.get_testplan_summary(
                    args.output_summary,
                    sim_result,
                    output_sim_path,
                    html_links=args.output_summary.suffix == ".html",
                )
            )
            stages_progress = testplan_obj.update_stages_progress(
                sim_result, stages_progress
            )
        if args.testpoint_summary:
            tests_all.append(
                (
                    testplan_obj.result_data_store,
                    testplan_obj.stage_text_to_stage,
                    testplan_obj.get_testplan_name_with_url(
                        args.output_summary,
                        output_sim_path,
                        html_links=args.output_summary.suffix == ".html",
                    ),
                )
            )

        if output_sim_results and args.testplan_spreadsheet:
            testplan_obj.generate_xls_sim_results(xls)

    summary_all_tests_link_flag = False
    if len(tests_all) > 0:
        summary_all_tests_link_flag = True

        def process_cumulative_data(all_the_data: list) -> list:
            data = deepcopy(all_the_data)
            # stage -> stage+comment -> testpoints/tests
            dict_data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
            name_to_url = {}
            for (header, tp, name), stage_text_to_stage, link in data:
                curr_stage = ""
                for record in tp:
                    if not curr_stage:
                        curr_stage = record[0]
                    if record[0]:
                        curr_stage = record[0]
                    newrecord = []
                    for hname in COMPLETE_TESTPLAN_HEADER:
                        if hname not in header:
                            newrecord.append("")
                        else:
                            newrecord.append(record[header.index(hname)])
                    dict_data[stage_text_to_stage[curr_stage]][curr_stage][name].append(
                        newrecord
                    )
                    name_to_url[name] = link
            data = []
            for stage_name in sorted(list(dict_data.keys())):
                stage_passing = 0
                stage_total = 0
                for stage_comment in sorted(list(dict_data[stage_name].keys())):
                    stage_first = True
                    for testplan_name in sorted(
                        list(dict_data[stage_name][stage_comment].keys())
                    ):
                        testplan_first = True
                        for entry in dict_data[stage_name][stage_comment][
                            testplan_name
                        ]:
                            if SUMMARY_TOKEN in entry[2]:
                                continue
                            data.append(
                                [
                                    stage_comment if stage_first else "",
                                    name_to_url[testplan_name]
                                    if testplan_first
                                    else "",
                                ]
                                + entry[1:]
                            )
                            stage_passing += entry[5]
                            stage_total += entry[6]
                            stage_first = False
                            testplan_first = False
                total_str = f"<b>{SUMMARY_TOKEN} for {stage_name}</b>"
                if args.output_summary.suffix == ".md":
                    total_str = f"**{SUMMARY_TOKEN} for {stage_name}**"
                data.append(
                    [
                        "",
                        "",
                        "",
                        total_str,
                        "",
                        "",
                        stage_passing,
                        stage_total,
                        get_percentage(stage_passing, stage_total),
                    ]
                )
            return data

        data = {
            "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "title": args.testpoint_summary_title,
            "test_results_table": tabulate(
                process_cumulative_data(tests_all),
                headers=COMPLETE_TESTPLAN_HEADER[:1]
                + ["original_testplan"]
                + COMPLETE_TESTPLAN_HEADER[1:],
                tablefmt="unsafehtml",
            ),
            "summary_url": os.path.join(
                os.path.relpath(
                    args.output_summary.parent, start=args.testpoint_summary.parent
                ),
                args.output_summary.name,
            ),
        }
        if args.project_root:
            data["git_repo"], data["git_branch"], data["git_sha"] = parse_repo_data(
                args.repository_name,
                args.project_root,
                source_url_prefix,
                git_branch_prefix,
                git_commit_prefix,
            )
        with ir_path(
            html_templates, "testplan_simulations.html"
        ) as resourcetemplatefile:
            with open(resourcetemplatefile, "r") as f:
                resourcetemplate = f.read()
        tm = Template(resourcetemplate)
        content = tm.render(data)
        with open(args.testpoint_summary, "w") as f:
            f.write(content)

    if args.output_summary:
        header = [
            "Name",
            "Implemented tests",
            "Planned tests",
            "Implementation progress",
            "Passing runs",
            "Total runs",
            "Pass Rate",
        ]
        colalign = ["center"] + ["right"] * (len(header) - 1)
        if args.output_summary.suffix == ".html":
            sum_title = f"<h3> {args.output_summary_title}\n </h3>\n"
            summary = ""
            # for now comments will only work in HTML
            if comments:
                summary += comments.comment_summary()
            tablefmt = "unsafehtml"
            if summary_all_tests_link_flag:
                summary += f"""
                    <p class="comment">
                        <a href="{
                    os.path.join(
                        os.path.relpath(
                            args.testpoint_summary.parent,
                            start=args.output_summary.parent,
                        ),
                        args.testpoint_summary.name,
                    )
                }
                        "> View all tests </a>
                    </p>
                """
        else:
            summary = f"# {args.output_summary_title}\n\n"
            tablefmt = "pipe"
        summary += tabulate(
            tests_summary, headers=header, tablefmt=tablefmt, colalign=colalign
        )
        summary += "\n\n"

        header_stages = [
            "Stage",
            "Implemented tests",
            "Planned tests",
            "Implementation progress",
            "Passing runs",
            "Total runs",
            "Pass Rate",
        ]

        colalign = ["center"] + (len(header_stages) - 1) * ["right"]

        stages_summary = ""
        if args.output_summary.suffix == ".html":
            stages_summary += "<h3>Progress of stages</h3>\n"
            tablefmt = "unsafehtml"
        else:
            stages_summary += "## Progress of stages\n\n"
            tablefmt = "pipe"
        stages_summary += "\n\n"
        stages_table = []
        for stage in sorted(stages_progress.keys()):
            results = stages_progress[stage]
            impl_progress = get_percentage(results["written"], results["total"])
            pass_rate = get_percentage(results["passing_runs"], results["total_runs"])
            imp_prog_color = get_percentage_color(results["written"], results["total"])
            pass_rate_color = get_percentage_color(
                results["passing_runs"], results["total_runs"]
            )
            stages_table.append(
                [
                    stage,
                    results["written"],
                    results["total"],
                    f'<span style="color: {imp_prog_color}">{impl_progress}</span>',
                    results["passing_runs"],
                    results["total_runs"],
                    f'<span style="color: {pass_rate_color}">{pass_rate}</span>',
                ]
            )
        stages_summary += tabulate(
            stages_table, headers=header_stages, tablefmt=tablefmt, colalign=colalign
        )
        stages_summary += "\n\n"
        with args.output_summary.open("w") as f:
            if args.output_summary.suffix == ".html":
                data = {
                    "title": sum_title,
                    "test_results_table": summary,
                    "progress_table": stages_summary,
                    "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M"),
                }
                if args.project_root:
                    data["git_repo"], data["git_branch"], data["git_sha"] = (
                        parse_repo_data(
                            args.repository_name,
                            args.project_root,
                            source_url_prefix,
                            git_branch_prefix,
                            git_commit_prefix,
                        )
                    )
                f.write(Testplan.render_template(data))
            else:
                f.write(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
