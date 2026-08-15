"""
Parsers provided by aiida_abacus.

Register parsers via the "aiida.parsers" entry point in setup.json.
"""

import re

import numpy as np
from aiida import orm
from aiida.common import exceptions
from aiida.parsers.parser import Parser
from aiida.plugins import CalculationFactory

from ..common import make_retrieve_list
from .raw_parsers import (
    AbacusRawParser,
    DosParser,
    InternalParametersParser,
    KpointsParser,
    StruParser,
    WarningLogParser,
)


class ParserError(RuntimeError):
    """Base exception for parser errors."""


class QuantityMissingError(ParserError):
    """A required quantity is missing from the parsed data."""


class RequiredQuantityMissingError(ParserError):
    """A required quantity that must be present is missing."""


class MissingFileError(ParserError):
    """An expected output file is missing."""


AbacusCalculation = CalculationFactory("abacus.abacus")

DEFAULT_OUTPUT_SETTINGS = {
    "bands": False,
    "dos": False,
    "internal_parameters": False,
    "kpoints": False,
}

RELAX_RUN_TYPES = {"relax", "cell-relax", "md"}
SCF_CONVERGENCE_CHECK_RUN_TYPES = {"scf", "relax", "cell-relax"}


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
        output_suffix = self.node.process_class._OUTPUT_SUFFIX
        expected_files = make_retrieve_list(self.node.inputs.parameters, settings, output_suffix)
        run_type = self.node.inputs.parameters["input"].get("calculation", "scf")
        mandatory_files = self._get_mandatory_files(run_type, output_suffix)

        # Check if the files are retrieved
        missing = []
        for name in expected_files:
            # Skip glob patterns — they cannot be looked up by exact name via get_object
            if any(c in name for c in "*?["):
                continue
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
            raw_parser = AbacusRawParser(fhandle)
        misc_results.update(raw_parser.parse())

        # The magnetism keys are populated by the raw parser unconditionally so the
        # value-presence is captured consistently. Strip them from the misc node when
        # the calculation is not spin-polarised, since ABACUS does not emit any
        # magnetism lines in `running_*.log` for nspin=1.
        if not self._parameters_have_magnetism(self.node.inputs.parameters):
            misc_results.pop("magnetism", None)
            misc_results.pop("final_magnetism", None)

        # Check if calculation completed successfully using run_status from raw parser
        run_status = misc_results.get("run_status", {})
        notifications = run_status.get("notifications", [])

        if not run_status.get("completed", False):
            marker = run_status.get("termination_marker", "unknown")
            self.logger.warning(f"Calculation did not complete successfully. Termination marker: {marker}")
            return self.exit_codes.ERROR_CALCULATION_INCOMPLETE

        relax_structure = None
        if run_type in RELAX_RUN_TYPES and f"OUT.{output_suffix}/STRU_ION_D" not in missing:
            relax_structure = self._parse_relax_structure(output_folder, expected_files)

        if run_type in SCF_CONVERGENCE_CHECK_RUN_TYPES:
            final_scf_state = self._last_notification_name(notifications, {"scf_converged", "scf_not_converged"})
            final_ionic_state = self._last_notification_name(
                notifications, {"ionic_converged", "ionic_not_converged", "geometry_not_converged"}
            )

            if any(n["name"] == "relax_scf_not_converged" for n in notifications):
                self.logger.warning("Ionic relaxation converged, but the final SCF did not converge.")
                return self.exit_codes.ERROR_ELECTRONIC_NOT_CONVERGED

            # Check for electronic convergence failure
            if final_scf_state == "scf_not_converged":
                self.logger.warning("SCF did not converge in the final relevant step.")
                return self.exit_codes.ERROR_ELECTRONIC_NOT_CONVERGED

            # Check for ionic relaxation convergence failure
            if final_ionic_state in {"ionic_not_converged", "geometry_not_converged"}:
                if relax_structure is not None:
                    self.out("structure", relax_structure)
                self.logger.warning("Ionic relaxation did not converge.")
                return self.exit_codes.ERROR_IONIC_NOT_CONVERGED

        missing_mandatory = [name for name in mandatory_files if name in missing]
        if missing_mandatory:
            self.logger.error(f"The following mandatory output files are missing: {missing_mandatory}")
            return self.exit_codes.ERROR_MISSING_OUTPUT_FILES

        # Parse warning.log if available
        folder_name = "OUT." + output_suffix
        warning_log_path = folder_name + "/warning.log"
        warning_notifications = []
        try:
            with output_folder.open(warning_log_path, "r") as fhandle:
                warning_parser = WarningLogParser(fhandle)
                warning_notifications = warning_parser.parse()
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.logger.warning(f"Failed to parse warning.log: {exc}")

        misc_results["warnings"] = self._merge_warnings(warning_notifications, raw_parser.parse_runtime_warnings())

        misc_node = orm.Dict(dict=misc_results)

        # Parse the bands output if requested
        if self.check_include_node("bands"):
            eigenvalues, occupations, _ = raw_parser.parse_eigenvalues()
            kpoints_direct, _ = raw_parser.parse_kpoints()
            kcoord = kpoints_direct[:, :3]
            kweights = kpoints_direct[:, 3]
            node = orm.BandsData()
            node.set_kpoints(kcoord, weights=kweights)
            if kcoord.shape[0] != eigenvalues.shape[1]:
                raise AssertionError(
                    f"kcoord.shape={kcoord.shape} does not match eigenvalues.shape[1]={eigenvalues.shape[1]}."
                )
            node.set_bands(eigenvalues, occupations=occupations)

            # Handle kpoints labels - ABACUS may remove duplicate kpoints
            if hasattr(self.node.inputs, "kpoints") and hasattr(self.node.inputs.kpoints, "labels"):
                input_labels = self.node.inputs.kpoints.labels
                if input_labels:
                    input_kpoints = self.node.inputs.kpoints.get_kpoints()
                    n_input = len(input_kpoints)
                    n_output = kcoord.shape[0]

                    # Only remap labels if ABACUS removed duplicate kpoints
                    if n_input != n_output:
                        remapped = self._remap_kpoint_labels(input_kpoints, input_labels, kcoord, self.logger)
                        if remapped is not None:
                            node.labels = remapped
                    else:
                        # No duplicates, use labels as-is
                        node.labels = input_labels

            # Record the fermi level - the unit is eV
            node.base.attributes.set("fermi_level", misc_node.get("fermi_level"))
            self.out("bands", node)

        # Parse the DOS output if requested
        if self.check_include_node("dos"):
            folder_name = "OUT." + output_suffix
            dos1_path = folder_name + "/DOS1_smearing.dat"
            dos2_path = folder_name + "/DOS2_smearing.dat"

            dos1_content = None
            dos2_content = None
            try:
                with output_folder.open(dos1_path, "r") as f:
                    dos1_content = f.read()
            except FileNotFoundError:
                pass
            try:
                with output_folder.open(dos2_path, "r") as f:
                    dos2_content = f.read()
            except FileNotFoundError:
                pass

            if dos1_content is None and dos2_content is None:
                self.logger.warning("No DOS files found for parsing")
            else:
                parser = DosParser(dos1_content, dos2_content)
                result = parser.parse()
                dos_node = orm.ArrayData()
                if result["energy"] is not None:
                    dos_node.set_array("energy", result["energy"])
                if result["tdos"] is not None:
                    dos_node.set_array("tdos", result["tdos"])
                if result["dos1"] is not None:
                    dos_node.set_array("dos1", result["dos1"])
                if result["dos2"] is not None:
                    dos_node.set_array("dos2", result["dos2"])
                self.out("dos", dos_node)

        # TODO: there could be other types that should have a output structure
        if run_type in ["relax", "cell-relax", "md"]:
            if relax_structure is not None:
                self.out("structure", relax_structure)
            # Compose trajectory node
            trajectory = self._compose_trajectory(output_folder, misc_results)
            if trajectory:
                self.out("trajectory", trajectory)

        # Parse the calculation raw parameters
        if self.check_include_node("internal_parameters"):
            fname = next(filter(lambda x: x.endswith("INPUT"), expected_files))
            with output_folder.open(fname, "r") as fhandle:
                parser = InternalParametersParser(fhandle)
            self.out("internal_parameters", orm.Dict(parser.parse()))

        # Parse the KPOINTS actually used
        if self.check_include_node("kpoints"):
            fname = next(filter(lambda x: x.endswith("kpoints"), expected_files))
            with output_folder.open(fname, "r") as fhandle:
                parser = KpointsParser(fhandle)
                coords, weights = parser.parse()
            node = orm.KpointsData()
            node.set_kpoints(coords, weights=weights)
            # Set the cell based on the  INPUT structure
            node.set_cell_from_structure(self.node.inputs.structure)
            self.out("kpoints", node)

        # Define the output nodes
        self.out("misc", misc_node)

    def _get_mandatory_files(self, run_type: str, output_suffix: str) -> list[str]:
        """Return files that are required for this parser invocation."""
        folder_name = f"OUT.{output_suffix}"
        mandatory = [f"{folder_name}/running_{run_type}.log"]

        if run_type in RELAX_RUN_TYPES:
            mandatory.append(f"{folder_name}/STRU_ION_D")
        if self.check_include_node("internal_parameters"):
            mandatory.append(f"{folder_name}/INPUT")
        if self.check_include_node("kpoints"):
            mandatory.append(f"{folder_name}/kpoints")

        return mandatory

    @staticmethod
    def _parameters_have_magnetism(parameters) -> bool:
        """Return ``True`` if the calculation is spin-polarised (i.e. emits magmom lines).

        ABACUS only reports ``total magnetism`` / ``absolute magnetism`` in
        ``running_*.log`` when ``nspin`` is ``2`` (collinear) or ``4`` (non-collinear);
        for ``nspin == 1`` the corresponding lines are not emitted. We therefore key
        the magnetism parser off ``parameters['input']['nspin']`` only.
        """
        if parameters is None:
            return False
        if isinstance(parameters, orm.Dict):
            parameters = parameters.get_dict()

        input_block = parameters.get("input", {}) or {}
        return int(input_block.get("nspin", 1) or 1) > 1

    @staticmethod
    def _merge_warnings(*warning_sets: list[dict]) -> list[dict]:
        """Merge warning records while preserving input order and removing duplicates."""
        merged = []
        seen = set()
        for warning_set in warning_sets:
            for warning in warning_set:
                source = warning.get("source", "")
                message = warning.get("message", "")
                key = message
                if key in seen:
                    continue
                seen.add(key)
                merged.append({"source": source, "message": message})
        return merged

    @staticmethod
    def _last_notification_name(notifications: list[dict], names: set[str]) -> str | None:
        """Return the last matching notification name from an ordered notification list."""
        for notification in reversed(notifications):
            name = notification.get("name")
            if name in names:
                return name
        return None

    @staticmethod
    def _parse_relax_structure(output_folder, expected_files):
        """Parse the final structure emitted by a relax-like calculation."""
        fname = next(filter(lambda x: "STRU_ION_D" in x, expected_files))
        with output_folder.open(fname, "r") as fhandle:
            parser = StruParser(fhandle)
            cell, positions, species = parser.parse_structure()
        node = orm.StructureData(cell=cell)
        for pos, symbol in zip(positions, species):
            node.append_atom(position=pos, symbols=symbol)
        return node

    def check_include_node(self, name: str):
        """
        Check whether to include certain output node
        """

        if "settings" not in self.node.inputs:
            return DEFAULT_OUTPUT_SETTINGS[name]
        return self.node.inputs.settings.get("include_" + name, DEFAULT_OUTPUT_SETTINGS[name])

    def _compose_trajectory(self, output_folder: orm.FolderData, data_dict: dict):
        """
        Compose a TrajectoryData node based on the retrieved data
        :param output_folder: A FolderData containing the retrieved files
        :param data_dict: The `results` dictionary retrieved
        :return: A orm.TrajectoryData Node or None.
        """
        output_suffix = self.node.process_class._OUTPUT_SUFFIX
        folder_name = "OUT." + output_suffix
        traj_files = [
            file_name
            for file_name in output_folder.list_object_names(folder_name)
            if re.match(r"STRU_ION(\d+)_D$", file_name)
        ]
        if not traj_files:
            self.logger.warning("Skipping trajectory node creation: No intermediate STRU_ION*_D files found.")
            # Check out_stru parameter
            if "parameters" in self.node.inputs:
                out_stru = self.node.inputs.parameters["input"].get("out_stru", "0")
                if str(out_stru).lower() in ["0", False]:
                    self.logger.warning("Please set 'out_stru = 1' in INPUT to enable trajectory output.")
            return None
        traj_files.sort(key=lambda f: int(re.search(r"STRU_ION(\d+)_D$", f).group(1)))
        cell_list = []
        positions_list = []
        symbols_list = []
        for traj_file in traj_files:
            with output_folder.open(folder_name + "/" + traj_file) as fhandle:
                parser = StruParser(fhandle)
                cell, positions, species = parser.parse_structure()
            cell_list.append(cell)
            positions_list.append(positions)
            symbols_list.append(species)
        traj = orm.TrajectoryData()
        traj.set_trajectory(symbols=symbols_list[0], cells=np.array(cell_list), positions=np.array(positions_list))
        # Set additional data
        if data_dict.get("all_forces"):
            traj.set_array("forces", np.array(data_dict["all_forces"]))
            traj.base.attributes.set("force_unit", data_dict["force_unit"])
        if data_dict.get("energies"):
            traj.set_array("energies", np.array(data_dict["energies"]))
        all_stress = data_dict.get("all_stress", data_dict.get("all_stresses"))
        if all_stress:
            traj.set_array("stresses", np.array(all_stress))
            traj.base.attributes.set("stress_unit", data_dict["stress_unit"])
        return traj

    @staticmethod
    def _remap_kpoint_labels(input_kpoints, input_labels, output_kpoints, logger):
        """
        Remap kpoint labels when ABACUS removes duplicate kpoints.

        ABACUS may remove duplicate kpoints from the input path (e.g., when the path
        returns to a high-symmetry point like GAMMA). This function remaps the labels
        to match the output kpoints.

        :param input_kpoints: List of input kpoint coordinates
        :param input_labels: List of (index, label_name) tuples from input
        :param output_kpoints: Array of output kpoint coordinates (after deduplication)
        :param logger: Logger instance for debug/info messages
        :return: Remapped list of (index, label_name) tuples, or None if no labels to apply
        """
        n_input = len(input_kpoints)
        n_output = output_kpoints.shape[0]

        logger.info(
            f"Input has {n_input} kpoints but output has {n_output} kpoints. "
            f"ABACUS removed {n_input - n_output} duplicate kpoint(s)."
        )

        # Build mapping from input index to output index
        label_mapping = {}
        output_index = 0

        for input_idx in range(n_input):
            if output_index >= n_output:
                break

            # Check if this input kpoint matches the current output kpoint
            # Use modulo 1 to handle periodic boundary conditions in reciprocal space
            input_kpt = np.array(input_kpoints[input_idx][:3])
            output_kpt = output_kpoints[output_index]
            diff = np.abs((input_kpt - output_kpt + 0.5) % 1.0 - 0.5)

            if np.all(diff < 1e-6):
                label_mapping[input_idx] = output_index
                output_index += 1

        # Remap labels using the mapping
        remapped_labels = []
        for old_idx, label_name in input_labels:
            if old_idx in label_mapping:
                new_idx = label_mapping[old_idx]
                remapped_labels.append((new_idx, label_name))
                logger.debug(f"Remapped label '{label_name}': index {old_idx} -> {new_idx}")
            else:
                logger.debug(f"Skipped label '{label_name}' at index {old_idx} (kpoint was removed as duplicate)")

        if remapped_labels:
            logger.info(f"Applied {len(remapped_labels)} labels to bands data")

        return remapped_labels if remapped_labels else None
