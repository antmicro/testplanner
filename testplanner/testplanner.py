#!/usr/bin/env python3
# Copyright (c) 2019-2024 lowRISC <lowrisc.org>
# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0
r"""Command-line tool to parse and process testplan Hjson

"""
import yaml
import argparse
import logging
import os
import sys
from pathlib import Path
from shutil import copy2

from testplanner.Testplan import Testplan

STYLES_DIR = Path(Path(__file__).parent.resolve() / "template")


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
    """
    Supported calls:
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
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
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
        help="Path to the map with test links",
        type=Path,
    )
    parser.add_argument(
        "--source-url-prefix",
        help="Prefix for URLs to sources in generated files",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug prints.")

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
    output_sim_results = args.output_sim_results.resolve() if args.output_sim_results else None
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

    source_file_map = None
    if args.testplan_file_map:
        with args.testplan_file_map.open() as file_map_fd:
            source_file_map = yaml.safe_load(file_map_fd)

    repo_root = args.project_root if args.project_root else None

    source_url_prefix = args.source_url_prefix if args.source_url_prefix else ""

    diagram_paths = {}
    if args.diagram_paths:
        for mapping in args.diagram_paths:
            key, path = mapping.split("=")
            diagram_paths[key] = path
        logging.debug(f"diagram_paths = {diagram_paths.items()}")

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
            source_file_map=source_file_map,
            source_url_prefix=source_url_prefix,
        )

        output_sim_path = None

        if output_sim_results:
            sim_result = sim_results[id]
            output_sim_path = output_sim_results if output_sim_results_single else Path(output_sim_results) / f"{testplan_stem}.{format}"
            with open(output_sim_path, "a" if output_sim_results_single else "w") as f:
                f.write(testplan_obj.get_sim_results(sim_result, fmt=format))
                f.write('\n')
            copy2(STYLES_DIR / "main.css", output_sim_path.parent)
            copy2(STYLES_DIR / "cov.css", output_sim_path.parent)

        if output_testplan:
            output_path = output_testplan if output_testplan_single else Path(output_testplan) / f"{testplan_stem}.{format}"
            with open(output_path, "a" if output_testplan_single else "w") as f:
                testplan_obj.write_testplan_doc(f, output_sim_path)
                f.write("\n")

    return 0


if __name__ == "__main__":
    main(sys.argv[1:])
