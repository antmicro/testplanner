#!/bin/bash

cwd="$(dirname -- "${BASH_SOURCE[0]}")"
PROJ_ROOT=$(realpath "$cwd"/../)

testplanner "${PROJ_ROOT}"/tests/data/testplanner/foo_testplan.hjson \
    -o "${PROJ_ROOT}"/build

testplanner "${PROJ_ROOT}"/tests/data/testplanner/foo_testplan.hjson \
    -s "${PROJ_ROOT}"/tests/data/testplanner/foo_sim_results.hjson \
    -o "${PROJ_ROOT}"/build
