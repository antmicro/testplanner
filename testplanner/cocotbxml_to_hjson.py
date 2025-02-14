import sys
import hjson
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
        type=Path,
    )

    args = parser.parse_args()

    test_root_dir = args.tests_base_dir if args.tests_base_dir else Path(".")

    test_names_to_entries = dict()

    # TODO (glatosinski): We need to adjust passing/total and
    # simulated_time/job_runtime to what they should be

    for resultspath in args.input_xmls:
        root = ET.parse(resultspath).getroot()
        for testcase in root.findall('.//testcase'):
            tname = testcase.attrib["name"]
            if tname.startswith('test_'):
                tname = tname[5:]
            if tname in test_names_to_entries:
                print(f"WARNING: test name '{tname}' reappears in test results in {resultspath}, previously in {test_names_to_entries[tname]['xmlpath'][-1]}")  # noqa: E501
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
        tests_stats = dict()
        with open(testplanpath, 'r') as f:
            testplan = hjson.load(f)
        for test in testplan["testpoints"]:
            if test["name"] not in test_names_to_entries:
                continue
            tdata = test_names_to_entries[test["name"]]
            if test["name"] in tests_stats:
                raise RuntimeError("Multiple tests with the same name")
            tests_stats[test["name"]] = {
                "name": test["name"],
                "passing": tdata["total"] - tdata["skipped"] - tdata["failure"],
                "total": tdata["total"],
                "simulated_time": mean(tdata["simulated_time"]),
                "job_runtime": mean(tdata["job_runtime"]),
                "file": str(Path(tdata["file"]).relative_to(test_root_dir)),
                "lineno": tdata["lineno"],
            }
        out_hjson = {
            "timestamp": datetime.now().strftime("%D/%M/%Y %H:%M"),
            "test_results": [val for val in tests_stats.values()]
        }
        out_path = args.output_dir / testplanpath
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            hjson.dump(out_hjson, f)
    return 0


if __name__ == "__main__":
    main(sys.exit(main()))
