"""
Calculations provided by aiida_abacus.

Register calculations via the "aiida.calculations" entry point in setup.json.
"""

import os

from aiida import orm
from aiida.common import datastructures, exceptions
from aiida.common.utils import get_unique_filename
from aiida.engine import CalcJob
from aiida.plugins import DataFactory
from aiida_pseudo.data.pseudo.upf import UpfData

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
            help="""Additional control parameters for how AiiDA behaves for this calculation.
                   Available options includes: additional_retrieve_list, excluded_retrieve_list,
                   retrieve_charge_density, include_kpoints, include_internal_parameters
                   """,
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

        # misc stands for miscellaneous, which is some of
        # the scalar outputs or small vectors (e.g., energy, forces, stress) of the calculation.
        # extracted from the output file OUT.aiida/running_scf.log
        # results will be stored in a Dict node.
        spec.output(
            "misc",
            valid_type=orm.Dict,
            help="The scalar outputs or" "small vectors (e.g., energy, forces, stress) of the calculation.",
        )

        # abacus_output, which is a Str
        spec.output("abacus_output", valid_type=orm.Str, help="The raw ABACUS output file content.")

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

        # retrieve the output folder OUT.aiida
        # Gather the list of the files to be retrieved/included
        settings = {} if "settings" in self.inputs else self.inputs.settings
        calcinfo.retrieve_list = [
            self._ABACUS_OUTPUT,
            *make_retrieve_list(self.inputs.parameters, settings, self._OUTPUT_SUFFIX),
        ]

        print("to be retrieved:", calcinfo.retrieve_list)

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
        # parameters.pseudo_dir = self._PSEUDO_SUBFOLDER

        input_content = self.generate_input(parameters["input"])
        with open(input_file, "w") as handle:
            handle.write(input_content)

    def write_kpoints(self, kpt_file):
        """Write the kpoints file KPT."""
        kpt_list = [
            "K_POINTS",  # kewyword for start
            "0",  # total number of k-point, `0' means generate automatically
            "Gamma",  # which kind of Monkhorst-Pack method, `Gamma' or `MP'
            # here we need six numbers,
            # first three number: subdivisions along reciprocal vectors
            # last three number: shift of the mesh
        ]

        # validation adapted from aiida-quantumespresso\src\aiida_quantumespresso\calculations\__init__.py
        try:
            # Mesh of kpoints: List[int]
            # Offset of the mesh: List[float]
            mesh, offset = self.inputs.kpoints.get_kpoints_mesh()
        except AttributeError as exceptions:
            raise exceptions.InputValidationError("No mesh found in KpoitnsData.")
        if any([i not in [0, 0.5] for i in offset]):
            raise exceptions.InputValidationError("offset list must only be made of 0 or 0.5 floats")

        # Convert offset to integers (0 or 1)
        the_offset = [0 if i == 0.0 else 1 for i in offset]

        kpt_list.append(f"{' '.join(map(str, mesh + the_offset))}\n")

        with open(kpt_file, "w") as handle:
            handle.write("\n".join(kpt_list))

    def generate_structure(self, structure, pseudos, parameters) -> str:
        """Generate the content of input file STRU according to structure.
        For detailed documentation,
        see the `ABACUS Input Guide <https://abacus.deepmodeling.com/en/latest/advanced/input_files/stru.html>`_.
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

            try:
                # If it is the same pseudopotential file, use the same filename
                filename = pseudo_filenames[pseudo.pk]
            except KeyError:
                # The pseudo was not encountered yet; use a new name and also add it to the local copy list
                filename = get_unique_filename(pseudo.filename, list(pseudo_filenames.values()))
                pseudo_filenames[pseudo.pk] = filename
                local_copy_list_to_append.append(
                    (pseudo.uuid, pseudo.filename, os.path.join(self._PSEUDO_SUBFOLDER, filename))
                )

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

        # LATTICE_CONSTANT section
        # The lattice constant of the system in unit of Bohr.
        print("parameter is:", parameters)
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

        # from ase/io/onetep.py
        # 1.889726134583548707935
        lattice_const_in_bohr = 1.8897259886  # 1.8897259886 Bohr =  1.0 Angstrom
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
            "Direct",  # The first line signifies method that atom positions are given, e.g. Cartesian or Direct.
            # next lines are atom-specific information, processed in the following code
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
        move_list = parameters["m"]  # default value for move_x, move_y, move_z

        ### BELOW are optional keywords!!!###
        # KEYWORD mag or magmom: set the start magnetization for each atom
        # set three number for the xyz commponent of magnetization here (e.g. mag 0.0 0.0 1.0).

        magmom_list = parameters.get("mag") or parameters.get("magmom", [])  # default value for mag_x, mag_y, mag_z

        # Ensure the length of the magnetic moment list is consistent with the number of atoms
        # (fill in empty lists if insufficient)
        if magmom_list:
            if len(magmom_list) != len(structure.sites):
                #  fill in the default value if the length of the magnetic moment list is insufficient
                magmom_list += [[] for _ in range(len(structure.sites) - len(magmom_list))]
        else:  # empty list
            magmom_list = [[] for _ in range(len(structure.sites))]

        # Add and count atoms.
        # The following three lines tells the elemental type (Fe),
        # the initial magnetic moment (1.0),
        # and the number of atoms for this particular element (2) repsectively.
        for site, site_coords, moves, magmoms in zip(structure.sites, coordinates, move_list, magmom_list):
            kind_name = site.kind_name
            move_int = [int(i) for i in moves]

            # process magnetic moment (if exists)
            magmom_float = []
            if magmoms:  # if magmom is not empty
                magmom_float = [float(i) for i in magmoms]  # 转换为浮点数

            # each position is a line containing the following information:
            position = [
                *site_coords,
                "m",  # m or NO key word: three numbers, which take value in 0 or 1,
                # control how the atom move in geometry relaxation calculations.
                *move_int,
            ]
            # if magmom_float is not empty, add magnetic moment information
            if magmom_float:
                position.extend(
                    [
                        "magmom",  # mag or magmom: set the start magnetization for each atom.
                        *magmom_float,
                    ]
                )  # In colinear case only one number should be given.
                # In non-colinear case set three number for the xyz commponent of magnetization here
                # (e. g. mag 0.0 0.0 1.0).
                # Note that if this parameter is set, the initial magnetic moment setting will be overrided.

            # Other STRU key word parameters parser can be added here.

            if kind_name not in atom_position_dict:
                atom_position_dict[kind_name] = {
                    "number_of_atoms": 1,
                    # need to add magnetism into readin parameters
                    "initial_magnetic_moment": 0.0,
                    "positions": [],
                }
            else:
                atom_position_dict[kind_name]["number_of_atoms"] += 1
            atom_position_dict[kind_name]["positions"].append(position)

        # write atom_position_dict into atom_positions
        for kind_name, kind_dict in atom_position_dict.items():
            atom_positions.append(
                f"{kind_name}\n{kind_dict["initial_magnetic_moment"]}\n{kind_dict['number_of_atoms']}"
            )
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
        structure_content, local_pseudo_copy_list = self.generate_structure(
            self.inputs.structure, self.inputs.pseudos, self.inputs.parameters["stru"]
        )
        with open(stru_file, "w") as handle:
            handle.write(structure_content)
        return local_pseudo_copy_list
