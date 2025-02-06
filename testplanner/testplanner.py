#!/usr/bin/env python3
# Copyright (c) 2019-2024 lowRISC <lowrisc.org>
# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0
r"""Command-line tool to parse and process testplan Hjson

"""
import argparse
import logging
import os
import sys
from pathlib import Path
from shutil import copy2

from testplanner.Testplan import Testplan

STYLES_DIR = Path(Path(__file__).parent.resolve() / "template")


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
        "--sim_results",
        metavar="<sim-results-file>",
        nargs="*",
        help="input HJSON simulation results file",
    )
    parser.add_argument(
        "-d",
        "--diagram_paths",
        metavar="testplan_file=diagram_path",
        nargs="*",
        help="input UVM testbench image file",
    )
    parser.add_argument("--output_dir", "-o", default=".", help="Output directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug prints.")

    args = parser.parse_args()

    # Basic logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level)

    # Process args
    logging.debug("Args:")
    output_dir = Path(os.path.abspath(args.output_dir))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    logging.debug(f"output_dir = {output_dir}")

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

    diagram_paths = {}
    if args.diagram_paths:
        for mapping in args.diagram_paths:
            key, path = mapping.split("=")
            diagram_paths[key] = path
        logging.debug(f"diagram_paths = {diagram_paths.items()}")

    # Process testplans
    for testplan in testplans:
        logging.debug("Processing:")
        testplan_name = Path(testplan).name
        logging.debug(f"testplan_name = {testplan_name}")

        testplan_stem = Path(testplan).stem
        logging.debug(f"testplan_stem = {testplan_stem}")

        diagram_path = None
        if testplan_name in diagram_paths:
            diagram_path = diagram_paths[testplan_name]

        # Create the testplan object
        testplan_obj = Testplan(testplan, diagram_path=diagram_path)

        if sim_results:
            out_name = testplan_stem + ".html"
        else:
            out_name = testplan_stem + ".md"
        output_file = Path(output_dir) / out_name
        logging.debug(f"output_file = {output_file}")

        with open(output_file, "w") as f:
            # Map testplan to sim_result by index in the list
            if sim_results:
                id = testplans.index(testplan)
                sim_result = sim_results[id]
                f.write(testplan_obj.get_sim_results(sim_result, fmt="html"))
            else:
                testplan_obj.write_testplan_doc(f)
                f.write("\n")
        copy2(STYLES_DIR / "main.css", output_dir)
        copy2(STYLES_DIR / "cov.css", output_dir)

    return 0


if __name__ == "__main__":
    main(sys.argv[1:])
