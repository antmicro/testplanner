#!/usr/bin/env python3
# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

"""
Converter of xunit-like XML files with test results from cocotb to HJSON.
"""

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import hjson

from testplanner.Testplan import Testplan, glob_resources


def update_avg(avg, total, nextval):
    return (avg * total + nextval) / (total + 1)


def merge_avg(avg1, total1, avg2, total2):
    return (avg1 * total1 + avg2 * total2) / (total1 + total2)


def merge_results(test_result, update):
    test_result["simulated_time"] = merge_avg(
        test_result["simulated_time"],
        test_result["total"],
        update["simulated_time"],
        update["total"],
    )
    test_result["job_runtime"] = merge_avg(
        test_result["job_runtime"],
        test_result["total"],
        update["job_runtime"],
        update["total"],
    )
    test_result["passing"] += update["passing"]
    test_result["total"] += update["total"]
    test_result["passing_logs"].extend(update["passing_logs"])
    test_result["failing_logs"].extend(update["failing_logs"])
    if "file" in update:
        if "file" not in test_result:
            test_result["file"] = str(update["file"])
        else:
            assert str(test_result["file"]) == str(update["file"]), (
                f"Source files are different - {test_result['file']} != {update['file']}"
            )
    if "lineno" in update:
        if "lineno" not in test_result:
            test_result["lineno"] = update["lineno"]
        else:
            assert test_result["lineno"] == update["lineno"]


def process_xml(input_xml, project_root_dir, ignore_dirs, all_tests):
    root = ET.parse(input_xml).getroot()
    results = defaultdict(
        lambda: {
            "passing": 0,
            "total": 0,
            "passing_logs": [],
            "failing_logs": [],
            "simulated_time": 0,
            "job_runtime": 0,
        }
    )
    for testcase in root.findall(".//testcase"):
        tname = testcase.attrib["name"]
        logging.info(f"Processing testcase: {tname}")
        if tname.startswith("test_"):
            tname = tname[5:]
        unsuccessful = len(testcase.findall("skipped")) + len(
            testcase.findall("failure")
        )
        assert unsuccessful <= 1
        results[tname]["total"] += 1
        if unsuccessful == 0:
            results[tname]["passing"] += 1
        if len(testcase.findall("skipped")) + len(testcase.findall("failure")) > 0:
            if input_xml not in results[tname]["failing_logs"]:
                results[tname]["failing_logs"].append(str(input_xml))
        else:
            if input_xml not in results[tname]["passing_logs"]:
                results[tname]["passing_logs"].append(str(input_xml))
        results[tname]["simulated_time"] = update_avg(
            results[tname]["simulated_time"],
            results[tname]["total"] - 1,
            float(testcase.attrib["sim_time_ns"]),
        )
        results[tname]["job_runtime"] = update_avg(
            results[tname]["job_runtime"],
            results[tname]["total"] - 1,
            float(testcase.attrib["time"]),
        )
        if "file" in testcase.attrib and testcase.attrib["file"]:
            tdata = testcase.attrib
            if project_root_dir.resolve() in Path(tdata["file"]).resolve().parents:
                parents = Path(tdata["file"]).relative_to(project_root_dir).parents
                ignore = False
                for idir in ignore_dirs:
                    if idir in parents:
                        ignore = True
                        break
                if not ignore:
                    results[tname]["file"] = str(
                        Path(tdata["file"]).relative_to(project_root_dir)
                    )
                    results[tname]["lineno"] = tdata["lineno"]
            else:
                logging.warning(
                    f'Path in XML test "{tdata["file"]}" is outside "{project_root_dir.resolve()}" (happened in {input_xml})'
                )
        all_tests.add((tname, str(input_xml)))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input-xmls-dir",
        help="Paths to directory with cocotb XMLs",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "-t",
        "--input-testplans",
        help="Paths to HJSON testplan files",
        nargs="+",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Output directory for per-testplan HJSONs",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--project-root-dir",
        help="Base path for the project",
        default=Path("."),
        type=Path,
    )
    parser.add_argument(
        "--xml-root-dir",
        help="Root directory used in XML results in 'file' fields",
        type=Path,
    )
    parser.add_argument(
        "--tests-ignore-dirs",
        help="Directories to ignore when searching for sources, relative to --xml-root-dir",
        nargs="+",
        type=Path,
    )
    parser.add_argument(
        "--testplans-base-dir",
        help="Base path for testplans",
        default=Path("."),
        type=Path,
    )
    parser.add_argument(
        "--test-tracking-summary-dir",
        help="Directory of files with summary on test tracking",
        type=Path,
    )
    parser.add_argument(
        "--xml-url-prefix",
        help="Link XMLs with a specified prefix - relative to --tests-base-dir",
    )
    parser.add_argument(
        "--testplan-file-map",
        help="Path to the file with path and resource mappings for testplans",
        type=Path,
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug prints.",
    )

    args = parser.parse_args()

    project_root_dir = args.project_root_dir if args.project_root_dir else Path(".")
    testplan_root_dir = args.testplans_base_dir.resolve()
    xml_root_dir = args.xml_root_dir
    ignore_dirs = args.tests_ignore_dirs if args.tests_ignore_dirs else []

    level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=level)

    all_tests = set()
    used_tests = set()
    missing_results = set()

    xml_results_cache = dict()

    for testplanpath in args.input_testplans:
        testplanpath = testplanpath.resolve()
        testplan = Testplan(
            testplanpath,
            repo_top=project_root_dir,
            resource_map_data=args.testplan_file_map,
        )
        results = []
        for testpoint in testplan.testpoints:
            for test in testpoint.tests:

                def find_resource(resource_name, resource_dir):
                    resource_glob = testplan.resource_map.get(
                        resource_name,
                        testplan.filename,
                        testplan.name,
                        testpoint.name,
                        test,
                    )
                    if resource_glob is None:
                        return []
                    results_paths = glob_resources(
                        resource_dir,
                        resource_glob,
                        "regex",
                    )
                    return results_paths

                # skip empty entities
                if not test:
                    continue
                cocotb_xml = find_resource("cocotb_xml", args.input_xmls_dir)
                test_impl = None
                if not cocotb_xml:
                    source = find_resource("source", args.project_root_dir)
                    if len(source):
                        assert len(source) > 0, (
                            "There should be only one relevant source"
                        )
                        source = source[0]
                        test_impl = source
                        template = Path(source).relative_to(args.project_root_dir)
                        template = template.parent / f"{template.stem}"
                        template = str(template) + r".*\.xml"
                        cocotb_xml = glob_resources(
                            args.input_xmls_dir, template, "regex"
                        )
                if not cocotb_xml:
                    logging.warning(
                        f"No XML results for {testplan.filename=} {testpoint.name=} {test=}"
                    )
                    missing_results.add((str(testplan.filename), testpoint.name, test))
                    continue
                test_result = None
                for xmlpath in cocotb_xml:
                    processed_tests = None
                    if str(xmlpath) in xml_results_cache:
                        processed_tests = xml_results_cache[str(xmlpath)]
                    else:
                        processed_tests = process_xml(
                            xmlpath, xml_root_dir, ignore_dirs, all_tests
                        )
                        xml_results_cache[str(xmlpath)] = processed_tests
                    if test not in processed_tests:
                        logging.error(
                            f"No test {testplan.filename=} {testpoint.name=} {test=} found in XML {xmlpath}"
                        )
                        continue
                    tdata = processed_tests[test]
                    if test_result is None:
                        test_result = {
                            "name": test,
                            "passing": tdata["passing"],
                            "total": tdata["total"],
                            "passing_logs": tdata["passing_logs"],
                            "failing_logs": tdata["failing_logs"],
                            "simulated_time": tdata["simulated_time"],
                            "job_runtime": tdata["job_runtime"],
                        }
                        if "file" in tdata:
                            test_result["file"] = tdata["file"]
                        elif test_impl:
                            test_result["file"] = test_impl
                    else:
                        merge_results(test_result, tdata)
                    used_tests.add((test, str(xmlpath)))
                if test_result is not None:
                    results.append(test_result)
                else:
                    missing_results.add((str(testplan.filename), testpoint.name, test))
        out_hjson = {
            "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "test_results": results,
        }
        out_path = args.output_dir / testplanpath.relative_to(testplan_root_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f"Writing test results to: {out_path}")
        with out_path.open("w") as f:
            hjson.dump(out_hjson, f)

        if args.test_tracking_summary_dir:
            args.test_tracking_summary_dir.mkdir(parents=True, exist_ok=True)

            unmapped_tests = list(all_tests - used_tests)

            used_logs = sorted(list(set([q[1] for q in used_tests])))

            if len(unmapped_tests) > 0:
                print("There are unmapped tests")
            for test in unmapped_tests:
                print(test)

            with (args.test_tracking_summary_dir / "unmapped-tests.json").open(
                "w"
            ) as f:
                json.dump(
                    {
                        "used": sorted(list(used_tests)),
                        "unused": sorted(list(unmapped_tests)),
                        "missing_results": sorted(list(missing_results)),
                    },
                    f,
                    indent=4,
                )
            with (args.test_tracking_summary_dir / "used-logs.json").open("w") as f:
                json.dump(used_logs, f, indent=4)
    return 0


if __name__ == "__main__":
    main(sys.exit(main()))
