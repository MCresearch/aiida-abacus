import re
from logging import getLogger
from pathlib import Path
from typing import List

import numpy as np

logger = getLogger(__name__)


class BaseRawParser:
    def __init__(self, fhandle):
        """A parser for the ABACUS output file."""
        if hasattr(fhandle, "read"):
            self.content = fhandle.read()
        else:
            self.content = Path(fhandle).read_text()
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

    def parse_magnetism(self) -> None:
        """
        Parse the per-electronic-step ``total magnetism`` and ``absolute magnetism``
        values reported by ABACUS.

        The line format depends on the spin treatment:

        * ``nspin == 2`` (collinear) — single scalar after ``=``::

              total magnetism (Bohr mag/cell) = -3.13515e-06
           absolute magnetism (Bohr mag/cell) = 8.57839e-06

        * ``nspin == 4`` (non-collinear) — three tab-separated cartesian
          components for the total vector, single scalar for the absolute value::

              total magnetism (Bohr mag/cell)\t-1.89816e-16\t-2.03396e-18\t-5.64117e-05
             absolute magnetism (Bohr mag/cell) = 0.000798729

        Results are stored (in ``self.results``) under the keys
        ``magnetism`` (a dict with one ``total_magnetism`` and one
        ``absolute_magnetism`` list) and ``final_magnetism`` (a dict with
        the last reported entry for each key). For nspin=2 each element of
        ``magnetism['total_magnetism']`` is a ``float``; for nspin=4 each
        element is a list of three floats ``[mx, my, mz]``. The
        ``absolute_magnetism`` list always contains ``float`` values. When
        no magnetism lines are found both keys are set to ``None`` so the
        caller can distinguish "not reported" from "reported as zero".
        """
        # nspin=2: `... = <scalar>`
        total_scalar_re = re.compile(r"total magnetism \(Bohr mag/cell\)\s*=\s*([-+0-9.eE]+)")
        # nspin=4: `<header>\t<mx>\t<my>\t<mz>` (tab-separated, no '=')
        total_vector_re = re.compile(
            r"total magnetism \(Bohr mag/cell\)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)"
        )
        absolute_magnetism_re = re.compile(r"absolute magnetism \(Bohr mag/cell\)\s*=\s*([-+0-9.eE]+)")

        total_magnetism = []
        absolute_magnetism = []

        for line in self.lines:
            scalar_match = total_scalar_re.search(line)
            if scalar_match:
                total_magnetism.append(float(scalar_match.group(1)))
                continue
            vector_match = total_vector_re.search(line)
            if vector_match:
                total_magnetism.append(
                    [
                        float(vector_match.group(1)),
                        float(vector_match.group(2)),
                        float(vector_match.group(3)),
                    ]
                )
                continue
            abs_match = absolute_magnetism_re.search(line)
            if abs_match:
                absolute_magnetism.append(float(abs_match.group(1)))

        magnetism = None
        final_magnetism = None
        if total_magnetism or absolute_magnetism:
            magnetism = {
                "total_magnetism": total_magnetism,
                "absolute_magnetism": absolute_magnetism,
            }
            final_magnetism = {
                "total_magnetism": total_magnetism[-1] if total_magnetism else None,
                "absolute_magnetism": absolute_magnetism[-1] if absolute_magnetism else None,
            }

        self.results["magnetism"] = magnetism
        self.results["final_magnetism"] = final_magnetism

    def parse_total_time(self) -> None:
        """
        Parse the ``Total  Time`` wall-clock duration reported at the end of the
        ABACUS log, e.g.::

            Total  Time  : 0 h 0 mins 2 secs

        The result is stored in ``self.results`` as ``total_time`` (a float of
        seconds) and ``total_time_unit`` (the string ``"s"``). When the line
        cannot be located or fails to parse, both keys are set to ``None`` so
        the caller can distinguish "not reported" from "reported as zero".
        """
        total_time = None
        # The "Total  Time" line uses two spaces between "Total" and "Time";
        # mirror that exactly in the pattern. The summary line is always at
        # the very end of the log, so we only need to scan the tail and pick
        # the first match we find there; this avoids a full-log regex sweep
        # for very large log files.
        total_time_re = re.compile(r"Total\s+Time\s*:\s*(\d+)\s*h\s*(\d+)\s*mins\s*(\d+)\s*secs")
        for line in self.lines[-100:]:
            match = total_time_re.search(line)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                total_time = float(hours * 3600 + minutes * 60 + seconds)
                break

        self.results["total_time"] = total_time
        self.results["total_time_unit"] = "s" if total_time is not None else None

    def parse(self) -> dict:
        """
        Parse ABACUS output file.

        :returns: parsed results as a dictionary
        """
        self.parse_blocks()
        self.parse_magnetism()
        self.parse_total_time()
        # Parse the lines one-by-one for general information of the calculation
        self.results["energies"] = []  # Container for the per-ionic-step energies in eV
        self.results["electronic_energies"] = []
        current_ion = -1
        for line in self.lines:
            if "TOTAL-pressure" in line:
                self.results["total_pressure"] = float(line.strip().split()[-2])
                self.results["total_pressure_unit"] = line.strip().split()[-1]
            elif "!FINAL_ETOT_IS" in line:
                self.results["total_energy"] = float(line.strip().split()[-2])
            elif "final etot is" in line:
                self.results["energies"].append(float(line.strip().split()[-2]))
            elif "NBANDS =" in line:
                self.results["number_of_bands"] = int(line.strip().split()[-1])
            elif "EFERMI" in line:
                self.results["fermi_level"] = float(line.strip().split()[-2])
            elif "ION=" in line and "ELEC=" in line:
                parts = line.strip().split()
                for i, p in enumerate(parts):
                    if p == "ION=":
                        current_ion = int(parts[i + 1]) - 1
                        break
                while len(self.results["electronic_energies"]) <= current_ion:
                    self.results["electronic_energies"].append([])
            elif "E_KohnSham" in line and current_ion >= 0:
                self.results["electronic_energies"][current_ion].append(float(line.strip().split()[-1]))

        # Check calculation completion status
        self.results["run_status"] = self.compose_run_status()

        self.is_parsed = True
        return self.results

    def parse_kpoints(self):
        """
        Parse the kpoints involved in the calculation.

        ABACUS writes the ``K-POINTS DIRECT/CARTESIAN COORDINATES`` block
        once per spin channel and, for ``nspin == 2`` runs, also appends a
        combined block that lists the k-points once for every spin. We
        therefore pick the first DIRECT block (ABACUS always writes the
        per-spin block first) and validate its size against the per-spin
        k-point count read from the ``<i>/<n> kpoint (Cartesian)``
        eigenvalue header.

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
        if not kdirect:
            raise ValueError("No kpoints data found")

        kpoints_per_spin = self._detect_kpoints_per_spin()
        if kpoints_per_spin is None:
            raise ValueError("No per-spin k-point count found in eigenvalue header.")

        tokens = np.array(kdirect[0][1])
        if len(tokens) != kpoints_per_spin:
            raise ValueError("K-POINTS DIRECT block size does not match per-spin k-point count.")

        kdirect_arr = tokens[:, 1:]
        kcart_arr = np.array(kcart[0][1])[:, 1:] if kcart else None
        return kdirect_arr, kcart_arr

    def _detect_kpoints_per_spin(self):
        """Infer the per-spin k-point count from eigenvalue block headers.

        Looks for ``<i>/<n> kpoint (Cartesian)`` style headers in the running
        log, where ``n`` is the total number of k-points processed for the
        current spin channel. Returns ``None`` if no such header is found.
        """
        match = re.search(
            r"^\s*(\d+)/(\d+)\s+kpoint\s*\(Cartesian\)",
            self.content,
            flags=re.MULTILINE,
        )
        if match is None:
            return None
        try:
            return int(match.group(2))
        except (TypeError, ValueError):
            return None

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
            logger.warning("The number of kpoint is (), but only () on this proc")
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

    def compose_run_status(self) -> dict:
        """
        Check if the calculation completed successfully by looking for 'Total  Time'
        at the end of the running log file and compose the run status dictionary.

        Also detects convergence status from the running log.

        :returns: Dictionary with completion status information
        """
        run_status = {"completed": False, "completion_marker_found": False, "termination_marker": None}

        try:
            # Check if we have any lines to analyze
            if not self.lines:
                logger.warning("Empty file content provided for completion check")
                return run_status

            # Get the last few lines to check for completion markers
            last_lines = self.lines[-10:] if len(self.lines) >= 10 else self.lines

            # Check for ABACUS completion marker
            completion_marker = "Total  Time"  # ABACUS standard completion marker

            # Check for completion marker in the last lines
            for line in reversed(last_lines):
                line_stripped = line.strip()

                # Check for successful completion marker
                if completion_marker in line_stripped:
                    run_status["completed"] = True
                    run_status["completion_marker_found"] = True
                    run_status["termination_marker"] = completion_marker
                    logger.info(f"Found completion marker '{completion_marker}' in line: {line_stripped}")
                    break

            # If no completion marker found, calculation is incomplete
            if not run_status["completed"]:
                logger.warning(f"Completion marker '{completion_marker}' not found in log file")

            # Detect convergence status from the full log
            notifications = self.parse_notifications()
            run_status["notifications"] = notifications

        except Exception as e:
            logger.error(f"Error checking calculation completion: {e!s}")
            run_status["completed"] = False
            run_status["termination_marker"] = f"error: {e!s}"

        return run_status

    def parse_notifications(self) -> list:
        """
        Scan the running log for convergence and error notifications.

        Detects ABACUS-specific patterns:
        - SCF convergence:
          current branches: "!!SCF IS NOT CONVERGED!!" / "#SCF IS CONVERGED#"
          LTS branches: "!! convergence has not been achieved @_@" / "charge density convergence is achieved"
        - Ionic convergence: "Relaxation is (not) converged" / "Lattice relaxation is not converged yet"
        - Geometry convergence: "Geometry relaxation is not converged"
        - Mixed state: "Relaxation is converged, but the SCF is unconverged"

        Preserve the full encounter order so callers can reason about the final state
        of a relaxation instead of just the presence of any earlier warning.

        :returns: List of notification dicts with 'name' and 'message' keys
        """
        notifications = []

        # Patterns to search for in the running log
        patterns = {
            "scf_not_converged": re.compile(r"!!SCF IS NOT CONVERGED!!|!!\s*convergence has not been achieved\s*@_@"),
            "scf_converged": re.compile(r"#SCF IS CONVERGED#|charge density convergence is achieved"),
            "ionic_not_converged": re.compile(r"(?:Lattice )?[Rr]elaxation is not converged(?: yet)?"),
            "ionic_converged": re.compile(r"(?:Lattice )?[Rr]elaxation is converged!"),
            "geometry_not_converged": re.compile(r"Geometry relaxation is not converged"),
            "relax_scf_not_converged": re.compile(r"Relaxation is converged, but the SCF is unconverged"),
        }

        for line in self.lines:
            for name, pattern in patterns.items():
                if pattern.search(line):
                    notifications.append({"name": name, "message": line.strip()})

        return notifications

    def parse_runtime_warnings(self) -> list:
        """
        Scan the running log for warning-like messages not mirrored into ``warning.log``.

        ABACUS commonly emits numerical quality warnings as ``Notice: ...`` lines in
        ``running_*.log``. Keep these in a separate list so they can be merged into the
        parsed misc output without conflating them with convergence notifications.
        """
        patterns = (
            re.compile(r"^\s*Notice:\s*(.+)$"),
            re.compile(r"^\s*Warning:\s*(.+)$", re.IGNORECASE),
        )
        warnings = []
        seen = set()

        for line in self.lines:
            stripped = line.strip()
            for pattern in patterns:
                match = pattern.match(stripped)
                if match is None:
                    continue
                message = match.group(1).strip()
                key = ("running_log", message)
                if key not in seen:
                    seen.add(key)
                    warnings.append({"source": "running_log", "message": message})
                break

        return warnings


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
            while j < len(self.lines):
                this_line = self.lines[j].strip()
                # Break with empty line
                if not this_line:
                    break
                # Break with predefined sequence such as ---- or +++++
                if any(key in this_line for key in self.end_characters):
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


class DosParser:
    """Parser to process DOS1_smearing.dat and DOS2_smearing.dat files"""

    def __init__(self, dos1_content=None, dos2_content=None):
        self.dos1_content = dos1_content
        self.dos2_content = dos2_content

    @staticmethod
    def _parse_single(content):
        energy = []
        dos = []
        for raw_line in content.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    energy.append(float(parts[0]))
                    dos.append(float(parts[1]))
                except ValueError:
                    continue
        return np.array(energy), np.array(dos)

    def parse(self):
        """Parse DOS files and return a dict with energy, tdos, dos1, dos2"""
        result = {}

        if self.dos1_content is not None:
            energy, dos1 = self._parse_single(self.dos1_content)
            result["energy"] = energy
            result["dos1"] = dos1
        else:
            result["dos1"] = None

        if self.dos2_content is not None:
            _, dos2 = self._parse_single(self.dos2_content)
            result["dos2"] = dos2
        else:
            result["dos2"] = None

        if result.get("dos1") is not None and result.get("dos2") is not None:
            result["tdos"] = result["dos1"] + result["dos2"]
        elif result.get("dos1") is not None:
            result["tdos"] = result["dos1"].copy()
        elif result.get("dos2") is not None:
            result["tdos"] = result["dos2"].copy()
        else:
            result["tdos"] = None

        return result


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


class StruParser(BaseRawParser):
    """
    Parse a STRU file
    """

    def parse(self):
        """
        Parse a STRU file
        :returns: A tuple of lattice vectors, positions, species.
        """
        blocks = self.parse_blocks()
        lattice_constant = float(blocks["LATTICE_CONSTANT"][0])  # In bohr
        lattice_vectors = np.array([[float(value) for value in line.split()] for line in blocks["LATTICE_VECTORS"]])
        positions = []
        species = []
        # magnetic_moments = []
        pos_block = blocks["ATOMIC_POSITIONS"]
        coord_type = pos_block[0]
        current_specie = None
        p = 1
        while p < len(pos_block):
            current_specie = pos_block[p]
            # current_magmom = float(pos_block[p+1])
            current_natoms = float(pos_block[p + 2])
            for i in range(int(current_natoms)):
                tokens = pos_block[p + 3 + i].split()
                positions.append([float(value) for value in tokens[:3]])
                species.append(re.match(r"^([A-Za-z]+)", current_specie).group(1))
            p += 3 + int(current_natoms)
        positions = np.array(positions)
        # Lattice vectors in angstrom
        lattice_vectors *= lattice_constant / 1.8897261255

        if coord_type == "Direct":
            positions = positions @ lattice_vectors
        elif coord_type == "Cartesian":
            positions *= lattice_constant / 1.8897261255
        elif coord_type == "Cartesian_au":
            positions *= 1.0 / 1.8897261255
        elif coord_type == "Cartesian_angstrom":
            pass
        else:
            raise ValueError(f"Unknown coordinate type {coord_type}")
        self.structure = {"lattice_vectors": lattice_vectors, "species": species, "positions": positions}
        return lattice_vectors, positions, species

    def parse_structure(self):
        """Parse for the structure"""
        return self.parse()

    def parse_blocks(self):
        """Split the file content by their blocks"""
        keywords = ["ATOMIC_SPECIES", "LATTICE_CONSTANT", "LATTICE_VECTORS", "ATOMIC_POSITIONS"]
        blocks = {}
        current_block = None
        for _line in self.lines:
            line = _line.strip()
            # Skip comment lines
            if not line or line.startswith("#"):
                continue
            # Remove any trailing comments
            line = line.split("#", maxsplit=1)[0].strip()
            # Check if we are in a block title line
            is_title = False
            for block_name in keywords:
                if block_name in line:
                    current_block = block_name
                    blocks[current_block] = []
                    is_title = True
                    continue
            if is_title:
                continue
            # We are in a block - record the content
            if current_block is not None:
                blocks[current_block].append(line)
        self.blocks = blocks
        return blocks


class WarningLogParser(BaseRawParser):
    """
    Parse ABACUS warning.log file.

    ABACUS writes warnings via WARNING() and WARNING_QUIT() functions.
    Format: <file>  warning : <description>
    """

    WARNING_PATTERN = re.compile(r"^\s*(\S+)\s+warning\s*:\s*(.+)$", re.IGNORECASE)

    def parse(self) -> list:
        """
        Parse warning.log and return a list of notification dicts.

        :returns: List of dicts with 'source', 'message' keys
        """
        notifications = []
        for line in self.lines:
            match = self.WARNING_PATTERN.match(line.strip())
            if match:
                notifications.append({"source": match.group(1), "message": match.group(2).strip()})
        return notifications


class PBandsParser(BaseRawParser):
    """Parser for the projected-band structure file ``PBANDS_1``.

    The file is ABACUS-flavoured XML with the following structure::

        <pband>
          <nspin>1</nspin>
          <norbitals>13</norbitals>
          <band_structure nkpoints="358" nbands="12" units="eV">
            ... nkpoints lines of nbands floats each ...
          </band_structure>
          <orbital
          index="1"
          atom_index="1"
          species="Si"
          l="0"
          m="0"
          z="1"
          >
            <data>
              ... nkpoints lines of nbands floats each ...
            </data>
          </orbital>
          ... one <orbital> per (atom, l, m, z) ...
        </pband>

    Note that the opening ``<orbital ...>`` tag spans multiple lines, which
    is not strictly valid XML. The parser therefore walks the file with
    line-by-line regex matching instead of an XML library.

    The returned dict has:
    * ``nspin`` / ``norbitals``
    * ``band_structure`` (np.ndarray of shape ``(nkpoints, nbands)``) — the
      eigenvalues at each k-point, identical to the regular ``BANDS_*`` data.
    * ``orbitals`` (list of dicts) — one per orbital, with ``attrs`` (dict of
      ``index/atom_index/species/l/m/z``) and ``weights`` (np.ndarray of shape
      ``(nkpoints, nbands)``). The order matches the order in the file.
    """

    _ATTR_PATTERN = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")
    _ORBITAL_OPEN_PATTERN = re.compile(r"^<orbital\b", re.MULTILINE)
    _ORBITAL_DATA_PATTERN = re.compile(r"<data>(.*?)</data>", re.DOTALL)
    _BAND_STRUCT_PATTERN = re.compile(r"<band_structure[^>]*>(.*?)</band_structure>", re.DOTALL)
    _BAND_STRUCT_HEADER_PATTERN = re.compile(r"<band_structure([^>]*)>")
    _NBANDS_PATTERN = re.compile(r"nbands\s*=\s*\"([^\"]*)\"")
    _NSPIN_PATTERN = re.compile(r"<nspin>([^<]+)</nspin>")
    _NORBITALS_PATTERN = re.compile(r"<norbitals>([^<]+)</norbitals>")

    def parse(self) -> dict:
        """Parse ``PBANDS_1`` and return the projected band-structure data."""
        if "<pband>" not in self.content:
            raise ValueError("Expected <pband> root tag")

        nspin = int(self._NSPIN_PATTERN.search(self.content).group(1))
        norbitals = int(self._NORBITALS_PATTERN.search(self.content).group(1))

        band_struct_match = self._BAND_STRUCT_PATTERN.search(self.content)
        if band_struct_match is None:
            raise ValueError("Missing <band_structure> block in PBANDS_1")
        band_struct_header = self._BAND_STRUCT_HEADER_PATTERN.search(self.content)
        nbands = int(self._NBANDS_PATTERN.search(band_struct_header.group(1)).group(1).strip())
        band_structure = np.fromstring(band_struct_match.group(1), sep=" ", dtype=float).reshape(-1, nbands)

        orbitals = []
        for orbital_match in self._ORBITAL_OPEN_PATTERN.finditer(self.content):
            # Walk from the <orbital ...> opening tag until the matching </orbital>.
            start = orbital_match.start()
            end_idx = self.content.find("</orbital>", start)
            if end_idx < 0:
                continue
            block = self.content[start:end_idx]
            attrs = {m.group(1): m.group(2).strip() for m in self._ATTR_PATTERN.finditer(block.split(">")[0] + ">")}
            data_match = self._ORBITAL_DATA_PATTERN.search(block)
            if data_match is None:
                continue
            weights = np.fromstring(data_match.group(1), sep=" ", dtype=float).reshape(band_structure.shape)
            orbitals.append({"attrs": attrs, "weights": weights})

        return {
            "nspin": nspin,
            "norbitals": norbitals,
            "band_structure": band_structure,
            "orbitals": orbitals,
        }


class PDosParser(BaseRawParser):
    """Parser for the projected density-of-states file ``PDOS``.

    The file is ABACUS-flavoured XML with the following structure::

        <pdos>
          <nspin>1</nspin>
          <norbitals>13</norbitals>
          <energy_values units="eV">
            ... ne lines of floats ...
          </energy_values>
          <orbital
          index="1"
          atom_index="1"
          species="Si"
          l="0"
          m="0"
          z="1"
          >
            <data>
              ... ne lines of nbands floats each ...
            </data>
          </orbital>
          ... one <orbital> per (atom, l, m, z) ...
        </pdos>

    The opening ``<orbital ...>`` tag spans multiple lines (not strictly
    valid XML); the parser walks the file with line-by-line regex matching.

    The returned dict has:
    * ``nspin`` / ``norbitals``
    * ``energy`` (np.ndarray of shape ``(ne,)``) — the energy grid.
    * ``orbitals`` (list of dicts) — one per orbital, with ``attrs`` and
      ``pdos`` (np.ndarray of shape ``(ne, nbands)``).
    """

    _ATTR_PATTERN = PBandsParser._ATTR_PATTERN
    _ORBITAL_OPEN_PATTERN = re.compile(r"^<orbital\b", re.MULTILINE)
    _ORBITAL_DATA_PATTERN = re.compile(r"<data>(.*?)</data>", re.DOTALL)
    _ENERGY_PATTERN = re.compile(r"<energy_values[^>]*>(.*?)</energy_values>", re.DOTALL)
    _NSPIN_PATTERN = re.compile(r"<nspin>([^<]+)</nspin>")
    _NORBITALS_PATTERN = re.compile(r"<norbitals>([^<]+)</norbitals>")

    def parse(self) -> dict:
        """Parse ``PDOS`` and return the projected DOS data."""
        if "<pdos>" not in self.content:
            raise ValueError("Expected <pdos> root tag")

        nspin = int(self._NSPIN_PATTERN.search(self.content).group(1))
        norbitals = int(self._NORBITALS_PATTERN.search(self.content).group(1))

        energy_match = self._ENERGY_PATTERN.search(self.content)
        if energy_match is None:
            raise ValueError("Missing <energy_values> block in PDOS")
        energy = np.fromstring(energy_match.group(1), sep=" ", dtype=float).reshape(-1)

        orbitals = []
        for orbital_match in self._ORBITAL_OPEN_PATTERN.finditer(self.content):
            start = orbital_match.start()
            end_idx = self.content.find("</orbital>", start)
            if end_idx < 0:
                continue
            block = self.content[start:end_idx]
            attrs = {m.group(1): m.group(2).strip() for m in self._ATTR_PATTERN.finditer(block.split(">")[0] + ">")}
            data_match = self._ORBITAL_DATA_PATTERN.search(block)
            if data_match is None:
                continue
            values = np.fromstring(data_match.group(1), sep=" ", dtype=float)
            nbands = values.size // energy.size
            orbitals.append({"attrs": attrs, "pdos": values.reshape(energy.size, nbands)})

        return {
            "nspin": nspin,
            "norbitals": norbitals,
            "energy": energy,
            "orbitals": orbitals,
        }
