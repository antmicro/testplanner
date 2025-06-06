import re
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml
from jinja2 import Template

TESTPLAN_LEVELS = [
    "testplans",
    "testpoints",
    "tests",
]


TESTPLAN_KEYWORDS = TESTPLAN_LEVELS + ["name", "filename"]


class ResourceMap:
    def __init__(self, resource_map: Optional[Union[Path, str, Dict]]):
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
    ):
        self.testplan = testplan
        self.testpoint = testpoint
        self.test = test
        self.testplan_file = testplan_file
        self.test_source = None
        self.regex_groups = {}
        self.result = None
        self.resource_type = resource_type

    def resolve_template(self, template: str):
        return self.regex_from_template(
            template=template,
            testplan=self.testplan,
            testpoint=self.testpoint,
            test=self.test,
            testplan_file=self.testplan_file,
            test_source=self.test_source,
            regex_groups=self.regex_groups,
        )

    def template_match(self, regex_template: str, string: str):
        return re.match(self.resolve_template(regex_template), str(string))

    def regex_from_template(self, template: str, **kwargs):
        tm = Template(template)
        return tm.render(**kwargs)

    def scan_tree(self, entries: List, names: Optional[List], levels: Optional[List]):
        name = names[0]
        level = levels[0]
        if name is None:
            return None
        if level not in entries:
            return None
        for entry in entries[level]:
            if "source" in entry:
                self.test_source = self.resolve_template(entry["source"])
            tocheck = "name"
            val = name
            if level == "testplans":
                assert ("filename" in entry) ^ ("name" in entry), (
                    "Testplan entry cannot have both filename and name provided"
                )
                tocheck = "filename" if "filename" in entry else "name"
                val = self.testplan_file if "filename" in entry else "name"
            matched = self.template_match(entry[tocheck], val)
            if not matched:
                continue
            self.regex_groups[level[:-1]] = list(matched.groups())
            if self.resource_type in entry:
                self.result = self.resolve_template(entry[self.resource_type])
            if len(levels) > 1:
                self.scan_tree(entry, names[1:], levels[1:])

    def get(
        self,
        resource_type: str,
        testplan_file: Union[str, Path],
        testplan: str,
        testpoint: Optional[str] = None,
        test: Optional[str] = None,
    ):
        self.prepare(resource_type, testplan, testpoint, test, testplan_file)
        assert self.resource_type not in TESTPLAN_KEYWORDS, (
            f"resource_type cannot be one of {TESTPLAN_KEYWORDS}"
        )
        self.scan_tree(
            self.testplan_rules,
            names=[testplan, testpoint, test],
            levels=TESTPLAN_LEVELS,
        )
        return self.result
