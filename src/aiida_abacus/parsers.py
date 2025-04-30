"""
Parsers provided by aiida_abacus.

Register parsers via the "aiida.parsers" entry point in setup.json.
"""

import re
from pathlib import Path
from typing import List, TextIO

import numpy as np
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
        misc_node = orm.Dict(dict=misc_results)

        # Parse the structure output
        fname = next(filter(lambda x: "STRU.cif" in x, expected_files))
        # TODO: there could be other types that should have a output structure
        if run_type in ["relax", "cell-relax", "md"]:
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
        if not hasattr(fhandle, 'read'):
            self.content = Path(fhandle).read_text()
        else:
            self.content = fhandle.read()
        self.lines = self.content.split("\n")
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
        all_stress = []
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
                    all_stress.append(stress)
                self.results["stress_unit"] = block_unit
        self.results["all_forces"] = all_forces
        self.results["all_stress"] = all_stress
        self.results["final_forces"] = all_forces[-1] if all_forces else None
        self.results["final_stress"] = all_stress[-1] if all_stress else None

    def parse(self) -> dict:
        """
        Parse ABACUS output file.

        :returns: parsed results as a dictionary
        """
        self.parse_blocks()
        # Parse the lines one-by-one for general information of the calculation
        for line in self.content.split("\n"):
            if "TOTAL-stress" in line:
                self.results["stress"] = line.strip().split()[1]
                self.results["stress_unit"] = line.strip().split()[2]
                if "all_stress" not in self.results:
                    self.results["all_stress"] = []
                self.results["all_stress"].append(self.results["stress"])
                continue
            elif "!FINAL_ETOT_IS" in line:
                self.results["total_energy"] = line.strip().split()[1]
            elif "NBANDS =" in line:
                self.results["number_of_bands"] = int(line.strip().split()[-1])

        self.is_parsed = True
        return self.results

    def parse_kpoints(self):
        """Parse the kpoints involved in the calculation"""

        kdirect = BlockParser(
            self.lines, re.compile(r"^K-POINTS (DIRECT) COORDINATES"), offset=2, types=[
                int, float, float, float, float
            ]
        ).parse()
        kcart = BlockParser(
            self.lines, re.compile(r"^K-POINTS (CARTESIAN) COORDINATES"), offset=2, types=[
                int, float, float, float, float
            ]
        ).parse()
        if len(kdirect) == 0:
            raise ValueError("No kpoints data found")
        if len(kdirect) > 2:
            raise ValueError("Multiple sets of kpoints data found")
        # Take the last set of kpoint reported
        # Return an array made of kpoint coordinates and weight, remove the kpoint index
        return np.array(kdirect[-1][1])[:, 1:], np.array(kcart[-1][1])[:, 1:]


    def parse_eigenvalues(self):
        """Parse the eigenvalues"""

        nspins = int(re.search(r"NSPIN == (\d)", self.content).group(1))
        parser = BlockParser(self.lines,
                            re.compile(r"^ (\d+)/(\d+) kpoint \(Cartesian\) *= *([-0-9.]+) ([-0-9.]+) ([-0-9.]+)"),
                            offset=1, types=[int, float, float],
                            )
        blocks = parser.parse()
        eigenvalues = {}
        occupations = {}
        ntot = len(blocks)
        nkpts = ntot // nspins
        assert ntot % nspins == 0
        kpt_cart = np.zeros((nkpts, 3))
        # Process all blocks
        for i, (key, block) in enumerate(blocks):
            ikpt = int(key[0])
            # Sanity check
            if i == 0:
                nkpt_tot = int(key[1])
                assert nkpt_tot == nkpts, "Mismatch in kpont number possible unsupported spin type"
            kpt_cart[ikpt-1, 0] = float(key[2])
            kpt_cart[ikpt-1, 1] = float(key[3])
            kpt_cart[ikpt-1, 2] = float(key[4])
            # Check which spin we are with
            ispin = i // nkpts
            if ispin not in eigenvalues:
                eigenvalues[ispin] = {}
                occupations[ispin] = {}
            occ = [entry[2] for entry in block]
            energy = [entry[1] for entry in block]
            eigenvalues[ispin][ikpt] = np.array(energy)
            occupations[ispin][ikpt] = np.array(occ)
        # Construct overall block
        nkpts = len(eigenvalues[1])
        nspins = len(eigenvalues)
        assert max(eigenvalues[1].keys()) == nkpts
        eigen_arrays = []
        occ_arrays = []
        for spin in range(nspins):
            eigen_arrays.append(np.stack([eigenvalues[spin][i] for i in range(1, nkpts+1)], axis=0))
            occ_arrays.append(np.stack([occupations[spin][i] for i in range(1, nkpts+1)], axis=0))
        return np.stack(eigen_arrays, axis=0), np.stack(occ_arrays, axis=0), kpt_cart

class BlockParser:
    """Parser to extract blocks of data"""
    DEFAULT_END_CHAR = ['------', '++++++']
    def __init__(self, lines:List[str], key_re, offset=1, types=None, end_characters=None):
        """
        A parser to parse blocks of data by searching a title line

        HEADER
        XXXX
        ---------
        A 1 B 2 
        A 1 B 2 
        C 1 D 2 
        ---------

        :param lines: A list contains string of each line
        :param key_re: The regular expression to match the presence of the block
        :param offset: Offset from the header to the real data
        :param types: The types of the data for each line
        """
        self.lines = lines
        self.key_re = key_re
        self.types = types
        self.offset = offset
        self.blocks = []
        self.end_characters = [] if not end_characters else end_characters
        self.end_characters += self.DEFAULT_END_CHAR

    def parse(self):
        """Parse the data"""
        for i, line in enumerate(self.lines):
            m = self.key_re.match(line)
            # not matching a header line
            if m is None:
                continue
            # We have found a matched group
            block_name = m.groups()
            block_tokens = []
            j = i + self.offset
            while j <= len(self.lines):
                this_line = self.lines[j].strip()
                # Break with empty line
                if not this_line:
                    break
                # Break with predefined sequence such as ---- or +++++
                if any(key in line for key in self.end_characters):
                    break
                tokens = self.lines[j].strip().split()
                block_tokens.append(tokens)
                j += 1
            self.blocks.append((block_name, block_tokens))

        if self.types is not None:
            self.blocks = self.convert_type()
        return self.blocks
    def convert_type(self):
        """Convert the match data to the correct type"""
        assert self.blocks
        converted = []
        for block_name, block_tokens in self.blocks:
            new_block = []
            for tokens in block_tokens:
                # Use the type constructors to convert the string data to the right type
                new_block.append([constructor(token) for constructor, token in zip(self.types, tokens)])
            converted.append([block_name, new_block])
        return converted









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
