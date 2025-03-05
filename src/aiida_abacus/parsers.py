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
        calc_paths = AbacusCalculation.get_default_calc_paths()
        
        # Check that folder content is as expected
        files_retrieved = self.retrieved.list_object_names()
        print("files_retrieved", files_retrieved)
        
        # Note: set(A) <= set(B) checks whether A is a subset of B
        # check that the following results are present
        # OUTPUT_SUBFOLDER - 'OUT.aiida' folder: contains the output files of ABACUS calculation
        #       'OUT.aiida/running_scf.log': contains the output of the calculation
        # ABACUS_OUTPUT - redirected stdout of the calculation, abacus_output
        files_expected = [
            calc_paths["OUTPUT_SUBFOLDER"], # 'OUT.aiida' folder
            calc_paths["ABACUS_OUTPUT"] # abacus_output file
            ]
        if not set(files_expected) <= set(files_retrieved):
            self.logger.error(f"Found files '{files_retrieved}', expected to find '{files_expected}'")
            return self.exit_codes.ERROR_MISSING_OUTPUT_FILES
        

        # add output file
        running_scf_log_filename = Path(calc_paths["OUTPUT_SUBFOLDER"]) / "running_scf.log"
        with output_folder.open(running_scf_log_filename, "r") as handle:
            output = handle.read()

        self.logger.info(f"Parsing '{running_scf_log_filename}'")


        # patter to search for total energy in output file
        # look for final total energy" !FINAL_ETOT_IS xxx eV"
        pattern = r"!FINAL_ETOT_IS\s+(-?\d+\.\d+)\s+eV"
        # search for pattern in output file
        self.logger.info(f"Searching for pattern '{pattern}'")
        self.logger.info(f"Contents of file: {output}")

        final_energy_total = self._parse_re_pattern(output, pattern)

        # parse miscellaneaous "misc"
        # valid_type=orm.Dict

        out_dict = {"final_energy_total": final_energy_total}
        print("output misc dict:", out_dict)
        misc_node = orm.Dict(dict=out_dict)
        self.out("misc", misc_node)

        return ExitCode(0)
    
    def _parse_re_pattern(self, output, pattern):
        """
        Parse pattern from output file.

        :param output: output file content
        :param pattern: regular expression pattern to search for
        :returns: extracted value
        """
        pattern_compile = re.compile(pattern)
        res = pattern_compile.search(output)
        if res:
            value = float(res.group(1))
        else:
            value = None
        return value


class AbacusRawParser:
    """
    A parser to process abacus output files (running_xxx.log)
    """


    def __init__(self, fhandle):
        """A parser for the ABACUS output file."""
        self.content = fhandle.read()
        self.results = {}
        self.is_parsed = False

    def parse_blocks(self) -> None:
        """
        Parse blocks from output file.
        """
        # Re pattern to match the block name, unit and content.
        pattern =  re.compile(r'---------+\n TOTAL-(FORCE|STRESS) \(([a-zA-Z/]+)\) *\n------+\n(.*?)\n--------+',
                               flags=re.DOTALL)
        # First, process all blocks
        all_blocks = []
        for match in re.findall(pattern, self.content):
            block_type = match[0]
            block_unit = match[1]
            block_content = match[2]
            lines = [line.strip() for line in block_content.split('\n')]
            all_blocks.append((block_type, block_unit, lines))

        all_forces = []
        all_pressure = []
        # Process the blocks one by one, additional block type can be supported by adding more elifs.
        for block_type, block_unit, lines in all_blocks:
            if block_type == 'FORCE':
                forces = []
                for line in lines:
                    tokens = line.split()
                    forces.append([float(token) for token in tokens[1:]])
                    all_forces.append(forces)
                self.results['force_unit'] = block_unit

            if block_type == 'STRESS':
                stress = []
                for line in lines:
                    stress.append([float(token) for token in line.split()])
                    all_pressure.append(stress)
                self.results['stress_unit'] = block_unit
        self.results['all_forces'] = all_forces
        self.results['all_pressure'] = all_pressure
        self.results['final_forces'] = all_forces[-1] if all_forces else None
        self.results['final_pressure'] = all_pressure[-1] if all_pressure else None

    def parse(self) -> dict:
        """
        Parse ABACUS output file.

        :returns: parsed results as a dictionary
        """
        self.parse_blocks()
        # Parse the lines one-by-one for general information of the calculation
        for line in self.content.split('\n'):
            if 'TOTAL-PRESSURE' in line:
                self.results['pressure'] = line.strip().split()[1]
                self.results['pressure_unit'] = line.strip().split()[2]
                if 'all_pressure' not in self.results:
                    self.results['all_pressure'] = []
                self.results['all_pressure'].append(self.results['pressure'])
            if '!FINAL_ETOT_IS' in line:
                self.results['total_energy'] = line.strip().split()[1]

        self.is_parsed = True
        return self.results
