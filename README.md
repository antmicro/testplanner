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

## Examples

To generate verification plan in Markdown, provide HJSON like in the following example:
```bash
testplanner verification_plan.hjson
```

Additionally you can choose output directory explicitly by providing `-o` flag:
```bash
testplanner verification_plan.hjson -o generated
```
