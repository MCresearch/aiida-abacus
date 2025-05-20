import re
from logging import getLogger
from pathlib import Path
from typing import List

import numpy as np

logger = getLogger(__name__)


class BaseRawParser:
    def __init__(self, fhandle):
        """A parser for the ABACUS output file."""
        if not hasattr(fhandle, "read"):
            self.content = Path(fhandle).read_text()
        else:
            self.content = fhandle.read()
        self.lines = self.content.split("\n")


class AbacusRawParser(BaseRawParser):
    """
    A parser to process abacus output files (running_xxx.log)
    """

    def __init__(self, fhandle):
        """A parser for the ABACUS output file."""
        super().__init__(fhandle)
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
        """
        Parse the kpoints involved in the calculation

        :return: A tuple of kpoints in direct and cartesian coordinates
        """

        kdirect = BlockParser(
            self.lines, re.compile(r"^K-POINTS (DIRECT) COORDINATES"), offset=2, types=[int, float, float, float, float]
        ).parse()
        kcart = BlockParser(
            self.lines,
            re.compile(r"^K-POINTS (CARTESIAN) COORDINATES"),
            offset=2,
            types=[int, float, float, float, float],
        ).parse()
        if len(kdirect) == 0:
            raise ValueError("No kpoints data found")
        if len(kdirect) > 2:
            raise ValueError("Multiple sets of kpoints data found")
        # Take the last set of kpoint reported
        # Return an array made of kpoint coordinates and weight, remove the kpoint index
        return np.array(kdirect[-1][1])[:, 1:], np.array(kcart[-1][1])[:, 1:]

    def parse_eigenvalues(self):
        """
        Parse the eigenvalues
        :return: A tuple of eigenvalues and occupations and k-points (in cartesian coordinates)
        """

        nspins = int(re.search(r"NSPIN == (\d)", self.content).group(1))
        nkthis_procs = int(re.search(r"k-point number in this process = (\d+)", self.content).group(1))
        parser = BlockParser(
            self.lines,
            re.compile(r"^ (\d+)/(\d+) kpoint \(Cartesian\) *= *([-0-9.]+) ([-0-9.]+) ([-0-9.]+)"),
            offset=1,
            types=[int, float, float],
        )
        blocks = parser.parse()
        eigenvalues = {}
        occupations = {}
        ntot = len(blocks)
        nkpts = ntot // nspins
        # NOTE: Abacus only report the kpoint on the head MPI process!
        # TODO: Raise a PR to the developers to include all kpoints in the log file.
        if nkpts != nkthis_procs:
            logger.wanning("The number of kpoint is (), but only () on this proc")
        assert ntot % nspins == 0
        kpt_cart = np.zeros((nkpts, 3))
        # Process all blocks
        for i, (key, block) in enumerate(blocks):
            ikpt = int(key[0])
            # Sanity check
            if i == 0:
                nkpt_tot = int(key[1])
                assert nkpt_tot == nkpts, "Mismatch in kpont number possible unsupported spin type"
            kpt_cart[ikpt - 1, 0] = float(key[2])
            kpt_cart[ikpt - 1, 1] = float(key[3])
            kpt_cart[ikpt - 1, 2] = float(key[4])
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
        nkpts = len(eigenvalues[0])
        nspins = len(eigenvalues)
        assert max(eigenvalues[0].keys()) == nkpts
        eigen_arrays = []
        occ_arrays = []
        for spin in range(nspins):
            eigen_arrays.append(np.stack([eigenvalues[spin][i] for i in range(1, nkpts + 1)], axis=0))
            occ_arrays.append(np.stack([occupations[spin][i] for i in range(1, nkpts + 1)], axis=0))
        return np.stack(eigen_arrays, axis=0), np.stack(occ_arrays, axis=0), kpt_cart


class BlockParser:
    """Parser to extract blocks of data"""

    DEFAULT_END_CHAR = ["------", "++++++"]

    def __init__(self, lines: List[str], key_re, offset=1, types=None, end_characters=None):
        """
        A parser to parse blocks of data by searching a title line
        Example:
            HEADER  <- header line used for matching
            XXXX       ^
            ---------  |
            A 1 B 2    | Data starts here so offset is 3
            A 1 B 2
            C 1 D 2
            ---------  <- data ends here so the end character is "-----" (default)

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


class BandsParser(BaseRawParser):
    """Parser to process the BNADS_XX.dat files"""

    def parse(self):
        """Parse the bands.dat file"""
        arrays = []
        for line in self.lines:
            if not line:
                continue
            arrays.append(np.fromstring(line, sep=" ", dtype=float))
        data = np.stack(arrays, axis=0)[:, 1:]
        kdist = data[:, 0]
        eigenvalues = data[:, 1:]
        return kdist, eigenvalues


class KpointsParser(BaseRawParser):
    """
    Parse the kpoints file in the suffix.out folder
    """

    def parse(self):
        """Read the output kpoints file"""

        line = self.lines[0]
        nkpts = int(line.strip().split()[-1])
        assert self.lines[1].startswith("K-POINTS DIRECT COORDINATES")
        points = []
        weights = []
        for i in range(nkpts):
            tokens = self.lines[i + 3].strip().split()
            points.append([float(tokens[i]) for i in range(1, 4)])
            weights.append(float(tokens[4]))
        return points, weights


class InternalParametersParser(BaseRawParser):
    """
    Parse the INPUT file in the suffix.out folder
    NOTE: This does not work for a general INPUT file
    """

    def parse(self):
        """Read the output internal parameters file"""
        out_dict = {}
        # Skip the first line
        for _line in self.lines[1:]:
            if _line.startswith("#"):
                continue
            line = _line.strip()
            if not line:
                continue
            # Remove the trialing # comments
            match = re.match(r"^(.+) *#.*$", line)
            if match:
                tokens = match.group(1).split(maxsplit=1)
            else:
                tokens = line.split(maxsplit=1)
            # Add potential null value
            if len(tokens) != 2:
                tokens.append("None")
            out_dict[tokens[0].strip()] = tokens[1].strip()
        return out_dict
