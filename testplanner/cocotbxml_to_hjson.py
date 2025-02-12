import sys
import hjson
import xml.etree.ElementTree as ET
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

    for resultspath in args.input_xmls:
        root = ET.parse(resultspath).getroot()
        for testcase in root.findall('.//testcase'):
            tname = testcase.attrib["name"]
            if tname.startswith('test_'):
                tname = tname[5:]
            if tname in test_names_to_entries:
                test_names_to_entries[tname]["skipped"] += len(testcase.findall("skipped"))
                test_names_to_entries[tname]["failure"] += len(testcase.findall("failure"))
                test_names_to_entries[tname]["total"] += 1
                test_names_to_entries[tname]["xmlpath"].append(resultspath)
            else:
                entry = testcase.attrib
                entry["skipped"] = len(testcase.findall("skipped"))
                entry["failure"] = len(testcase.findall("failure"))
                entry["total"] = 1
                entry["xmlpath"] = [resultspath]
                entry["name"] = tname
                test_names_to_entries[tname] = entry

    for testplanpath in args.input_testplans:
        tests_stats = dict()
        with open(testplanpath, 'r') as f:
            testplan = hjson.load(f)
        for test in testplan["testpoints"]:
            if test["name"] not in test_names_to_entries:
                continue
            tdata = test_names_to_entries[test["name"]]
            if test["name"] not in tests_stats:
                tests_stats[test["name"]] = {
                    "name": test["name"],
                    "passing": 0,
                    "total": 0,
                    "file": str(Path(tdata["file"]).relative_to(test_root_dir)),
                    "lineno": tdata["lineno"],
                }
            tests_stats[test["name"]]["total"] += tdata["total"]
            if tdata["skipped"] == 0 and tdata["failure"] == 0:
                tests_stats[test["name"]]["passing"] += tdata["total"] - tdata["skipped"] - tdata["failure"]
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
