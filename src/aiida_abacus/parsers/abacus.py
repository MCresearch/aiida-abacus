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
from .raw_parsers import AbacusRawParser, InternalParametersParser, KpointsParser, StruParser

AbacusCalculation = CalculationFactory("abacus.abacus")

DEFAULT_OUTPUT_SETTINGS = {
    "bands": False,
    "internal_parameters": False,
    "kpoints": False,
}


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
            raw_parser = AbacusRawParser(fhandle)
        misc_results.update(raw_parser.parse())

        # Check if calculation completed successfully using run_status from raw parser
        run_status = misc_results.get("run_status", {})
        if not run_status.get("completed", False):
            marker = run_status.get("termination_marker", "unknown")
            self.logger.warning(f"Calculation did not complete successfully. Termination marker: {marker}")
            return self.exit_codes.ERROR_CALCULATION_INCOMPLETE

        misc_node = orm.Dict(dict=misc_results)

        # Parse the bands output if requested
        if self.check_include_node("bands"):
            eigenvalues, occupations, _ = raw_parser.parse_eigenvalues()
            kpoints_direct, _ = raw_parser.parse_kpoints()
            kcoord = kpoints_direct[:, :3]
            kweights = kpoints_direct[:, 3]
            node = orm.BandsData()
            node.set_kpoints(kcoord, weights=kweights)
            assert kcoord.shape[0] == eigenvalues.shape[1], "Inconsistent number of kpoints reported (do not use kpar)"
            node.set_bands(eigenvalues, occupations=occupations)
            node.labels = self.node.inputs.kpoints.labels
            # Record the fermi level - the unit is eV
            node.base.attributes.set("fermi_level", misc_node.get("fermi_level"))
            self.out("bands", node)

        # TODO: there could be other types that should have a output structure
        if run_type in ["relax", "cell-relax", "md"]:
            # Parse the final structure
            fname = next(filter(lambda x: "STRU_ION_D" in x, expected_files))
            with output_folder.open(fname, "r") as fhandle:
                parser = StruParser(fhandle)
                cell, positions, species = parser.parse_structure()
            node = orm.StructureData(cell=cell)
            for pos, symbol in zip(positions, species):
                node.append_atom(position=pos, symbols=symbol)
            self.out("structure", node)
            # Compose trajectory node
            self.out(
                "trajectory", compose_trajectory(output_folder, misc_results, self.node.process_class._OUTPUT_SUFFIX)
            )

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

    def check_include_node(self, name: str):
        """
        Check whether to include certain output node
        """

        if "settings" not in self.node.inputs:
            return DEFAULT_OUTPUT_SETTINGS[name]
        return self.node.inputs.settings.get("include_" + name, DEFAULT_OUTPUT_SETTINGS[name])


def compose_trajectory(output_folder: orm.FolderData, data_dict: dict, output_suffix=AbacusCalculation._OUTPUT_SUFFIX):
    """
    Compose a TrajectoryData node based on the retrieved data

    :param output_folder: A FolderData containing the retrieved files
    :param data_dict: The `results` dictionary retrieved
    :param output_suffix: The *suffix* used by AbacusCalculation

    :return: A orm.TrajectoryData Node.
    """
    folder_name = "OUT." + output_suffix
    traj_files = [
        file_name
        for file_name in output_folder.list_object_names(folder_name)
        if re.match(r"STRU_ION\d+_D$", file_name)
    ]
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
    if data_dict.get("all_stresses"):
        traj.set_array("stresses", np.array(data_dict["stresses"]))
        traj.base.attributes.set("stress_unit", data_dict["stress_unit"])
    return traj
