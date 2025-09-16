# Copyright (c) 2025 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

r"""Utility for reading and applying comments from comments.hjson"""

import logging
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

        # Compile regexes
        import re

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
            comment = (
                self.comments.get(PurePath(filename).stem, {})
                .get("testpoint_comments", {})
                .get(testpoint, None)
            )
        if comment:
            return f'<br/><span class="comment">{self.htmlify(comment)}</span>'
        return ""

    def comment_test(self, filename, test):
        """Returns HTML comment for a test given the testplan filename, test name, and initial displayed test text."""
        comment = (
            self.comments.get(PurePath(filename).stem, {})
            .get("test_comments", {})
            .get(test, None)
        )
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
