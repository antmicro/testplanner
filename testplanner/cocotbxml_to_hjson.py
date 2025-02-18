import re
import sys
import hjson
import logging
import xml.etree.ElementTree as ET
from statistics import mean
import argparse
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--input-xmls",
        help="Paths to XMLs or directories with XMLs",
        nargs="+",
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
        "--tests-base-dir",
        help="Base path for tests",
        default=Path("."),
        type=Path,
    )
    parser.add_argument(
        "--tests-ignore-dirs",
        help="Directories to ignore when searching for sources, relative to --tests-base-dir",
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
        "--verbose",
        action="store_true",
        help="Enable debug prints.",
    )

    args = parser.parse_args()

    test_root_dir = args.tests_base_dir if args.tests_base_dir else Path(".")
    testplan_root_dir = args.testplans_base_dir.resolve()
    ignore_dirs = args.tests_ignore_dirs if args.tests_ignore_dirs else []

    level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=level)

    test_names_to_entries = dict()

    # TODO (glatosinski): We need to adjust passing/total and
    # simulated_time/job_runtime to what they should be

    for resultspath in args.input_xmls:
        root = ET.parse(resultspath).getroot()
        for testcase in root.findall('.//testcase'):
            tname = testcase.attrib["name"]
            if tname.startswith('test_'):
                tname = tname[5:]
            if matched := re.match(r"^(.+)_(\d+)$", tname):
                tname = matched.group(1)
            if tname in test_names_to_entries:
                logging.info(f"Test name '{tname}' reappears in test results in {resultspath}, previously in {test_names_to_entries[tname]['xmlpath'][-1]}")  # noqa: E501
                test_names_to_entries[tname]["skipped"] += len(testcase.findall("skipped"))  # noqa: E501
                test_names_to_entries[tname]["failure"] += len(testcase.findall("failure"))  # noqa: E501
                test_names_to_entries[tname]["total"] += 1
                test_names_to_entries[tname]["xmlpath"].append(resultspath)
                test_names_to_entries[tname]["simulated_time"].append(float(testcase.attrib["sim_time_ns"]))
                test_names_to_entries[tname]["job_runtime"].append(float(testcase.attrib["time"]))
            else:
                entry = testcase.attrib
                entry["skipped"] = len(testcase.findall("skipped"))
                entry["failure"] = len(testcase.findall("failure"))
                entry["total"] = 1
                entry["xmlpath"] = [resultspath]
                entry["name"] = tname
                entry["simulated_time"] = [float(testcase.attrib["sim_time_ns"])]
                entry["job_runtime"] = [float(testcase.attrib["time"])]
                test_names_to_entries[tname] = entry

    for testplanpath in args.input_testplans:
        testplanpath = testplanpath.resolve()
        tests_stats = dict()
        with open(testplanpath, 'r') as f:
            testplan = hjson.load(f)
        for testpoint in testplan["testpoints"]:
            for test in testpoint["tests"]:
                if test not in test_names_to_entries:
                    continue
                tdata = test_names_to_entries[test]
                if test in tests_stats:
                    raise RuntimeError("Multiple tests with the same name")
                tests_stats[test] = {
                    "name": test,
                    "passing": tdata["total"] - tdata["skipped"] - tdata["failure"],
                    "total": tdata["total"],
                    "simulated_time": mean(tdata["simulated_time"]),
                    "job_runtime": mean(tdata["job_runtime"]),
                }
                if "file" in tdata:
                    if test_root_dir.resolve() in Path(tdata["file"]).resolve().parents:
                        parents = Path(tdata["file"]).relative_to(test_root_dir).parents
                        ignore = False
                        for idir in ignore_dirs:
                            if idir in parents:
                                ignore = True
                                break
                        if not ignore:
                            tests_stats[test]["file"] = str(Path(tdata["file"]).relative_to(test_root_dir))
                            tests_stats[test]["lineno"] = tdata["lineno"]
                    else:
                        logging.warning(f'Path in XML test "{tdata["file"]}" is outside "{test_root_dir.resolve()}"')
        out_hjson = {
            "timestamp": datetime.now().strftime("%D/%M/%Y %H:%M"),
            "test_results": [val for val in tests_stats.values()]
        }
        out_path = args.output_dir / testplanpath.relative_to(testplan_root_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            hjson.dump(out_hjson, f)
    return 0


if __name__ == "__main__":
    main(sys.exit(main()))
