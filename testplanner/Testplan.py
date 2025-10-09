# Copyright (c) 2019-2024 lowRISC <lowrisc.org>
# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

r"""Testpoint and Testplan classes for maintaining the testplan"""

import logging
import os
import re
import sys
from collections import defaultdict
from importlib.resources import path
from pathlib import Path
from typing import Optional, TextIO, Union
from urllib.parse import quote

import git
import hjson
from jinja2 import Template
from tabulate import tabulate

import testplanner.template as html_templates
from testplanner.resource_map import ResourceMap

SUMMARY_TOKEN = "TOTAL"


COMPLETE_TESTPLAN_HEADER = [
    "Stage",
    "Name",
    "Tests",
    "Max Job Runtime",
    "Simulated Time",
    "Passing",
    "Total",
    "Pass Rate",
    "Logs",
]


def get_percentage(value, total):
    """Returns a string representing percentage up to 1 decimal place."""
    if total == 0:
        return "--%"
    perc = value / total * 100 * 1.0
    if perc == 100:
        return "100%"
    return f"{perc}%" if perc.is_integer() else "{0:.1f}%".format(round(perc, 1))


def format_time(time: Optional[Union[int, float, str]]) -> str:
    """Formats time provided in simulation results."""
    if time is None:
        return ""
    if isinstance(time, int):
        return str(time)
    if isinstance(time, float):
        return f"{time:.3f}"
    parsed_time = re.match(r"^(\d+\.?\d*)\s+(\w+)$", time)
    if parsed_time:
        time_val = float(parsed_time.group(1))
        if time_val.is_integer():
            time_val = str(int(time_val))
        else:
            time_val = f"{time_val:.1f}"
        return f"{time_val}{parsed_time.group(2)}"
    else:
        return time


def parse_repo_data(
    repo_name, repo_path, repo_url, git_branch_prefix, git_commit_prefix
):
    repo = git.Repo(repo_path)
    sha = repo.head.commit.hexsha[:8]
    branch = None
    try:
        if repo.head.is_detached:
            branch_name = None
            for parent in repo.head.commit.parents:
                for ref in repo.references:
                    if ref.commit == parent:
                        branch_name = ref.name
                        break
                if branch_name:
                    branch = branch_name
                    break
        else:
            branch = repo.active_branch.name
    except TypeError:
        pass

    if not repo_name:
        repo_name = repo.working_tree_dir.split("/")[-1]

    if not repo_url:
        return repo_name, branch, sha

    if git_branch_prefix and git_branch_prefix in repo_url:
        repo_url = repo_url.split(git_branch_prefix)[0]
    elif git_commit_prefix and git_commit_prefix in repo_url:
        repo_url = repo_url.split(git_commit_prefix)[0]

    if branch:
        branch_url = f"{repo_url}{git_branch_prefix}/{quote(branch)}"
    commit_url = f"{repo_url}{git_commit_prefix}/{quote(sha)}"

    return (
        f'<a target="_blank" href="{repo_url}">{repo_name}</a>',
        f'<a target="_blank" href="{branch_url}">{branch}</a>'
        if branch and (git_branch_prefix is not None)
        else branch,
        f'<a target="_blank" href="{commit_url}">{sha}</a>'
        if git_commit_prefix is not None
        else sha,
    )


def render_log_entry(number: int, log_url, format: str, passing: bool):
    if "html" in format:
        return f"""
        <a href="{log_url}" class="button tooltip">
            <img src="assets/file.svg" alt="Pass #{number}" class="{"log-passing" if passing else "log-failing"}" style="transform: scale(1.25) translatey(1px);"/>
            <span class="tooltip-text tooltip-text-left">Go to {"passing" if passing else "failing"} log #{number}</span>
        </a>
        """
    else:
        return (
            f"* [{'Passing log' if passing else 'Failing log'} #{number}]({log_url})\n"
        )


class Result:
    """The results for a single test"""

    def __init__(
        self,
        name,
        passing=0,
        total=0,
        job_runtime=None,
        simulated_time=None,
        file=None,
        lineno=None,
        passing_logs=None,
        failing_logs=None,
        additional_sources=None,
    ):
        self.name = name
        self.passing = passing
        self.total = total
        self.job_runtime = job_runtime
        self.simulated_time = simulated_time
        self.mapped = False
        self.file = file
        self.lineno = lineno
        self.passing_logs = passing_logs if passing_logs else []
        self.failing_logs = failing_logs if failing_logs else []
        self.additional_sources = additional_sources if additional_sources else {}


class Element:
    """An element of the testplan.

    This is either a testpoint or a covergroup.
    """

    # Type of the testplan element. Must be set by the extended class.
    kind = "none"

    # Mandatory fields in a testplan element.
    fields = ["name", "desc"]

    def __init__(self, raw_dict):
        """Initialize the testplan element.

        raw_dict is the dictionary parsed from the HJSon file.
        """
        # 'tags' is an optional field in addition to the mandatory self.fields.
        self.tags = []

        for field in self.fields:
            try:
                setattr(self, field, raw_dict.pop(field))
            except KeyError as e:
                raise KeyError(
                    f"Error: {self.kind} does not contain all of "
                    f"the required fields:\n{raw_dict}\nRequired:\n"
                    f"{self.fields}\n{e}"
                )

        # Set the remaining k-v pairs in raw_dict as instance attributes.
        for k, v in raw_dict.items():
            setattr(self, k, v)

        # Verify things are in order.
        self._validate()

    def __str__(self):
        # Reindent the multiline desc with 4 spaces.
        desc = "\n".join(["    " + line.lstrip() for line in self.desc.split("\n")])
        return f"  {self.kind.capitalize()}: {self.name}\n  Description:\n{desc}\n"

    def _validate(self):
        """Runs some basic consistency checks."""
        if not self.name:
            raise ValueError(
                f"Error: {self.kind.capitalize()} name cannot be empty:\n{self}"
            )

        # "tags", if updated key must be list.
        if not isinstance(self.tags, list):
            raise ValueError(f"'tags' key in {self} is not a list.")

    def has_tags(self, tags: set) -> bool:
        """Checks if the provided tags match the tags originally set.

        tags is a list of tags that are we are filtering this testpoints with.
        Tags may be preceded with `-` to exclude the testpoints that contain
        that tag.

        Vacuously returns true if tags is an empty list.
        """
        if not tags:
            return True

        for tag in tags:
            if tag.startswith("-"):
                if tag[1:] in self.tags:
                    return False
            else:
                if tag not in self.tags:
                    return False

        return True


class Covergroup(Element):
    """A coverage model item.

    The list of covergroups defines the coverage model for the design. Each
    entry captures the name of the covergroup (suffixed with _cg) and a brief
    description describing what functionality is covered. It is recommended to
    include individual coverpoints and crosses in the description.
    """

    kind = "covergroup"

    def _validate(self):
        super()._validate()
        if not self.name.endswith("_cg"):
            raise ValueError(
                f'Error: Covergroup name {self.name} needs to end with suffix "_cg".'
            )


class Testpoint(Element):
    """An testcase entry in the testplan.

    A testpoint maps to a unique design feature that is planned to be verified.
    It captures following information:
    - name of the planned test
    - a brief description indicating intent, stimulus and checking procedure
    - the targeted stage
    - the list of actual developed tests that verify it

    TODO: Refactor stages to milestones
    TODO: Expose milestones through configuration object so that users can
    define their milestones
    """

    kind = "testpoint"
    fields = Element.fields + ["stage", "tests"]

    def __init__(self, raw_dict):
        if "stage" not in raw_dict:
            raw_dict["stage"] = "N.A."
        super().__init__(raw_dict)

        # List of Result objects indicating test results mapped to this
        # testpoint.
        self.test_results = []

        # If tests key is set to ["N/A"], then don't map this testpoint to the
        # simulation results.
        self.not_mapped = False
        if self.tests == ["N/A"]:
            self.not_mapped = True

    def __str__(self):
        return super().__str__() + (f"  Stage: {self.stage}\n  Tests: {self.tests}\n")

    def _validate(self):
        super()._validate()

        # "tests" key must be list.
        if not isinstance(self.tests, list):
            raise ValueError(f"'tests' key in {self} is not a list.")

    def do_substitutions(self, substitutions):
        """Substitute {wildcards} in tests

        If tests have {wildcards}, they are substituted with the 'correct'
        values using the key=value pairs provided by the substitutions arg.
        Wildcards with no substitution arg are replaced by an empty string.

        substitutions is a dictionary of wildcard-replacement pairs.
        """
        resolved_tests = []
        for test in self.tests:
            match = re.findall(r"{([A-Za-z0-9\_]+)}", test)
            if not match:
                resolved_tests.append(test)
                continue

            # 'match' is a list of wildcards used in the test. Get their
            # corresponding values.
            subst = {item: substitutions.get(item, "") for item in match}

            resolved = [test]
            for item, value in subst.items():
                values = value if isinstance(value, list) else [value]
                resolved = [
                    t.replace(f"{{{item}}}", v) for t in resolved for v in values
                ]
            resolved_tests.extend(resolved)

        self.tests = resolved_tests

    def map_test_results(self, test_results):
        """Map test results to tests against this testpoint.

        Given a list of test results find the ones that match the tests listed
        in this testpoint and buiild a structure. If no match is found, or if
        self.tests is an empty list, indicate 0/1 passing so that it is
        factored into the final total.
        """
        # If no written tests were indicated for this testpoint, then reuse
        # the testpoint name to count towards "not run".
        if not self.tests:
            self.test_results = [Result(name=self.name)]
            return

        # Skip if this testpoint is not meant to be mapped to the simulation
        # results.
        if self.not_mapped:
            return

        for tr in test_results:
            assert isinstance(tr, Result)
            if tr.name in self.tests:
                tr.mapped = True
                self.test_results.append(tr)

        # Did we map all tests in this testpoint? If we are mapping the full
        # testplan, then count the ones not found as "not run", i.e. 0 / 0.
        tests_mapped = [tr.name for tr in self.test_results]
        for test in self.tests:
            if test not in tests_mapped:
                self.test_results.append(Result(name=test))


class Testplan:
    """The full testplan

    The list of Testpoints and Covergroups make up the testplan.
    """

    rsvd_keywords = ["import_testplans", "testpoints", "covergroups"]
    element_cls = {"testpoint": Testpoint, "covergroup": Covergroup}

    @staticmethod
    def _parse_hjson(filename: Path):
        """Parses an input file with HJson and returns a dict."""
        try:
            return hjson.load(open(filename, "r"))
        except IOError as e:
            print(f"IO Error when opening file {filename}\n{e}")
        except hjson.scanner.HjsonDecodeError as e:
            print(f"Error: Unable to decode HJSON with file {filename}:\n{e}")
        sys.exit(1)

    @staticmethod
    def _create_testplan_elements(kind: str, raw_dicts_list: list, tags: set):
        """Creates testplan elements from the list of raw dicts.

        kind is either 'testpoint' or 'covergroup'.
        raw_dicts_list is a list of dictionaries extracted from the HJson file.
        """
        items = []
        item_names = set()
        for dict_entry in raw_dicts_list:
            try:
                item = Testplan.element_cls[kind](dict_entry)
            except KeyError as e:
                print(f"Error: {kind} arg is invalid.\n{e}")
                sys.exit(1)
            except ValueError as e:
                print(f"{kind}\n{dict_entry}\n{e}")
                sys.exit(1)

            if item.name in item_names:
                print(f"Error: Duplicate {kind} item found with name: {item.name}")
                sys.exit(1)

            # Filter out the item by tags if provided.
            if item.has_tags(tags):
                items.append(item)
                item_names.add(item.name)
        return items

    @staticmethod
    @staticmethod
    def get_dv_style_css():
        """Returns text with HTML CSS style for a table."""
        return (
            "<link rel='stylesheet' type='text/css' href='main.css'>"
            "<link rel='stylesheet' type='text/css' href='cov.css'>"
        )

    def __str__(self):
        lines = [f"Name: {self.name}\n"]
        lines += ["Testpoints:"]
        lines += [f"{t}" for t in self.testpoints]
        lines += ["Covergroups:"]
        lines += [f"{c}" for c in self.covergroups]
        return "\n".join(lines)

    def __init__(
        self,
        filename,
        repo_top=None,
        name=None,
        diagram_path=None,
        resource_map_data=None,
        source_url_prefix="",
        git_branch_prefix="",
        git_commit_prefix="",
        docs_url_prefix="",
        comments=None,
    ):
        """Initialize the testplan.

        filename is the HJson file that captures the testplan. It may be
        suffixed with tags separated with a colon delimiter to filter the
        testpoints. For example: path/too/foo_testplan.hjson:bar:baz
        repo_top is an optional argument indicating the path to top level repo
        / project directory. It is used with filename arg.
        name is an optional argument indicating the name of the testplan / DUT.
        It overrides the name set in the testplan HJson.
        """
        self.name = None
        self.diagram_path = diagram_path
        self.testpoints = []
        self.covergroups = []
        self.test_results_mapped = False
        self.resource_map = ResourceMap(resource_map_data)
        self.repo_top = repo_top
        self.source_url_prefix = source_url_prefix
        self.git_branch_prefix = git_branch_prefix
        self.git_commit_prefix = git_commit_prefix
        self.docs_url_prefix = docs_url_prefix.rstrip("/")
        self.comments = comments

        # Split the filename into filename and tags, if provided.
        split = str(filename).split(":")
        filename = Path(split[0])
        tags = set(split[1:])

        if filename.exists():
            self._parse_testplan(filename, tags, repo_top)

        self.filename = filename

        if name:
            self.name = name

        if not self.name:
            print("Error: the testplan 'name' is not set!")
            print(self.filename)
            sys.exit(1)

        # Represents current progress towards each stage. Stage = N.A.
        # is used to indicate the unmapped tests.
        self.progress = {}
        for key in set([i.stage for i in self.testpoints] + ["N.A."]):
            self.progress[key] = {
                "passing": 0,
                "written": 0,
                "total": 0,
                "progress": 0.0,
            }

    @staticmethod
    def _get_imported_testplan_paths(
        parent_testplan: Path, imported_testplans: list, repo_top: Path
    ) -> list:
        """Parse imported testplans with correctly set paths.

        Paths of the imported testplans can be set relative to repo_top
        or relative to the parent testplan importing it. Path anchored to
        the repo_top has higher precedence. If the path is not relative to
        either, we check if the path is absolute (which must be avoided!),
        else we raise an exception.

        parent_testplan is the testplan currently being processed which
        importing the sub-testplans.
        imported_testplans is the list of testplans it imports - retrieved
        directly from its Hjson file.
        repo_top is the path to the repository's root directory.

        Returns a list of imported testplans with correctly set paths.
        Raises FileNotFoundError if the relative path to the testplan is
        not anchored to repo_top or the parent testplan.
        """
        result = []
        for testplan in imported_testplans:
            path = repo_top / testplan
            if path.exists():
                result.append(path)
                continue

            path = parent_testplan.parent / testplan
            if path.exists():
                result.append(path)
                continue

            # In version-controlled codebases, references to absolute paths
            # must not exist. This usecase is supported anyway.
            path = Path(testplan)
            if path.exists():
                result.append(path)
                continue

            raise FileNotFoundError(
                f"Testplan {testplan} imported by {parent_testplan} does not exist."
            )

        return result

    def _parse_testplan(self, filename: Path, tags: set, repo_top=None):
        """Parse testplan Hjson file and create the testplan elements.

        It creates the list of testpoints and covergroups extracted from the
        file.

        filename is the path to the testplan file written in HJson format.
        repo_top is an optional argument indicating the path to repo top.
        """
        if repo_top is None:
            # Assume dvsim's original location: $REPO_TOP/third_party/dvsim.
            repo_top = Path(__file__).parent.parent.parent.resolve()

        obj = Testplan._parse_hjson(filename)

        parsed = set()
        parent_testplan = Path(filename)
        imported_testplans = self._get_imported_testplan_paths(
            parent_testplan, obj.get("import_testplans", []), repo_top
        )

        while imported_testplans:
            testplan = imported_testplans.pop(0)
            if testplan in parsed:
                print(
                    f"Error: encountered the testplan {testplan} again, "
                    "which was already parsed. Please check for circular "
                    "dependencies."
                )
                sys.exit(1)
            parsed.add(testplan)
            data = self._parse_hjson(testplan)
            imported_testplans.extend(
                self._get_imported_testplan_paths(
                    testplan, data.get("import_testplans", []), repo_top
                )
            )
            obj = _merge_dicts(obj, data)

        self.name = obj.get("name")

        testpoints = obj.get("testpoints", [])
        self.testpoints = self._create_testplan_elements("testpoint", testpoints, tags)

        covergroups = obj.get("covergroups", [])
        self.covergroups = self._create_testplan_elements(
            "covergroup", covergroups, set()
        )

        if not testpoints and not covergroups:
            print(f"Error: No testpoints or covergroups found in {filename}")
            sys.exit(1)

        # Any variable in the testplan that is not a recognized HJson field can
        # be used as a substitution variable.
        substitutions = {k: v for k, v in obj.items() if k not in self.rsvd_keywords}
        for tp in self.testpoints:
            tp.do_substitutions(substitutions)

        self._sort()

    def _sort(self):
        """Sort testpoints by stage and covergroups by name."""
        self.testpoints.sort(key=lambda x: x.stage)
        self.covergroups.sort(key=lambda x: x.name)

    def get_stage_regressions(self):
        regressions = defaultdict(set)
        for tp in self.testpoints:
            if tp.not_mapped:
                continue
            if tp.stage in tp.stages[1:]:
                regressions[tp.stage].update({t for t in tp.tests if t})

        # Build regressions dict into a hjson like data structure
        return [{"name": ms, "tests": list(regressions[ms])} for ms in regressions]

    def create_testplan_worksheet(self, xls):
        xls.create_or_select_sheet(self.name)
        stages = {}
        for tp in self.testpoints[::-1]:
            stages.setdefault(tp.stage, list()).append(tp)
        for stage, testpoints in stages.items():
            for tp in testpoints:
                # This dict maps section names in descriptions
                # to column names in XLSX_writer.
                # The keys are used as a list of words for
                # regexes that take out relevant paragraphs
                # from the text. 'Comment' is omitted as it's the
                # rest of the description and should be separate from
                # structured data.
                headers = {
                    # Removed since it's not that simple to dedcide where it should be mapped to
                    "Testbench": "testbench",
                    "Intent": "intent",
                    "Stimulus": "stimulus_procedure",
                    "Check": "checking_mechanism",
                    "Coverpoints": "coverpoints",
                }
                parts, desc = xls.parse_standard_description(tp.desc, headers, True)
                # for now, it's the only field besides name and comment
                # (which are processed separately) that is not a part of the description
                parts["milestone"] = stage
                xls.testplan_add_entry(tp.name, parts, desc)
        xls.format_string_columns()
        xls.save()

    def generate_xls_sim_results(self, xls):
        stages = {}
        for tp in self.testpoints:
            stages.setdefault(tp.stage, list()).append(tp)
        for stage, tps in stages.items():
            for tp in tps[::-1]:
                if tp.name != "N.A.":
                    testplan_str = ""
                    total = 0
                    passing = 0
                    for i in tp.test_results:
                        if i.total > 0:
                            result = "Passed" if i.passing else "FAILED"
                            if i.passing:
                                passing += 1
                        else:
                            result = "Not implemented"
                        total += 1
                        testplan_str += f"  *{i.name}: {result}\n"
                    testplan_str = (
                        f"TOTAL: {get_percentage(passing, total)}\n\nIndividual test results:\n"
                        + testplan_str
                    )
                    rich_testplan_str = xls.embolden_line(testplan_str, 0)
                    if tp.name == "Unmapped tests":
                        # Special handling for when test results contain tests
                        # that were not present in the corresponding testplan

                        # Save the default new entry index and replace it
                        # with the first empty row index
                        save_tpl_entry_idx = xls.tpl_entry_idx
                        calc_dim_y = re.sub(
                            "[a-zA-Z]",
                            "",
                            xls.active_worksheet.calculate_dimension().split(":")[1],
                        )
                        xls.tpl_entry_idx = int(calc_dim_y) + 1
                        xls.testplan_add_entry(
                            xls.embolden_line(tp.name, 0),
                            {"status": rich_testplan_str},
                            "Unmapped test results",
                        )
                        # Restore the index to the default
                        # (first empty row in the template sheet)
                        xls.tpl_entry_idx = save_tpl_entry_idx
                    else:
                        xls.testplan_append_to_entry_col(
                            col="status",
                            content=rich_testplan_str,
                            entry_key=tp.name,
                        )
        xls.format_string_columns()
        xls.save()

    def write_testplan_doc(
        self,
        output: TextIO,
        sim_results_path: Path = None,
        target_sim_results_path: Optional[Path] = None,
        target_sim_results_url_prefix: Optional[str] = None,
    ) -> None:
        """Write testplan documentation in markdown from the hjson testplan."""
        stages = {}
        for tp in self.testpoints:
            stages.setdefault(tp.stage, list()).append(tp)

        output.write(f"# {self.name}\n\n")

        if self.diagram_path:
            diagram_rel_path = os.path.relpath(
                os.path.abspath(self.diagram_path),
                os.path.dirname(output.name),
            )
            output.write(
                f":::{{figure-md}} {self.name.lower().replace(' ', '-')}-testbench-diagram\n"
            )
            output.write(f"![{self.name}]({diagram_rel_path})\n\n")
            output.write(
                f"{self.name} UVM testbench diagram with static and dynamic components\n"
            )
            output.write(":::\n")

        if self.resource_map:
            source = self.resource_map.get("source", self.filename, self.name)
            if source is not None:
                candidatepaths = sorted(self.repo_top.resolve().glob(source))
                assert len(candidatepaths) <= 1, (
                    f"Multiple source files assigned to testplan {self.name}:  {source} {candidatepaths}"
                )
                if len(candidatepaths) == 1:
                    path = candidatepaths[0].relative_to(self.repo_top.resolve())
                    output.write(f"[Source file]({self.source_url_prefix}/{path})\n\n")
                else:
                    print(
                        f'Source file for testplan "{self.name}" not found ({self.filename}) (regex: {source})!'
                    )

        tests_to_urls = {}
        if sim_results_path:
            sim_results = Testplan._parse_hjson(sim_results_path)
            sim_results = sim_results.get("test_results", [])
            for item in sim_results:
                if all(f in item for f in ["name", "file"]):
                    if Path(item["file"]).is_symlink():
                        item["file"] = str(
                            Path(item["file"]).resolve().relative_to(self.repo_top)
                        )
                    tests_to_urls[item["name"]] = (
                        f"{self.source_url_prefix}/{item['file']}"
                    )
                    if "lineno" in item:
                        tests_to_urls[item["name"]] += f"#L{item['lineno']}"
            # TODO (glatosinski): To fix Myst's link resolution, {.external}
            # attribute is added to link. This requires "inline_attrs"
            # extension in myst_enable_extensions
            url_prefix = (
                target_sim_results_url_prefix if target_sim_results_url_prefix else "./"
            )
            output.write(
                f"[Test results]({url_prefix}{os.path.relpath(target_sim_results_path, Path(output.name).parent)}){{.external}}\n\n"
            )

        output.write("## Testpoints\n\n")
        for stage, testpoints in stages.items():
            testpoint_header = "###"
            if stage != "N.A.":
                output.write(f"### Stage {stage} Testpoints\n\n")
                testpoint_header = "####"
            for tp in testpoints:
                output.write(f"{testpoint_header} `{tp.name}`\n\n")
                if len(tp.tests) == 0:
                    output.write("No Tests Implemented")
                elif len(tp.tests) == 1:
                    test_name = self.find_test_file(tp.tests[0], tp.name, tests_to_urls)
                    output.write(f"Test: {test_name}")
                else:
                    output.write("Tests:\n")
                    for test in tp.tests:
                        test_name = self.find_test_file(test, tp.name, tests_to_urls)
                        output.write(f"- {test_name}\n")

                output.write("\n\n" + tp.desc.strip() + "\n\n")

        if self.covergroups:
            output.write("## Covergroups\n\n")
            for covergroup in self.covergroups:
                output.write(f"### {covergroup.name}\n\n{covergroup.desc.strip()}\n\n")

    def find_test_file(self, test_name, testpoint_name, tests_to_urls):
        if test_name in tests_to_urls:
            return f"[{test_name}]({tests_to_urls[test_name]})"
        test_source = self.resource_map.get(
            "source",
            self.filename,
            self.name,
            testpoint_name,
            test_name,
            expected_levels=["tests"],
        )
        if test_source is None:
            return test_name
        candidatepaths = sorted(self.repo_top.resolve().glob(test_source))
        assert len(candidatepaths) <= 1, (
            f"Multiple files assigned to test {self.name}/{testpoint_name}/{test_name}:  {test_source} {candidatepaths}"
        )
        if len(candidatepaths) == 0:
            return test_name
        relative_path = candidatepaths[0].relative_to(self.repo_top.resolve())
        return f"[{test_name}]({self.source_url_prefix}/{relative_path})"

    def map_test_results(self, test_results, format="md"):
        """Map test results to testpoints."""
        # Maintain a list of tests we already counted.
        tests_seen = set()

        def _process_testpoint(testpoint, totals):
            """Computes the testplan progress and the sim footprint.

            totals is a list of Testpoint items that represent the total number
            of tests passing for each stage. The sim footprint is simply
            the sum total of all tests run in the simulation, counted for each
            stage and also the grand total.
            """
            ms = testpoint.stage
            for tr in testpoint.test_results:
                if not tr:
                    continue

                if tr.name in tests_seen:
                    continue

                tests_seen.add(tr.name)
                # Compute the testplan progress.
                self.progress[ms]["total"] += 1
                if tr.total != 0:
                    if tr.passing == tr.total:
                        self.progress[ms]["passing"] += 1
                    self.progress[ms]["written"] += 1

                # Compute the stage total & the grand total.
                totals[ms].test_results[0].passing += tr.passing
                totals[ms].test_results[0].total += tr.total
                if ms != "N.A.":
                    totals["N.A."].test_results[0].passing += tr.passing
                    totals["N.A."].test_results[0].total += tr.total

        totals = {}
        # Create testpoints to represent the total for each stage & the
        # grand total.
        totstages = set([i.stage for i in self.testpoints] + ["N.A."])
        for ms in totstages:
            arg = {
                "name": "N.A.",
                "desc": f"Total {ms} tests",
                "stage": ms,
                "tests": [],
            }
            totals[ms] = Testpoint(arg)
            target = ""
            if ms != "N.A.":
                target = f" for {ms}"
            if format == "md":
                totals[ms].test_results = [Result(f"**{SUMMARY_TOKEN}{target}**")]
            else:
                totals[ms].test_results = [Result(f"<b>{SUMMARY_TOKEN}{target}</b>")]

        # Create unmapped as a testpoint to represent tests from the simulation
        # results that could not be mapped to the testpoints.
        arg = {
            "name": "Unmapped tests",
            "desc": "Unmapped tests",
            "stage": "N.A.",
            "tests": [],
        }
        unmapped = Testpoint(arg)

        # Now, map the simulation results to each testpoint.
        for tp in self.testpoints:
            tp.map_test_results(test_results)
            _process_testpoint(tp, totals)

        # If we do have unmapped tests, then count that too.
        unmapped.test_results = [tr for tr in test_results if not tr.mapped]
        _process_testpoint(unmapped, totals)

        # Add stage totals back into 'testpoints' and sort.
        for ms in set([i.stage for i in self.testpoints]):
            self.testpoints.append(totals[ms])
        self._sort()

        # Append unmapped and the grand total at the end.
        if unmapped.test_results:
            self.testpoints.append(unmapped)
        # if there is only one stage + TOTAL, print only TOTAL for current stage
        if len(totstages) > 2:
            self.testpoints.append(totals["N.A."])

        # Compute the progress rate for each stage.
        for ms in set([i.stage for i in self.testpoints]):
            stat = self.progress[ms]

            # Remove stages that are not targeted.
            if stat["total"] == 0:
                self.progress.pop(ms)
                continue

            stat["progress"] = get_percentage(stat["passing"], stat["total"])

        self.test_results_mapped = True

    def map_covergroups(self, cgs_found):
        """Map the covergroups found from simulation to the testplan.

        For now, this does nothing more than 'check off' the covergroup
        found from the simulation results with the coverage model in the
        testplan by updating the progress dict.

        cgs_found is a list of covergroup names extracted from the coverage
        database after the simulation is run with coverage enabled.
        """
        if not self.covergroups:
            return

        written = 0
        total = 0
        for cg in self.covergroups:
            total += 1
            if cg.name in cgs_found:
                written += 1

        self.progress["Covergroups"] = {
            "total": total,
            "written": written,
            "passing": written,
            "progress": get_percentage(written, total),
        }

    def get_test_results_table(self, map_full_testplan=True, format="pipe"):
        """Return the mapped test results into a markdown table."""
        assert self.test_results_mapped, "Have you invoked map_test_results()?"
        stages = set()
        has_logs = False
        for tp in self.testpoints:
            stage = "" if tp.stage == "N.A." else tp.stage
            stages.add(stage)
            for tr in tp.test_results:
                if tr.passing_logs or tr.failing_logs:
                    has_logs = True
        skip_stages = False
        if not (len(stages) > 1 or list(stages)[0] != ""):
            skip_stages = True
        header = COMPLETE_TESTPLAN_HEADER[
            (1 if skip_stages else 0) : (None if has_logs else -1)
        ]
        colalign = (
            ("center",) * (1 if skip_stages else 2)
            + ("left",)
            + ("center",) * (5 + has_logs)
        )
        table = []
        self.stage_text_to_stage = {}
        prev_stage = ""
        for tp in self.testpoints:
            stage = "" if tp.stage == "N.A." else tp.stage
            tp_name = "" if tp.name == "N.A." else tp.name
            is_new_stage = stage != prev_stage
            prev_stage = stage
            if "html" in format and tp_name != "":
                tp_text = f"<span title='{tp.desc}'>{tp_name}<span>"
                # for now comments will only work in HTML
                if self.comments:
                    tp_text += self.comments.comment_testpoint(self.filename, tp_name)
                    tp_text += self.comments.get_testpoint_estimation(
                        self.filename, tp_name
                    )
                tp_name = tp_text

            for tr in tp.test_results:
                if tr.total == 0 and not map_full_testplan:
                    continue
                pass_rate = get_percentage(tr.passing, tr.total)

                job_runtime = format_time(tr.job_runtime)
                simulated_time = format_time(tr.simulated_time)

                test_name = tr.name
                if tr.file:
                    if Path(tr.file).exists():
                        if Path(tr.file).is_symlink():
                            tr.file = str(
                                Path(tr.file).resolve().relative_to(self.repo_top)
                            )
                    if "html" in format:
                        file_fmt = tr.file
                        if tr.lineno is not None:
                            file_fmt += f"#L{tr.lineno}"
                        test_name = (
                            f"<a href={self.source_url_prefix}/{file_fmt}>{tr.name}</a>"
                        )
                    else:
                        test_name = f"[{tr.name}]({self.source_url_prefix}/{tr.file}"
                        if tr.lineno is not None:
                            test_name += f"#L{tr.lineno})"
                        else:
                            test_name += ")"
                logs = ""
                if has_logs:
                    for i, passing_log in enumerate(tr.passing_logs):
                        logs += render_log_entry(i, passing_log, format, True)

                    for i, failing_log in enumerate(tr.failing_logs):
                        logs += render_log_entry(i, failing_log, format, False)

                # TODO add support for markdown
                if "html" in format and tr.additional_sources:
                    if tr.additional_sources:
                        test_name += '<br/><div class="additional-sources">'
                        test_name += " | ".join(
                            [
                                f"<a href={self.source_url_prefix}/{v}>{k}</a>"
                                for k, v in tr.additional_sources.items()
                            ]
                        )
                        test_name += "</div>"

                # for now comments will only work in HTML
                if "html" in format and self.comments:
                    test_name += self.comments.comment_test(self.filename, tr.name)
                    test_name += self.comments.get_test_estimation(
                        self.filename, tr.name
                    )

                stage_text = ""
                if not skip_stages and is_new_stage:
                    is_new_stage = False
                    stage_text = stage
                    # for now comments will only work in HTML
                    if "html" in format and self.comments:
                        stage_text += self.comments.comment_stage(self.filename, stage)

                    self.stage_text_to_stage[stage_text] = stage

                table.append(
                    ([stage_text] if not skip_stages else [])
                    + [
                        tp_name,
                        test_name,
                        job_runtime,
                        simulated_time,
                        tr.passing,
                        tr.total,
                        pass_rate,
                    ]
                    + ([logs] if has_logs else [])
                )
                stage = ""
                tp_name = ""

        # for now comments will only work in HTML
        if "html" in format:
            text = "\n<h3> Test Results\n </h3>"
            if self.comments:
                text += self.comments.comment_testplan(self.filename)
                text += self.comments.get_estimation_totals(self.filename)
            from copy import deepcopy

            self.result_data_store = deepcopy(header), deepcopy(table), self.name

        else:
            text = "\n### Test Results\n"
        text += tabulate(table, headers=header, tablefmt=format, colalign=colalign)
        text += "\n"
        return text

    def get_progress_table(self, format="pipe"):
        """Returns the current progress of the effort towards the testplan."""
        assert self.test_results_mapped, "Have you invoked map_test_results()?"
        header = []
        table = []
        skip_stage = False
        stages = list(set([key for key in self.progress.keys()]))
        if len(stages) == 1 and stages[0] == "N.A.":
            skip_stage = True
        for key in sorted(self.progress.keys()):
            stat = self.progress[key]
            values = [v for v in stat.values()]
            if self.progress[key]["total"] == 0:
                continue
            if not header:
                header = ([] if skip_stage else ["Stage"]) + [
                    k.capitalize() for k in stat
                ]
            table.append(
                ([] if skip_stage else [key if key != "N.A." else ""]) + values
            )

        if "html" in format:
            text = "\n<h3> Testplan Progress\n </h3>"
        else:
            text = "\n### Testplan Progress\n"
        colalign = ("center",) * len(header)
        text += tabulate(table, headers=header, tablefmt=format, colalign=colalign)
        text += "\n"
        return text

    def linkify(self, text):
        """Adds links based on regexes in self.link_regexes (originally from comments.hjson)."""

        def linkify_single(text):
            for r in self.link_regexes:
                text, n = r["regex"].subn(
                    r'<a href="' + r["link"] + '">' + r["text"] + "</a>", text, 1
                )
                if n != 0:
                    return text
            logging.warning(
                f"Matched combined link regex, but failed to replace: {text}"
            )

        text = self.combined_link_regex.sub(lambda m: linkify_single(m.group()), text)

        return text

    @staticmethod
    def get_cov_results_table(cov_results):
        """Returns the coverage in a table format.

        cov_results is a list of dicts with name and result keys, representing
        the name of the coverage metric and the result in decimal / fp value.
        """
        if not cov_results:
            return ""

        try:
            cov_header = [c["name"].capitalize() for c in cov_results]
            cov_values = [c["result"] for c in cov_results]
        except KeyError as e:
            print(f"Malformed cov_results:\n{cov_results}\n{e}")
            sys.exit(1)

        colalign = ("center",) * len(cov_header)
        text = "\n### Coverage Results\n"
        text += tabulate(
            [cov_values],
            headers=cov_header,
            tablefmt="pipe",
            colalign=colalign,
        )
        text += "\n"
        return text

    def get_test_results_summary(self):
        """Returns the final total as a summary."""
        assert self.test_results_mapped, "Have you invoked map_test_results()?"

        # The last item in tespoints is the final sum total. We use that to
        # return the results summary as a dict.
        total = self.testpoints[-1]
        assert total.name == "N.A."
        assert total.stage == "N.A."

        tr = total.test_results[0]

        result = {}
        result["Name"] = self.name.upper()
        result["Passing"] = tr.passing
        result["Total"] = tr.total
        result["Pass Rate"] = get_percentage(tr.passing, tr.total)
        return result

    def get_sim_results(
        self,
        sim_results_file,
        summary_output_path: Union[Path, None] = None,
        repo_path: Union[Path, None] = None,
        repo_name: Union[str, None] = None,
        fmt="md",
    ):
        """Returns the mapped sim result tables in HTML formatted text.

        The data extracted from the sim_results table HJson file is mapped into
        a test results, test progress, covergroup progress and coverage tables.

        fmt is either 'md' (markdown) or 'html'.
        """
        assert fmt in ["md", "html"]
        sim_results = Testplan._parse_hjson(sim_results_file)
        test_results_ = sim_results.get("test_results", None)

        test_results = []
        for item in test_results_:
            try:
                tr = Result(
                    item["name"],
                    item["passing"],
                    item["total"],
                    simulated_time=item.get("simulated_time", None),
                    job_runtime=item.get("job_runtime", None),
                    file=item.get("file", None),
                    lineno=item.get("lineno", None),
                    passing_logs=item.get("passing_logs", []),
                    failing_logs=item.get("failing_logs", []),
                    additional_sources=item.get("additional_sources", {}),
                )
                test_results.append(tr)
            except KeyError as e:
                print(f"Error: data in {sim_results_file} is malformed!\n{e}")
                sys.exit(1)

        self.map_test_results(test_results, fmt)
        self.map_covergroups(sim_results.get("covergroups", []))
        self.timestamp = sim_results["timestamp"]
        self.cov_results = sim_results.get("cov_results", [])

        if fmt == "html":
            return self.sim_results_html(summary_output_path, repo_path, repo_name)
        else:
            return self.sim_results_markdown(summary_output_path)

    @staticmethod
    def render_template(data):
        with path(html_templates, "testplan_simulations.html") as resourcetemplatefile:
            with open(resourcetemplatefile, "r") as f:
                resourcetemplate = f.read()
        tm = Template(resourcetemplate)
        content = tm.render(data)
        return content

    def get_testplan_doc_url(self):
        doc_url = ""
        found_suffix = self.resource_map.get("docs_html", self.filename, self.name)
        if found_suffix:
            doc_url = f"{self.docs_url_prefix}/{found_suffix}"
        return doc_url

    def get_testplan_source_url(self):
        root = Path(self.repo_top).resolve()
        testplan_repo_path = Path(self.filename).resolve().relative_to(root)
        if self.source_url_prefix:
            return f"{self.source_url_prefix}/{testplan_repo_path}"
        return ""

    def sim_results_html(
        self,
        summary_output_path,
        repo_path: Union[Path, None] = None,
        repo_name: Union[str, None] = None,
    ):
        if summary_output_path:
            summary_url = summary_output_path
        else:
            summary_url = ""
        doc_url = self.get_testplan_doc_url()

        progress_table = self.get_progress_table(format="unsafehtml")
        data = {
            "timestamp": self.timestamp,
            "title": self.name,
            "progress_table": progress_table,
            "test_results_table": self.get_test_results_table(format="unsafehtml"),
            # This was always empty thus far, leaving it here but it's not
            # templated in any way
            "cov_results": Testplan.get_cov_results_table(self.cov_results),
            "summary_url": summary_url,
            "documentation_url": doc_url,
            "testplan_source_url": self.get_testplan_source_url(),
        }
        if repo_path:
            data["git_repo"], data["git_branch"], data["git_sha"] = parse_repo_data(
                repo_name,
                repo_path,
                self.source_url_prefix,
                self.git_branch_prefix,
                self.git_commit_prefix,
            )
        return Testplan.render_template(data)

    def sim_results_markdown(self, summary_output_path):
        text = "# Simulation Results\n"
        text += "## Run on {}\n".format(self.timestamp)
        if summary_output_path:
            text += f"[<- back to summary]({summary_output_path})"
        doc_url = self.get_testplan_doc_url()
        if doc_url:
            text += f"[view documentation]({doc_url})\n"
        text += self.get_test_results_table()
        text += self.get_progress_table()

        text += Testplan.get_cov_results_table(self.cov_results)
        return text

    def get_testplan_summary(
        self,
        summary_output_path: Path,
        sim_results_file: Path,
        target_sim_results_path: Path,
        html_links: bool = False,
    ):
        """Provides a summary for testplan results.

        Provides an array with:
        * an URL to simulation results,
        * passing tests,
        * implemented tests,
        * total number of tests
        * implementation progress
        * percentage of succeeding tests.
        """
        total = 0
        passing = 0
        written = 0
        tests_seen = set()
        for tp in self.testpoints:
            for tr in tp.test_results:
                if not tr:
                    continue
                if tr.name.startswith("<b>TOTAL"):
                    continue
                if tr.name.startswith("**TOTAL"):
                    continue
                if tr.name in tests_seen:
                    continue
                tests_seen.add(tr.name)
                if tr.total != 0:
                    if tr.passing == tr.total:
                        passing += 1
                    written += 1
                total += 1
        path_rel = os.path.relpath(
            target_sim_results_path.parent, start=summary_output_path.parent
        )
        if html_links:
            link = f"<a href='{os.path.join(path_rel, target_sim_results_path.name)}'>{self.name}</a>"
        else:
            link = (
                f"[{self.name}]({os.path.join(path_rel, target_sim_results_path.name)})"
            )

        return [
            link,
            passing,
            written,
            total,
            get_percentage(written, total),
            get_percentage(passing, written),
        ]

    def get_testplan_name_with_url(
        self,
        summary_output_path: Optional[Path],
        target_sim_results_path: Optional[Path],
        html_links: bool = False,
    ):
        """
        Provides URL to testplan results or testplan name if no paths are
        provided.
        """
        if summary_output_path is None or target_sim_results_path is None:
            return self.name
        path_rel = os.path.relpath(
            target_sim_results_path.parent, start=summary_output_path.parent
        )
        link = f"<a href='{os.path.join(path_rel, target_sim_results_path.name)}'>{self.name}</a>"
        if not html_links:
            link = (
                f"[{self.name}]({os.path.join(path_rel, target_sim_results_path.name)})"
            )
        return link

    def update_stages_progress(
        self,
        sim_results_file,
        stages_progress=None,
    ) -> dict[str, dict[str, int]]:
        """
        Provides information on implemented, passing and total tests per stage.
        """
        tests_seen = set()
        if stages_progress is None:
            stages_progress = defaultdict(
                lambda: {"passing": 0, "written": 0, "total": 0}
            )
        for tp in self.testpoints:
            stage = tp.stage
            for tr in tp.test_results:
                if not tr:
                    continue

                # skip dummy entries representing TOTAL rows
                if tr.name.startswith("<b>TOTAL") or tr.name.startswith("**TOTAL"):
                    continue

                if tr.name in tests_seen:
                    continue

                tests_seen.add(tr.name)

                stages_progress[stage]["total"] += 1
                if tr.total != 0:
                    if tr.passing == tr.total:
                        stages_progress[stage]["passing"] += 1
                    stages_progress[stage]["written"] += 1

        return stages_progress


def _merge_dicts(list1, list2, use_list1_for_defaults=True):
    """Merge 2 dicts into one

    This function takes 2 dicts as args list1 and list2. It recursively merges
    list2 into list1 and returns list1. The recursion happens when the
    value of a key in both lists is a dict. If the values of the same key in
    both lists (at the same tree level) are of dissimilar type, then there is a
    conflict and an error is thrown. If they are of the same scalar type, then
    the third arg "use_list1_for_defaults" is used to pick the final one.
    """
    for key, item2 in list2.items():
        item1 = list1.get(key)
        if item1 is None:
            list1[key] = item2
            continue

        # Both dictionaries have an entry for this key. Are they both lists? If
        # so, append.
        if isinstance(item1, list) and isinstance(item2, list):
            list1[key] = item1 + item2
            continue

        # Are they both dictionaries? If so, recurse.
        if isinstance(item1, dict) and isinstance(item2, dict):
            _merge_dicts(item1, item2)
            continue

        # We treat other types as atoms. If the types of the two items are
        # equal pick one or the other (based on use_list1_for_defaults).
        if isinstance(item1, type(item2)) and isinstance(item2, type(item1)):
            list1[key] = item1 if use_list1_for_defaults else item2
            continue

        # Oh no! We can't merge this.
        print(
            "ERROR: Cannot merge dictionaries at key {!r} because items "
            "have conflicting types ({} in 1st; {} in 2nd).".format(
                key, type(item1), type(item2)
            )
        )
        sys.exit(1)

    return list1
