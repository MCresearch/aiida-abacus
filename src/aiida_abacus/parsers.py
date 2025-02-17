"""
Parsers provided by aiida_abacus.

Register parsers via the "aiida.parsers" entry point in setup.json.
"""

from aiida import orm
from aiida.common import exceptions
from aiida.engine import ExitCode
from aiida.orm import SinglefileData, Str
from aiida.parsers.parser import Parser
from aiida.plugins import CalculationFactory

import re
from pathlib import Path

AbacusCalculation = CalculationFactory("abacus.abacus")


class AbacusParser(Parser):
    """
    Parser class for parsing output of calculation.
    """

    def __init__(self, node):
        """
        Initialize Parser instance

        Checks that the ProcessNode being passed was produced by a AbacusCalculation.

        :param node: ProcessNode of calculation
        :param type node: :class:`aiida.orm.nodes.process.process.ProcessNode`
        """
        super().__init__(node)
        if not issubclass(node.process_class, AbacusCalculation):
            raise exceptions.ParsingError("Can only parse AbacusCalculation")

    def parse(self, **kwargs):
        """
        Parse outputs, store results in database.

        :returns: an exit code, if parsing fails (or nothing if parsing succeeds)
        """
        output_folder = self.retrieved
        # print(AbacusCalculation.get_default_calc_paths())
        running_scf_log_filename = Path("OUT.aiida") / "running_scf.log"
        
        # Check that folder content is as expected
        files_retrieved = self.retrieved.list_object_names()
        print("files_retrieved", files_retrieved)
        # check that 'OUT.aiida' folder is present
        files_expected = ["OUT.aiida", "abacus_output"]
        if not set(files_expected) <= set(files_retrieved):
            self.logger.error(f"Found files '{files_retrieved}', expected to find '{files_expected}'")
            return self.exit_codes.ERROR_MISSING_OUTPUT_FILES
        # files_expected = [output_filename]
        # Note: set(A) <= set(B) checks whether A is a subset of B
        # if not set(files_expected) <= set(files_retrieved):
        #     self.logger.error(f"Found files '{files_retrieved}', expected to find '{files_expected}'")
        #     return self.exit_codes.ERROR_MISSING_OUTPUT_FILES

        # add output file
        with output_folder.open(running_scf_log_filename, "r") as handle:
            output = handle.read()
        # print("output", output)
        self.logger.info(f"Parsing '{running_scf_log_filename}'")
        # with self.retrieved.open(output_filename, "rb") as handle:
        #     output_node = SinglefileData(file=handle)

        # patter to search for total energy in output file
        # look for " !FINAL_ETOT_IS xxx eV"
        pattern = r"!FINAL_ETOT_IS\s+(-?\d+\.\d+)\s+eV"
        # search for pattern in output file
        self.logger.info(f"Searching for pattern '{pattern}'")
        self.logger.info(f"Contents of file: {output}")

        final_energy_total = self._parse_energy(output, pattern)

        # parse miscellaneaous "misc"
        # update misc_node with final_energy_total
        # valid_type=orm.Dict

        out_dict = {"final_energy_total": final_energy_total}
        print("out_dict", out_dict)
        misc_node = orm.Dict(dict=out_dict)
        self.out("misc", misc_node)

        # raw abacus_output content str
        abacus_output_filename = "abacus_output"
        with self.retrieved.open(abacus_output_filename, "rb") as handle:
            abacus_output_node = Str(handle)
        self.out("abacus_output", abacus_output_node)
        
        # Scheduler part
        # std output and err stream content of scheduler
        # scheduler_stdout_filename = self.node.get_option("scheduler_stdout")
        # with self.retrieved.open(scheduler_stdout_filename, "rb") as handle:
        #     scheduler_stdout_node = Str(handle)
        # self.out("scheduler_stdout", scheduler_stdout_node)

        # scheduler_stderr_filename = self.node.get_option("scheduler_stderr")
        # with self.retrieved.open(scheduler_stderr_filename, "rb") as handle:
        #     scheduler_stderr_node = Str(handle)
        # self.out("scheduler_stderr", scheduler_stderr_node)


        return ExitCode(0)
    
    def _parse_energy(self, output, pattern):
        """
        Parse energy from output file.

        :param output: output file content
        :param pattern: regular expression pattern to search for
        :returns: energy value
        """
        pattern_compile = re.compile(pattern)
        res = pattern_compile.search(output)
        if res:
            energy = float(res.group(1))
        else:
            energy = None
        return energy
