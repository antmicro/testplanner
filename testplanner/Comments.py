# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

r"""Utility for reading and applying comments from comments.hjson"""

import logging
import re
import sys
from pathlib import PurePath

from testplanner.Testplan import Testplan


class Comments:
    def __init__(self, comments_file):
        """Constructs the commenting utility."""
        # TODO: extract HJSON parsing to some common module
        self.comments = Testplan._parse_hjson(comments_file)
        self.link_regexes = self.comments.get("link_regexes", [])
        del self.comments["link_regexes"]
        self.estimations = {}
        self.estimations_unit = self.comments.get("estimations_unit", "")
        self.estimations_regex = re.compile(r"(.*)\[([0-9]+)\]$")

        try:
            self.combined_link_regex = "|".join(r["regex"] for r in self.link_regexes)
            for r in self.link_regexes:
                r["regex"] = re.compile(r["regex"])
            self.combined_link_regex = re.compile(self.combined_link_regex)
        except re.error:
            print(f"Error: regex '{r['regex']}' in comment file is invalid.")
            sys.exit(1)

    def comment_summary(self):
        """Returns HTML comment for the top-level summary."""
        comment = self.comments.get("summary_comment", None)
        if comment:
            return f'<p class="comment">{self.htmlify(comment)}</p>'
        return ""

    def comment_testplan(self, filename):
        """Comments a testplan given its filename and initial displayed text."""
        comment = self.comments.get(PurePath(filename).stem, {}).get(
            "general_comment", None
        )
        if comment:
            return f'<p class="comment">{self.htmlify(comment)}</p>'
        return ""

    def comment_stage(self, filename, stage):
        """Returns HTML comment for a stage given the testplan filename, stage name, and initial displayed stage text."""
        comment = (
            self.comments.get(PurePath(filename).stem, {})
            .get("stage_comments", {})
            .get(stage, None)
        )
        if comment:
            return f'<br/><span class="comment">{self.htmlify(comment)}</span>'
        return ""

    def comment_testpoint(self, filename, testpoint):
        """Returns HTML comment for a testpoint given the testplan filename, testpoint name, and testpoint description."""
        comment = None
        if self.comments:
            data = (
                self.comments.get(PurePath(filename).stem, {})
                .get("testpoint_comments", {})
                .get(testpoint, "")
            )
            matched = self.estimations_regex.match(data)
            if matched:
                comment = matched.group(1)
                stem = PurePath(filename).stem
                if stem not in self.estimations:
                    self.estimations[stem] = {}
                if "testpoints" not in self.estimations[stem]:
                    self.estimations[stem]["testpoints"] = {}
                self.estimations[stem]["testpoints"][testpoint] = int(matched.group(2))
            else:
                comment = data
        if comment:
            return f'<br/><span class="comment">{self.htmlify(comment)}</span>'
        return ""

    def _check_dict(self, firstkey, midkey=None, lastkey=None):
        if firstkey not in self.estimations:
            return False
        if midkey and midkey not in self.estimations[firstkey]:
            return False
        if lastkey and (
            not midkey or lastkey not in self.estimations[firstkey][midkey]
        ):
            return False
        return True

    def get_testpoint_estimation(self, filename, testpoint):
        plan_name = PurePath(filename).stem
        if self._check_dict(plan_name, "testpoints", testpoint):
            return f"""<br/><span class="comment">{
                self.htmlify(
                    (
                        "Estimate: "
                        + str(self.estimations[plan_name]["testpoints"][testpoint])
                        + " "
                        + self.estimations_unit
                    ).rstrip()
                )
            }</span>"""
        return ""

    def get_test_estimation(self, filename, test):
        plan_name = PurePath(filename).stem
        if self._check_dict(plan_name, "tests", test):
            return f"""<br/><span class="comment">{
                self.htmlify(
                    (
                        "Estimate: "
                        + str(self.estimations[plan_name]["tests"][test])
                        + " "
                        + self.estimations_unit
                    ).rstrip()
                )
            }</span>"""
        return ""

    def get_estimation_totals(self, filename):
        plan_name = PurePath(filename).stem
        if self._check_dict(plan_name):
            test_total = 0
            testpoint_total = 0
            if self._check_dict(plan_name, "tests"):
                for value in self.estimations[plan_name]["tests"].values():
                    test_total += value
            if self._check_dict(plan_name, "testpoints"):
                for value in self.estimations[plan_name]["testpoints"].values():
                    testpoint_total += value
            total_str = f"Total estimate: {test_total + testpoint_total} {self.estimations_unit}".rstrip()
            return f'<p class="comment">{self.htmlify(total_str)}</p>'
        return ""

    def comment_test(self, filename, test):
        """
        Returns HTML comment for a test given the testplan filename,
        test name, and initial displayed test text.
        """
        data = (
            self.comments.get(PurePath(filename).stem, {})
            .get("test_comments", {})
            .get(test, "")
        )
        matched = self.estimations_regex.match(data)
        if matched:
            comment = matched.group(1)
            stem = PurePath(filename).stem
            if stem not in self.estimations:
                self.estimations[stem] = {}
            if "tests" not in self.estimations[stem]:
                self.estimations[stem]["tests"] = {}
            self.estimations[stem]["tests"][test] = int(matched.group(2))
        else:
            comment = data
        if comment:
            return f'<br/><span class="comment">{self.htmlify(comment)}</span>'
        return ""

    def htmlify(self, text):
        """Converts newlines to <br/> and linkifies text for HTML."""
        text = self.linkify(text)
        text = text.replace("\n", "<br/>")
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
