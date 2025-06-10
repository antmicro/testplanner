# testplanner

Copyright (c) 2019-2025 [lowRISC](https://lowrisc.org/)

Copyright (c) 2025 [Antmicro](https://www.antmicro.com)

A tool for parsing testplans written in Hjson format into a data structure that can be used for:
* Expanding the testplan inline within the DV document as a table;
* Annotating the simulation results with testplan entries for a document driven DV execution

It is based on [OpenTitan's testplanner tool](https://github.com/lowRISC/opentitan/blob/master/util/dvsim/testplanner.py), extracted as a standalone module.

## Installation

To install the tool, run:

```bash
pip3 install git+https://github.com/antmicro/testplanner.git
```

After this, the tool is available as `testplanner`, e.g.:

```bash
testplanner --help
```

The `--help` flag will provide all available flags for the tool.

## Testplan files

Testplan is defined in a single file in HJSON format.
It consists of a list of planned tests (`testpoints`) and coverage items (`covergroups`).

### Testpoint

Testpoint is an entry in the testplan representing a planned test or tests.

It consists of following fields:

* `name` - a name of the testpoint,
* `desc` - a description of the testpoint, see [Testpoint description](#testpoint-description) for more details
* `stage` - verification stage the testpoint is assigned to
* `tests` - list of tests implementing the testpoint
* `tags` - list of arbitrary tags used e.g. to represent specific conditions to run testpoint tests

### Covergroup

Covergroup is an entry in the testplan representing functional coverage plan for the design.

It consists of:

* `name` - name of the covergroup
* `desc` - description of the covergroup

## Testpoint description

While the testpoint description does not have a specific structure, it is recommended to define following sections in the documentation:

* Testbench - describes the architecture of the test itself,
* Intent - outlines the desired effect and area of coverage,
* Stimulus - enumerates the steps that are going to be taken to start and run the testbench, and describes the inputs to the test,
* Check - describes the tested output and final state in which the device under test should be in.

The description can look as follows:

## Testplan example

The following code represents a testplan named `Example tesplan` with single testpoint:

```
{
  "name":"Example testplan",
  "testpoints": [
    {
      "name": "Example testpoint",
      "desc": '''
              Testbench:
              * Two modules connected to each other output-to-input
              Intent:
              * Test to prove that the modules are stackable.

              Stimulus:
              * Input a clock signal to the clock input of both modules.
              * Test should feed the first module a randomized sequence of data.
                * Edge cases should be taken into consideration, eg. an empty data lane.

              Check:
              * The output of the first module should be checked for correctness of calculation.
              * The output of the second module should be checked for correctness of calculation based on the results from the first module.
              '''
      "stage": "tests",
      "tests": ["test1", "test2"],
      "tags": [""]
    }
  ]
}
```

## Including tests' results

Testplanner can parse results of tests and use them to generate summaries for testpoints and testplans, as well as associate tests and testpoints with their implementations.
It expects results to be in HJSON format, one file per testplan.

Each file with results consists of:

* `timestamp` - when tests were executed
* `test_results` - list of tests' results

Each entry in `test_results` consists of:

* `passing` - number of passed tests
* `total` - total number of tests
* `job_runtime` - how long did the execution of the test take
* `simulated_time` - how long did the test take in simulation time
* `name` - name of the test. It needs to match the name of the test in `tests` list in testpoints to properly associate the test's result with its definition in testplans.
* `file` (optional) - path to the implementation of the test
* `lineno` (optional) - line number within `file` where test is implemented

Test results can be provided with `-os` flag of `testplanner`.

## Examples

To generate verification plan in Markdown, provide HJSON like in the following example:

```bash
testplanner verification_plan.hjson
```

Additionally you can choose output directory explicitly by providing `-o` flag:

```bash
testplanner verification_plan.hjson -o generated
```

## Using cocotb tests' results in testplanner

[cocotb](https://www.cocotb.org/) provides results in XML format conforming to xUnit definition of tests' results.
It is possible to convert XML files from [cocotb](https://www.cocotb.org/) using `cocotbxml-to-hjson` tool.

It can be executed like so:

```
cocotbxml-to-hjson -i <path-to-cocotb-xml-1> <path-to-cocotb-xml-2> ... -t <testplan-hjson-1> <testplan-hjson-2> <testplan-hjson-3> ... -o <output-dir>
```

Where:

* `-i <path-to-cocotb-xml-1> <path-to-cocotb-xml-2>` - list of XML results from cocotb (does not need to match list of testplans)
* `-t <testplan-hjson-1> <testplan-hjson-2> <testplan-hjson-3>` - list of testplans in the project
* `-o <output-dir>` - path to the directory where output HJSON files associated to testplans will be created

For more options run `cocotbxml-to-hjson --help`.

## Interlinking tests, documentations and sources for tests

Testplanner:

* Creates documentations for planned tests
* Parses results of tests and creates a summary of testplans' progress
* Creates general overview of testplans
* Can trace implementations of tests

It is possible to interconnect all of the above for easier exploration using `--testplan-file-map <file-map-yaml>` flag in `testplanner`.
This flag takes a YAML file with regex-like rules allowing to associate tests to their sources, documentations, and more.

The file passed with `--testplan-file-map` is managed by [ResourceMap class](testplanner/resource_map.py) (which can be also used in other Python scripts using testplanner to obtain testplan-related files).

The YAML is required to have `testplans` key in the root of the YAML (other fields are ignored, which can be used in third-party tools).
The `testplans` is a list of rules and associated assets, such as documentation links, sources, logs and more.

Rules are in form of regex rules that may be matched against names of testplans/testpoints/tests, or testplans' file names.
At each level (testplan, testpoint or test) it is possible to assign a specific resource (`source`, `docs_html`, custom resource).

`testplans` consists of entries with:

* `name` - regex rule for testplan's `name` field
* `filename` - regex rule for testplan's
* optional resources specific to testplan, e.g. `source`
* `testpoints` - list of testpoint-specific entries

`testpoints` is an array of entries associated with testplans' testpoints:

* `name` - regex rule for testpoint's `name` field
* optional resources specific to testpoint, e.g. `source`
* `tests` - list of test-specific entries

`tests` is an array of entries associated with testpoints' tests:

* `name` - regex rule for test's `name` field
* resources specific to test, e.g. `source`

Resources supported by testplanner are:

* `source` - path to the implementation of tests
* `docs_html` - path or URL to the documentation regarding testplan, testpoint, test

It is possible to add other resources, which can be used by tools associating testplanner.

The first matching entry in file map will be used.

The example of file map looks as follows:

```yaml
testplans:
  - filename: ".*"
    docs_html: "design-verification/{{testplan_file}}.html"
  - filename: ".*testplan_another_module.hjson"
    testpoints:
      - name: ".*"
        tests:
          - name: ".*"
            source: "**/tb_another_module_top.sv"
            vcs_logs: "**/tb_another_module_top_{{test}}.hjson"
  - name: "^.*$"
    testpoints:
      - name: "^.*$"
        tests:
          - name: "^reg_(.*)$"
            source: "**/{{testplan}}/reg/test_{{regex_groups['test'][1]}}.sv"
          - name: "^.*$"
            source: "**/{{testplan}}/test_{{test}}.sv"
```

Values for each resource (here `docs_html` and `source`) are template-based strings that can access special variables by using `{{variable_name}}` syntax.

Available variables are:

* `testplan` - name of the testplan
* `testpoint` - name of the testpoint
* `test` - name of the test
* `testplan_file` - path to the testplan file
* `test_source` - special access to the value of the `source` resource, if defined earlier
* `regex_groups` - a dictionary providing access to arrays with regex groups defined for current `testplan`, `testpoint`, `test`.

For example, for `reg_reset_check` test name in the `sample_testplan` testplan, the `source` resource will be evaluated to `**/sample_testplan/reg/test_reset_check.sv`.
For `smoke`, it will evaluate to `**/sample_testplan/test_smoke.sv`.

### Providing links to sources

The `source` field allows to define the glob-like search for test implementation.
It can be defined on testplan, testpoint and test level.

**NOTE:** If the results of tests provide coordinates to the test (`filename` and `lineno`), they override path provided here.
It is to allow introducing more precise location of test implementation coming from tools like `cocotb`.

**NOTE:** In documentation and simulation results, it is crucial to extinguish implemented tests from unimplemented tests.
To address that, the resource mapping for individual tests works only if the resource is given at `tests` level.

To create a full URL path to the source, `testplanner` tool needs `--source-url-prefix` flag with URL base.

### Providing links to documentation

For testplans, links to relevant documentation can be defined with `docs_html`.
The generated string acts as a URL suffix.
The prefix for the URL can be provided with `testplanner` `--docs-url-prefix` flag.
