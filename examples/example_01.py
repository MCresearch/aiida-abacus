#!/usr/bin/env python
"""Run a test calculation on localhost.

Usage: ./example_01.py
"""

from os import path

import click
from aiida import cmdline, engine
from aiida.plugins import CalculationFactory, DataFactory
from aiida_abacus import helpers

INPUT_DIR = path.join(path.dirname(path.realpath(__file__)), "input_files")


def test_run(abacus_code):
    """Run a calculation on the localhost computer.

    Uses test helpers to create AiiDA Code on the fly.
    """
    if not abacus_code:
        # get code
        computer = helpers.get_computer()
        abacus_code = helpers.get_code(entry_point="abacus", computer=computer)

    # Prepare input parameters
    diff_parameters = DataFactory("abacus")
    parameters = diff_parameters({"ignore-case": True})

    singlefile_data = DataFactory("core.singlefile")
    file1 = singlefile_data(file=path.join(INPUT_DIR, "file1.txt"))
    file2 = singlefile_data(file=path.join(INPUT_DIR, "file2.txt"))

    # set up calculation
    inputs = {
        "code": abacus_code,
        "parameters": parameters,
        "file1": file1,
        "file2": file2,
        "metadata": {
            "description": "Test job submission with the aiida_abacus plugin",
        },
    }

    # Note: in order to submit your calculation to the aiida daemon, do:
    # from aiida.engine import submit
    # future = submit(CalculationFactory('abacus'), **inputs)
    result = engine.run(CalculationFactory("abacus"), **inputs)

    computed_diff = result["abacus"].get_content()
    print(f"Computed diff between files: \n{computed_diff}")


@click.command()
@cmdline.utils.decorators.with_dbenv()
@cmdline.params.options.CODE()
def cli(code):
    """Run example.

    Example usage: $ ./example_01.py --code diff@localhost

    Alternative (creates diff@localhost-test code): $ ./example_01.py

    Help: $ ./example_01.py --help
    """
    test_run(code)


if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
