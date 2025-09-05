"""
Calculations provided by aiida_abacus.

Register calculations via the "aiida.calculations" entry point in setup.json.
"""

import os

import numpy as np
from aiida import orm
from aiida.common import datastructures, exceptions
from aiida.common.utils import get_unique_filename
from aiida.engine import CalcJob
from aiida.plugins import DataFactory
from aiida_pseudo.data.pseudo.upf import UpfData

from aiida_abacus.common.opthold import SettingsOptions
from aiida_abacus.data.orbital import AtomicOrbitalData

from .common import make_retrieve_list

LegacyUpfData = DataFactory("core.upf")


class AbacusCalculation(CalcJob):
    """
    AiiDA calculation plugin wrapping ABACUS calculation.

    """

    # Here we define some default paths for the input and output files of the calculation
    _PSEUDO_SUBFOLDER = "./pseudo/"  # default pesudopotential folder
    _ORBITAL_SUBFOLDER = "./orbital/"  # default orbital folder
    _OUTPUT_SUFFIX = "aiida"  # default output suffix
    _OUTPUT_SUBFOLDER = "OUT." + _OUTPUT_SUFFIX  # default output folder
    _DEFAULT_RETRIEVE_LIST = [_OUTPUT_SUBFOLDER]
    _ABACUS_OUTPUT = "abacus_output"

    @classmethod
    def get_default_calc_paths(cls):
        """Return a dictionary with the default path settings for the calculation."""
        return {
            "PSEUDO_SUBFOLDER": cls._PSEUDO_SUBFOLDER,
            "ORBITAL_SUBFOLDER": cls._ORBITAL_SUBFOLDER,
            "OUTPUT_SUFFIX": cls._OUTPUT_SUFFIX,
            "OUTPUT_SUBFOLDER": cls._OUTPUT_SUBFOLDER,
            "ABACUS_OUTPUT": cls._ABACUS_OUTPUT,
        }

    @classmethod
    def define(cls, spec):
        """Define inputs and outputs of the calculation."""
        super().define(spec)

        # set default values for AiiDA options
        spec.inputs["metadata"]["options"]["resources"].default = {
            "num_machines": 1,
            "num_mpiprocs_per_machine": 1,  # use 1 cores per machine by default
        }
        # entry point for parser
        spec.inputs["metadata"]["options"]["parser_name"].default = "abacus.abacus"

        # default output name, where the output of the calculation will be written
        spec.inputs["metadata"]["options"]["output_filename"].default = cls._ABACUS_OUTPUT

        spec.input("metadata.options.withmpi", valid_type=bool, default=True)  # use mpi by default

        # new ports

        # structural data for 3 Input file for ABACUS calculation
        # see https://abacus.deepmodeling.com/en/latest/quick_start/input.html for detail

        # parameters, which is a Dict
        # consists of different parts
        # "input" dict will be written into INPUT file after validation
        # "stru" dict will be queried to write STRU file
        # thus, parameters is likely some Dict() of {"input": {}, "stru": {}}
        spec.input("parameters", valid_type=orm.Dict, help="The ABACUS input parameters.")

        # kpoints, which is a KpointsData
        # will be written into KPT file after validation
        spec.input("kpoints", valid_type=orm.KpointsData, help="The kpoints KPT.")

        # structure, which is a StructureData
        # and some other parameters (Dict)
        # will be written into STRU file after validation
        spec.input("structure", valid_type=orm.StructureData, help="The input structure STRU.")
        # following ports are some parameters that do not belong to INPUT,
        # but required by STRU!

        # Several other parameters could be defined after the atom position using key words.
        # See https://abacus.deepmodeling.com/en/latest/advanced/input_files/stru.html#more-key-words
        # for details.
        spec.input(
            "settings",
            valid_type=orm.Dict,
            validator=SettingsOptions.aiida_validate,
            serializer=SettingsOptions.aiida_serialize,
            help=SettingsOptions.aiida_description(),
            required=False,
        )
        # spec.input("dynamics", valid_type=orm.Dict, help="The dynamics parameters in STRU.")
        # spec.input("magmom", valid_type=orm.Dict, help="The magnetic moments in STRU.")

        # dynamic pseudopotential input port namespace, adapted from aiida-castep
        spec.input_namespace(
            "pseudos",
            help=(
                "Use nodes for the pseudopotentails of one of the element in the structure."
                "Pass a dictionary specifying the pseudpotential node for each kind,"
                "such as {O: <PsudoNode>}."
            ),
            required=True,
            valid_type=(LegacyUpfData, UpfData),
            dynamic=True,
        )

        spec.input(
            "restart_folder",
            valid_type=orm.RemoteData,
            help="Existing calculation folder to restart from.",
            required=False,
        )

        # misc stands for miscellaneous, which is some of
        # the scalar outputs or small vectors (e.g., energy, forces, stress) of the calculation.
        # extracted from the output file OUT.aiida/running_scf.log
        # results will be stored in a Dict node.
        spec.output(
            "misc",
            valid_type=orm.Dict,
            help="The scalar outputs or small vectors (e.g., energy, forces, stress) of the calculation.",
            required=True,
        )
        spec.output(
            "structure",
            valid_type=orm.StructureData,
            help="Output structure of the calculation.",
            required=False,
        )
        spec.output(
            "kpoints",
            valid_type=orm.KpointsData,
            help="Output structure of the calculation.",
            required=False,
        )

        spec.output(
            "internal_parameters",
            valid_type=orm.Dict,
            help="The internal parameters used by the calculation.",
            required=False,
        )

        spec.output(
            "bands",
            valid_type=orm.BandsData,
            help="Band structure",
            required=False,
        )

        spec.exit_code(
            300,
            "ERROR_MISSING_OUTPUT_FILES",
            message="Calculation did not produce all expected output files.",
        )
        # Set 'misc' to be default output node so calcjob.res and verdi calcjob res works
        spec.default_output_node = "misc"

    def prepare_for_submission(self, folder):
        """
        Create input files.

        :param folder: an `aiida.common.folders.Folder` where the plugin should temporarily place all files
            needed by the calculation.
        :return: `aiida.common.datastructures.CalcInfo` instance
        """
        local_copy_list = []

        input_file = folder.get_abs_path("INPUT")
        kpt_file = folder.get_abs_path("KPT")
        stru_file = folder.get_abs_path("STRU")

        self.write_input(input_file)
        self.write_kpoints(kpt_file)

        local_pseudo_copy_list = self.write_stru(stru_file)
        local_copy_list.extend(local_pseudo_copy_list)

        codeinfo = datastructures.CodeInfo()

        # To run ABACUS, no cmdline params needed
        codeinfo.cmdline_params = []
        codeinfo.code_uuid = self.inputs.code.uuid
        # The stdout_name attribute tells the engine where the output of the executable should be redirected to.
        # Here set to the value of the output_filename option.
        codeinfo.stdout_name = self._ABACUS_OUTPUT

        # Prepare a `CalcInfo` to be returned to the engine
        calcinfo = datastructures.CalcInfo()
        calcinfo.codes_info = [codeinfo]
        calcinfo.local_copy_list = local_copy_list

        # Remote copy
        if "restart_folder" in self.inputs:
            calcinfo.remote_copy_list = [
                (
                    self.inputs.restart_folder.computer.uuid,
                    self.inputs.restart_folder.get_remote_path() + "/" + self._OUTPUT_SUBFOLDER,
                    self._OUTPUT_SUBFOLDER,
                )
            ]

        # retrieve the output folder OUT.aiida
        # Gather the list of the files to be retrieved/included
        settings = {} if "settings" not in self.inputs else self.inputs.settings
        calcinfo.retrieve_list = [
            [self._ABACUS_OUTPUT, ".", 0],
            *make_retrieve_list(self.inputs.parameters, settings, self._OUTPUT_SUFFIX, full_specification=True),
        ]

        return calcinfo

    # make INPUT file content by given parameters dict
    def generate_input(self, parameters: dict) -> str:
        """Generate the content of input file INPUT according to parameters.
        For detailed documentation,
        see the `ABACUS Input Guide <https://abacus.deepmodeling.com/en/latest/quick_start/input.html>`_.
        :param parameters: a dictionary of input parameters
        :return: the content of the input file INPUT"""
        # may add some validation here, and maybe some conversions
        input_list = [
            "INPUT_PARAMETERS"  # parameter list always starts with key word INPUT_PARAMETERS
        ]

        for key, value in parameters.items():
            # The longest parameter is 'bessel_descriptor_tolerence' with 27 characters.
            input_list.append(f"{key:<30}{value}")
        input_content = "\n".join(input_list)
        return input_content

    # param string -> INPUT file, call generate_input and write down file
    def write_input(self, input_file):
        """Write the input file INPUT."""

        # prepare input content
        parameters = self.inputs.parameters.get_dict()
        # output folder will be OUT.aiida
        parameters["input"]["suffix"] = self._OUTPUT_SUFFIX
        # parameters.suffix = "aiida"
        # folder for pseudopotentials, default is ./pseudo/
        parameters["input"]["pseudo_dir"] = self._PSEUDO_SUBFOLDER
        # folder for orbitals, default is ./orbital/
        parameters["input"]["orbital_dir"] = self._ORBITAL_SUBFOLDER

        input_content = self.generate_input(parameters["input"])
        with open(input_file, "w") as handle:
            handle.write(input_content)

    def write_kpoints(self, kpt_file):
        """Write the kpoints file KPT."""
        # validation adapted from aiida-quantumespresso\src\aiida_quantumespresso\calculations\__init__.py
        knode = self.inputs.kpoints
        if "mesh" in knode.base.attributes:
            kpt_list = [
                "K_POINTS",  # keyword for start, must be set to this value
                "0",  # total number of k-point, `0' means generate automatically
                "Gamma",  # which kind of Monkhorst-Pack method, `Gamma' or `MP'
                # here we need six numbers,
                # first three number: subdivisions along reciprocal vectors
                # last three number: shift of the mesh
            ]
            # Mesh of kpoints: List[int]
            # Offset of the mesh: List[float]
            mesh, offset = self.inputs.kpoints.get_kpoints_mesh()
            if any([i not in [0, 0.5] for i in offset]):
                raise exceptions.InputValidationError("offset list must only be made of 0 or 0.5 floats")
            # Convert offset to integers (0 or 1)
            the_offset = [0 if i == 0.0 else 1 for i in offset]

            kpt_list.append(f"{' '.join(map(str, mesh + the_offset))}\n")

        else:
            kpoints = knode.get_kpoints()
            if "weights" in knode.get_arraynames():
                weights = knode.get_array("weights")
            else:
                weights = np.ones(len(kpoints)) * (1 / len(kpoints))

            kpt_list = [
                "K_POINTS",  # keyword for start, must be set to this value
                f"{len(kpoints)}",
                "Direct",
            ]
            labels = knode.labels
            if labels is not None:
                labels_map = dict(labels)
            else:
                labels_map = {}
            for i, coord in enumerate(kpoints):
                label = labels_map.get(i)
                # Write labels if they exist
                # No effect to the calculation, but nice to have when checking raw input files
                if label is None:
                    kpt_list.append(f"{coord[0]:.14f} {coord[1]:.14f} {coord[2]:.14f} {weights[i]:.14f}")
                else:
                    kpt_list.append(f"{coord[0]:.14f} {coord[1]:.14f} {coord[2]:.14f} {weights[i]:.14f} // {label}")

        # Write to the file
        with open(kpt_file, "w") as handle:
            handle.write("\n".join(kpt_list) + "\n")

    def generate_structure(self, structure, pseudos, parameters) -> str:
        """Generate the content of input file STRU according to structure.
        For detailed documentation,
        see the ABACUS documentation about the `STRU file <https://abacus.deepmodeling.com/en/latest/advanced/input_files/stru.html>`_.
        :param structure: a StructureData object
        :param pseudos: a dictionary of pseudopotential nodes
        :param parameters: a dictionary of stru parameters
        :return: the content of the input file STRU & a list of pseudopotential files to be copied"""
        # may add some validation here, and maybe some conversions

        # This is the atom file containing all the information about the lattice structure.
        structure_list = []

        # adapted from aiida-quantumespresso\src\aiida_quantumespresso\calculations\__init__.py

        # copy useful pseudopotential files to the calc pseudo folder
        local_copy_list_to_append = []

        pseudo_filenames = {}

        structure_list = []

        # ATOMIC_SPECIES section
        # This section provides information about the type of chemical elements contained the unit cell.
        # structure_list.append("ATOMIC_SPECIES\n")
        atomic_species = ["ATOMIC_SPECIES"]

        kind_names = []
        # append the pseudopotential files to the list of files to be copied
        for kind in structure.kinds:
            # This should not give errors, I already checked before that
            # the list of keys of pseudos and kinds coincides
            # need validation here
            # structure_kinds = set(value['structure'].get_kind_names())
            # pseudo_kinds = set(value['pseudos'].keys())

            # if structure_kinds != pseudo_kinds:
            #     return f'The `pseudos` specified and structure kinds do not match: {pseudo_kinds} vs
            # {structure_kinds}'

            pseudo = pseudos[kind.name]
            if kind.is_alloy or kind.has_vacancies:
                raise exceptions.InputValidationError(
                    f"Kind '{kind.name}' is an alloy or has vacancies. This is not allowed for pw.x input structures."
                )
            if pseudo.pk not in pseudo_filenames:
                filename = get_unique_filename(pseudo.filename, list(pseudo_filenames.values()))
                pseudo_filenames[pseudo.pk] = filename
                local_copy_list_to_append.append(
                    (pseudo.uuid, pseudo.filename, os.path.join(self._PSEUDO_SUBFOLDER, filename))
                )
            else:
                # Pseudopotential file already copied
                filename = pseudo_filenames[pseudo.pk]

            kind_names.append(kind.name)
            atomic_species.append(f"{kind.name.ljust(6)} {kind.mass:^8}  {filename}")

        structure_list.extend(atomic_species)

        # NUMERICAL_ORBITAL section
        # Numerical atomic orbitals are only needed for LCAO calculations.
        # This section will be neglected in calcultions with plane wave basis(PW).
        # numerical_orbital = ["\nNUMERICAL_ORBITAL"]
        # structure_list.extend(numerical_orbital)
        # structure_list.append("\nNUMERICAL_ORBITAL\n")
        # for orbital in structure["numerical_orbital"]:
        #     structure_list.append(orbital)

        numberial_orbital = ["NUMERICAL_ORBITAL"]
        kind_names = []
        # append the orbtial files stored in the node to the list of files to be copied
        # The OrbtialData node has a second file whose filename is stored under the key filename_second
        orbital_filenames = {}
        for kind in structure.kinds:
            pseudo = pseudos[kind.name]
            if not isinstance(pseudo, AtomicOrbitalData):
                continue
            if pseudo.pk not in orbital_filenames:
                filename = get_unique_filename(pseudo.filename_second, list(orbital_filenames.values()))
                orbital_filenames[pseudo.pk] = filename
                local_copy_list_to_append.append(
                    (pseudo.uuid, pseudo.filename_second, os.path.join(self._ORBITAL_SUBFOLDER, filename))
                )
            else:
                # Pseudopotential file already included
                filename = orbital_filenames[pseudo.pk]

            kind_names.append(kind.name)
            numberial_orbital.append(f"{filename}")
        # Only add if there are orbital files
        if numberial_orbital:
            structure_list.extend(numberial_orbital)

        # LATTICE_CONSTANT section
        # The lattice constant of the system in unit of Bohr.
        # print("parameter is:", parameters)
        lattice_constant = ["\nLATTICE_CONSTANT"]
        # print("structure.cell is:", structure.cell)
        # need to be rechecked!
        # LATTICE_CONSTANT represents a length for the overall scaling of the lattice.
        # Note that 1 Angstrom = 1.8897261258369282 bohr,
        # and writing a decimal starting with 1.8 here means that
        # the following LATTICE_VECTORS section can be written in lattice units of Angstrom.

        # lengths_in_ang = [np.linalg.norm(v) for v in structure.cell]
        # lengths_in_bohr = [ang_to_bohr * length for length in lengths_in_ang]
        # lattice_const_in_ang = max(lengths_in_ang)
        # lattice_const_in_bohr = max(lengths_in_bohr)
        # print(f"Calculated LATTICE_CONSTANT: {lattice_const_in_ang} Angstrom")

        # print("cell lengths:", structure.cell_lengths)
        # print(f"lattice_const in bohr {lattice_const_in_bohr} Bohr")

        # Use the bohr unit given in the abacus documentation
        lattice_const_in_bohr = 1.889726125457828  # 1.889726125457828  Bohr =  1.0 Angstrom
        if "LATTICE_CONSTANT" in parameters:
            lattice_constant.append(str(parameters["LATTICE_CONSTANT"]))
        else:
            lattice_constant.append(str(lattice_const_in_bohr))
        structure_list.extend(lattice_constant)

        # LATTICE_VECTORS section
        # This section is only relevant when latname (see input parameters) is used to specify the Bravais lattice type.
        lattice_vectors = ["\nLATTICE_VECTORS"]
        for vector in structure.cell:
            lattice_vectors.extend([f"{vector[0]:20}{vector[1]:20}{vector[2]:20}"])
        structure_list.extend(lattice_vectors)

        # ATOMIC_POSITIONS section
        # This section specifies the positions and other information of individual atoms.
        atom_positions = [
            "ATOMIC_POSITIONS",
            "Cartesian",  # Positions of the sites are in cartesian coordinates given by the StructureData
        ]

        # atom position dict consists of 4 parts:
        # part 1 Element type
        # part 2 magnetism (Be careful: value 1.0 refers to 1.0 bohr mag, but not fully spin up !!!)
        # part 3 number of atoms
        # part 4 the position of atoms and other parameter specify by key word
        # 4 details see https://abacus.deepmodeling.com/en/latest/advanced/input_files/stru.html#atomic-positions
        # e.g. keyword `m` or no keywords - followed by move_x, move_y, move_z
        # x,y,z, [m,] move_x, move_y, move_z
        # the numbers 0 0 0 (0 or 1 each for false and true) following the coordinates of the atom
        #   means this atom is allowed or not to move in the three directions three numbers,
        #   which take value in 0 or 1, control how the atom moved in geometry relaxation calculations

        # construct atom position dict
        atom_position_dict = {}
        # each key-value pair: key is the kind name, value is a list of atom positions and other parameters
        # this should be given as inputs!

        coordinates = [site.position for site in structure.sites]

        ### BELOW are mandatory keywords!!!###
        # that is even though no 'm' KEYWORD is given, this set of params still need to be given
        # KEYWORD m: the atom is allowed to move in geometry relaxation calculations
        # like [[True, True, True]]
        move_list = parameters.get("m")  # default value for move_x, move_y, move_z
        if move_list is None:
            # Default to move the atoms
            move_list = [[True, True, True]] * len(coordinates)

        ### BELOW are optional keywords!!!###
        # KEYWORD mag or magmom: set the start magnetization for each atom
        # set three number for the xyz commponent of magnetization here (e.g. mag 0.0 0.0 1.0).

        magmom_list = parameters.get("mag") or parameters.get("magmom", [])  # default value for mag_x, mag_y, mag_z

        # Add and count atoms.
        # The following three lines tells the elemental type (Fe),
        # the initial magnetic moment (1.0),
        # and the number of atoms for this particular element (2) repsectively.
        for i, (site, site_coords) in enumerate(zip(structure.sites, coordinates)):
            kind_name = site.kind_name
            position = [*site_coords]

            # Add the move flags
            flags = map(int, move_list[i])  # Ensure int type
            position.extend(["m", *flags])  # Set the move flag for geometry optimization

            # each position is a line containing the following information:
            # In colinear case only one number should be given.
            # In non-colinear case set three number for the xyz commponent of magnetization here
            # (e. g. mag 0.0 0.0 1.0).
            # Note that if this parameter is set, the initial magnetic moment setting will be overrided.
            if magmom_list:
                magmom_float = map(float, magmom_list[i])  # Ensure float type
                position.extend(["magmom", *magmom_float])  # mag or magmom: set the start magnetization for each atom.

            # Other STRU key word parameters parser can be added here.

            if kind_name not in atom_position_dict:
                atom_position_dict[kind_name] = {
                    "number_of_atoms": 1,
                    # Initial magnetic moment can be defined by a dictionary under the key 'initial_magnetic_moment'
                    "initial_magnetic_moment": parameters.get("initial_magnetic_moment", {}).get(kind_name, 0.0),
                    "positions": [],
                }
            else:
                atom_position_dict[kind_name]["number_of_atoms"] += 1
            atom_position_dict[kind_name]["positions"].append(position)

        # write atom_position_dict into atom_positions
        for kind_name, kind_dict in atom_position_dict.items():
            mag = kind_dict["initial_magnetic_moment"]
            natoms = kind_dict["number_of_atoms"]
            atom_positions.append(f"{kind_name}\n{mag}\n{natoms}")
            for position in kind_dict["positions"]:
                atom_positions.append(" ".join(map(str, position)))

        structure_list.extend(atom_positions)

        # Join the structure_list into a single string
        # print("structure_list is:", structure_list)
        structure_content = "\n".join(structure_list)
        return structure_content, local_copy_list_to_append

    def write_stru(self, stru_file):
        """
        Write the structure file STRU.
        :return: a list of pseudopotential files to be copied
        """
        stru_dict = self.inputs.parameters.get("stru", {})
        structure_content, local_pseudo_copy_list = self.generate_structure(
            self.inputs.structure, self.inputs.pseudos, stru_dict
        )
        with open(stru_file, "w") as handle:
            handle.write(structure_content)
        return local_pseudo_copy_list
