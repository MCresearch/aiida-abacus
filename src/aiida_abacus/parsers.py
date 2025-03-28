"""
Parsers provided by aiida_abacus.

Register parsers via the "aiida.parsers" entry point in setup.json.
"""

import re
from typing import TextIO

from aiida import orm
from aiida.common import exceptions
from aiida.parsers.parser import Parser
from aiida.plugins import CalculationFactory
from ase.io.cif import read_cif

from .common import make_retrieve_list

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
        settings = {} if "settings" not in self.node.inputs else self.node.inputs.settings
        expected_files = make_retrieve_list(self.node.inputs.parameters, settings, AbacusCalculation._OUTPUT_SUFFIX)
        # Add the STDOUT diversion
        expected_files.append(AbacusCalculation._ABACUS_OUTPUT)
        run_type = self.node.inputs.parameters["input"].get("calculation", "scf")

        # Check if the files are retrieved
        missing = []
        for name in expected_files:
            try:
                output_folder.get_object(name)
            except FileNotFoundError:
                missing.append(name)

        if missing:
            self.logger.warning(f"The following expected files are missing: {missing}")

        # Parse the calculation task output file
        main_log = next(filter(lambda x: "running_" in x, expected_files))
        misc_results = {}
        with output_folder.open(main_log, "r") as fhandle:
            parser = AbacusRawParser(fhandle)
            misc_results.update(parser.parse())
        breakpoint()
        misc_node = orm.Dict(dict=misc_results)

        # Parse the structure output
        fname = next(filter(lambda x: "STRU.cif" in x, expected_files))
        # TODO: there could be other types that should have a output structure
        if run_type in ["relax", "vc-relax"]:
            with output_folder.open(fname, "r") as fhandle:
                atoms = read_cif(fhandle)
                self.out("structure", orm.StructureData(ase=atoms))

        # Parse the calculation raw parameters
        if "settings" in self.node.inputs and self.node.inputs.settings.get("include_internal_parameters", False):
            fname = next(filter(lambda x: x.endswith("INPUT"), expected_files))
            with output_folder.open(fname, "r") as fhandle:
                self.out("internal_parameters", read_internal_parameters(fhandle))

        # Parse the KPOINTS actually used
        if "settings" in self.node.inputs and self.node.inputs.settings.get("include_kpoints", False):
            fname = next(filter(lambda x: x.endswith("kpoints"), expected_files))
            with output_folder.open(fname, "r") as fhandle:
                coords, weights = read_kpoints_output_file(fhandle)
                node = orm.KpointsData()
                node.set_kpoints(coords, weights=weights)
                # Set the cell based on the  INPUT structure
                node.set_cell_from_structure(self.node.inputs.structure)
            self.out("kpoints", node)

        # Define the output nodes
        self.out("misc", misc_node)


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
        pattern = re.compile(
            r"---------+\n TOTAL-(FORCE|STRESS) \(([a-zA-Z/]+)\) *\n------+\n(.*?)\n--------+", flags=re.DOTALL
        )
        # First, process all blocks
        all_blocks = []
        for match in re.findall(pattern, self.content):
            block_type = match[0]
            block_unit = match[1]
            block_content = match[2]
            lines = [line.strip() for line in block_content.split("\n")]
            all_blocks.append((block_type, block_unit, lines))

        all_forces = []
        all_pressure = []
        # Process the blocks one by one, additional block type can be supported by adding more elifs.
        for block_type, block_unit, lines in all_blocks:
            if block_type == "FORCE":
                forces = []
                for line in lines:
                    tokens = line.split()
                    forces.append([float(token) for token in tokens[1:]])
                    all_forces.append(forces)
                self.results["force_unit"] = block_unit

            if block_type == "STRESS":
                stress = []
                for line in lines:
                    stress.append([float(token) for token in line.split()])
                    all_pressure.append(stress)
                self.results["stress_unit"] = block_unit
        self.results["all_forces"] = all_forces
        self.results["all_pressure"] = all_pressure
        self.results["final_forces"] = all_forces[-1] if all_forces else None
        self.results["final_pressure"] = all_pressure[-1] if all_pressure else None

    def parse(self) -> dict:
        """
        Parse ABACUS output file.

        :returns: parsed results as a dictionary
        """
        self.parse_blocks()
        # Parse the lines one-by-one for general information of the calculation
        for line in self.content.split("\n"):
            if "TOTAL-PRESSURE" in line:
                self.results["pressure"] = line.strip().split()[1]
                self.results["pressure_unit"] = line.strip().split()[2]
                if "all_pressure" not in self.results:
                    self.results["all_pressure"] = []
                self.results["all_pressure"].append(self.results["pressure"])
            if "!FINAL_ETOT_IS" in line:
                self.results["total_energy"] = line.strip().split()[1]

        self.is_parsed = True
        return self.results


def read_internal_parameters(fhandle: TextIO):
    """Read the internal parameters"""
    fhandle.readline()
    out_dict = {}
    for line in fhandle:
        if line.startswith("#"):
            continue
        # Remove the trialing # comments
        match = re.match(r"^(.+) #.*$", line)
        if match:
            tokens = match.group(1).split()
            out_dict[tokens[0]] = tokens[1]
    return out_dict


def read_kpoints_output_file(fhandle: TextIO):
    """Read the output kpoints file"""

    line = fhandle.readline()
    nkpts = int(line.strip().split()[-1])
    assert fhandle.readline().startswith("K-POINTS DIRECT COORDINATES")
    fhandle.readline()
    points = []
    weights = []
    for i in range(nkpts):
        tokens = fhandle.readline().strip().split()
        points.append([float(tokens[i]) for i in range(1, 4)])
        weights.append(float(tokens[4]))

    return points, weights
