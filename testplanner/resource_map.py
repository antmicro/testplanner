# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

"""
Class parsing the resource mapping files for testplanner.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from jinja2 import Template
from jinja2.exceptions import UndefinedError

TESTPLAN_LEVELS = [
    "testplans",
    "testpoints",
    "tests",
]


TESTPLAN_KEYWORDS = TESTPLAN_LEVELS + ["name", "filename"]


def glob_resources(
    base_dir: Path, pattern: str, engine: Optional[str] = None
) -> list[Path]:
    """
    Searches files in base_dir based on given pattern.

    Parameters
    ----------
    base_dir: Path
        Path to the base directory to search for resources
    pattern: str
        String with pattern specifying files to look for
    engine: Optional[str]
        Engine to use for the search. Can be "glob", "regex",
        "fdfind" or None to use the default approach for Testplan
        (stored in self.resource_search_engine).

    Returns
    -------
    list[Path]:
        List of files matching the pattern
    """
    if engine == "glob":
        results = sorted(base_dir.rglob(pattern))
        return results
    elif engine == "fdfind":
        fdfind_binary = os.getenv("FDFIND_BINARY", "fdfind")
        results = (
            subprocess.check_output(
                f'{fdfind_binary} -p -t f -j $(nproc) --regex "^{pattern}$" {base_dir}',
                shell=True,
            )
            .decode("utf-8")
            .strip()
        )
        if not results:
            return []
        return sorted([Path(result) for result in results.split("\n")])
    results = []
    for root, _, filepaths in os.walk(base_dir):
        for filepath in filepaths:
            path = Path(root) / filepath
            if re.fullmatch(pattern, str(path)):
                results.append(path)
    return sorted(results)


class ResourceMap:
    """
    Class processing the resource mappings.
    """

    def __init__(self, resource_map: Optional[Union[Path, str, Dict]]):
        """
        Loads resource mapping.

        Parameters
        ----------
        resource_map: Optional[Union[Path, str, Dict]]
            Path to the resource mapping, or dictionary with
            resource mapping.
        """
        if resource_map is None:
            self.testplan_rules = []
        elif isinstance(resource_map, dict):
            self.testplan_rules = resource_map
        else:
            self.resource_file_map = Path(resource_map)
            with self.resource_file_map.open() as fd:
                self.testplan_rules = yaml.safe_load(fd)
        self.prepare()

    def prepare(
        self,
        resource_type: Optional[str] = None,
        testplan: Optional[str] = None,
        testpoint: Optional[str] = None,
        test: Optional[str] = None,
        testplan_file: Optional[str] = None,
        custom_data: Optional[Any] = None,
    ):
        """
        Resets the search.
        """
        self.testplan = testplan
        self.testpoint = testpoint
        self.test = test
        self.testplan_file = testplan_file
        self.test_source = None
        self.regex_groups = {}
        self.result = None
        self.resource_type = resource_type
        self.custom_data = custom_data

    def resolve_template(self, template: str):
        """
        Resolves the template using loader's state.
        """
        return self.regex_from_template(
            template=template,
            testplan=self.testplan,
            testpoint=self.testpoint,
            test=self.test,
            testplan_file=self.testplan_file,
            test_source=self.test_source,
            regex_groups=self.regex_groups,
            custom_data=self.custom_data,
        )

    def template_match(self, regex_template: str, string: str):
        """
        Check if string matches the template.

        Parameters
        ----------
        regex_template: str
            Regex to check string against
        string: str
            String to check
        """
        return re.match(self.resolve_template(regex_template), str(string))

    def regex_from_template(self, template: str, **kwargs):
        tm = Template(template)
        return tm.render(**kwargs)

    def scan_tree(
        self,
        entries: List,
        names: Optional[List],
        levels: Optional[List],
        expected_levels: Optional[List] = None,
    ) -> bool:
        """
        Recursively scans the tree in search for query.

        Parameters
        ----------
        entries: List
            List of pattern entries
        names: Optional[List]
            Names of current testplan/testpoint/test
            (depending on recursion level)
        levels: Optional[List]
            Names of layers (testplans, testpoints, tests)
        expected_levels: Optional[List[str]]
            Expected levels of testplan where resource should be found.
            The found resource will be picked only if it is found in
            expected_levels (e.g. `["testpoints", "tests"]` will only
            select resources from those levels).

        Returns
        -------
        bool:
            True if the resource was found, False otherwise
        """
        name = names[0]
        level = levels[0]
        if name is None:
            return False
        if level not in entries:
            return False
        for entry in entries[level]:
            if "source" in entry:
                try:
                    self.test_source = self.resolve_template(entry["source"])
                except UndefinedError:
                    pass
            tocheck = "name"
            val = name
            if level == "testplans":
                assert ("filename" in entry) ^ ("name" in entry), (
                    "Testplan entry cannot have both filename and name provided"
                )
                tocheck = "filename" if "filename" in entry else "name"
                val = self.testplan_file if "filename" in entry else self.testplan
            matched = self.template_match(entry[tocheck], val)
            if not matched:
                continue
            self.regex_groups[level[:-1]] = list(matched.groups())
            if expected_levels is None or level in expected_levels:
                if self.resource_type in entry:
                    self.result = self.resolve_template(entry[self.resource_type])
                    return True
            if len(levels) > 1:
                if self.scan_tree(entry, names[1:], levels[1:]):
                    return True
        return False

    def get(
        self,
        resource_type: str,
        testplan_file: Union[str, Path],
        testplan: str,
        testpoint: Optional[str] = None,
        test: Optional[str] = None,
        expected_levels: Optional[List[str]] = None,
        custom_data: Optional[Any] = None,
    ) -> Optional[str]:
        """
        Retrieves resource from resource mapping, if present.

        Parameters
        ----------
        resource_type: str
            Name of the resource
        testplan_file: Union[str, Path]
            Path to the testplan
        testplan: str
            Name of the testplan
        testpoint: Optional[str]
            Name of the testpoint (optional)
        test: Optional[str]
            Name of the test (optional)
        expected_levels: Optional[List[str]]
            Expected levels of testplan where resource should be found.
            The found resource will be picked only if it is found in
            expected_levels (e.g. `["testpoints", "tests"]` will only
            select resources from those levels).
        custom_data: Optional[Any]
            Additional custom data to be delivered to templating context.

        Returns
        -------
        Optional[str]:
            Resource or None if not found
        """
        self.prepare(
            resource_type, testplan, testpoint, test, testplan_file, custom_data
        )
        assert self.resource_type not in TESTPLAN_KEYWORDS, (
            f"resource_type cannot be one of {TESTPLAN_KEYWORDS}"
        )
        self.scan_tree(
            self.testplan_rules,
            names=[testplan, testpoint, test],
            levels=TESTPLAN_LEVELS,
            expected_levels=expected_levels,
        )
        return self.result
