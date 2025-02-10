"""
Calculations provided by aiida_abacus.

Register calculations via the "aiida.calculations" entry point in setup.json.
"""

import os
from aiida.common import datastructures, exceptions
from aiida.common.utils import get_unique_filename
from aiida.engine import CalcJob
from aiida import orm
from aiida.orm import SinglefileData
from aiida.plugins import DataFactory

from aiida_pseudo.data.pseudo.upf import UpfData

import numpy as np

# DiffParameters = DataFactory("abacus.abacus")
LegacyUpfData = DataFactory('core.upf')
# UpfData = DataFactory('pseudo.upf')


class DiffCalculation(CalcJob):
    """
    AiiDA calculation plugin wrapping ABACUS calculation.

    """

    _PSEUDO_SUBFOLDER = "./pseudo/" # default pesudopotential folder
    _ORBITAL_SUBFOLDER = "./orbital/" # default orbital folder
    _OUTPUT_SUFFIX = "aiida" # default output suffix
    _OUTPUT_SUBFOLDER = "OUT." + _OUTPUT_SUFFIX # default output folder
    _DEFAULT_RETRIEVE_LIST = [
        _OUTPUT_SUBFOLDER
    ]

    @classmethod
    def define(cls, spec):
        """Define inputs and outputs of the calculation."""
        super().define(spec)

        # set default values for AiiDA options
        spec.inputs["metadata"]["options"]["resources"].default = {
            "num_machines": 1,
            "num_mpiprocs_per_machine": 1, # use 1 cores per machine by default
        }
        # entry point for parser
        spec.inputs["metadata"]["options"]["parser_name"].default = "abacus.abacus"

        # new ports
        # spec.input("metadata.options.output_filename", valid_type=str, default="patch.diff")
        # spec.input(
        #     "parameters",
        #     valid_type=DiffParameters,
        #     help="Command line parameters for diff",
        # )
        # spec.input("file1", valid_type=SinglefileData, help="First file to be compared.")
        # spec.input("file2", valid_type=SinglefileData, help="Second file to be compared.")
        # spec.output(
        #     "abacus",
        #     valid_type=SinglefileData,
        #     help="diff between file1 and file2.",
        # )

        spec.input('metadata.options.withmpi', valid_type=bool, default=True)

        # structural data for 3 Input file for ABACUS calculation
        # see https://abacus.deepmodeling.com/en/latest/quick_start/input.html for detail

        spec.input("parameters", valid_type=orm.Dict, help="The ABACUS input parameters INPUT.")
        spec.input("kpoints", valid_type=orm.KpointsData, help="The kpoints KPT.")
        spec.input("structure", valid_type=orm.StructureData, help="The input structure STRU.")
        # STRU contains some parameters that 

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
        spec.output("misc", valid_type=orm.Dict,
                    help="The scalar outputs or"
                    "small vectors (e.g., energy, forces, stress) of the calculation.")

        spec.exit_code(
            300,
            "ERROR_MISSING_OUTPUT_FILES",
            message="Calculation did not produce all expected output files.",
        )

    def prepare_for_submission(self, folder):
        """
        Create input files.

        :param folder: an `aiida.common.folders.Folder` where the plugin should temporarily place all files
            needed by the calculation.
        :return: `aiida.common.datastructures.CalcInfo` instance
        """
        local_copy_list = []

        INPUT = folder.get_abs_path("INPUT")
        KPT = folder.get_abs_path("KPT")
        STRU = folder.get_abs_path("STRU")

        self.write_input(INPUT)
        self.write_kpoints(KPT)

        # self.local_pseudo_copy_list = [] # will be written in generate_structure inside write_stru
        local_pseudo_copy_list = self.write_stru(STRU)
        local_copy_list.extend(local_pseudo_copy_list)

        codeinfo = datastructures.CodeInfo()
        # codeinfo.cmdline_params = self.inputs.parameters.cmdline_params(
        #     file1_name=self.inputs.file1.filename, file2_name=self.inputs.file2.filename
        # )

        # no cmdline params needed
        codeinfo.cmdline_params = []
        codeinfo.code_uuid = self.inputs.code.uuid
        # codeinfo.stdout_name = self.metadata.options.output_filename

        # Prepare a `CalcInfo` to be returned to the engine
        calcinfo = datastructures.CalcInfo()
        calcinfo.codes_info = [codeinfo]
        
        
        calcinfo.local_copy_list = local_copy_list
        # calcinfo.local_copy_list = [
        #     (
        #         self.inputs.file1.uuid,
        #         self.inputs.file1.filename,
        #         self.inputs.file1.filename,
        #     ),
        #     (
        #         self.inputs.file2.uuid,
        #         self.inputs.file2.filename,
        #         self.inputs.file2.filename,
        #     ),
        # ]

        # retrieve the output folder OUT.aiida
        calcinfo.retrieve_list = [self._OUTPUT_SUBFOLDER]
        # print("calcinfo is:", calcinfo)
        print("retrieve:", calcinfo.retrieve_list)

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
            "INPUT_PARAMETERS" # parameter list always starts with key word INPUT_PARAMETERS
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
        parameters["suffix"] = self._OUTPUT_SUFFIX
        # parameters.suffix = "aiida"
        # folder for pseudopotentials, default is ./pseudo/
        parameters["pseudo_dir"] = self._PSEUDO_SUBFOLDER
        # parameters.pseudo_dir = self._PSEUDO_SUBFOLDER

        input_content = self.generate_input(parameters)
        with open(input_file, "w") as handle:
            handle.write(input_content)
    
    def write_kpoints(self, kpt_file):
        """Write the kpoints file KPT."""
        kpt_list = ["K_POINTS", # kewyword for start
                    "0", # total number of k-point, `0' means generate automatically
                    "Gamma", # which kind of Monkhorst-Pack method, `Gamma' or `MP'
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
            raise exceptions.InputValidationError(
                "No mesh found in KpoitnsData."
            )
        if any([i not in [0, 0.5] for i in offset]):
            raise exceptions.InputValidationError(
                "offset list must only be made of 0 or 0.5 floats"
            )
        
        # Convert offset to integers (0 or 1)
        the_offset = [0 if i == 0.0 else 1 for i in offset]

        kpt_list.append(f"{' '.join(map(str, mesh + the_offset))}\n")

        with open(kpt_file, "w") as handle:
            handle.write("\n".join(kpt_list))

    def generate_structure(self, structure, pseudos) -> str:
        """Generate the content of input file STRU according to structure.
        For detailed documentation,
        see the `ABACUS Input Guide <https://abacus.deepmodeling.com/en/latest/advanced/input_files/stru.html>`_.
        :param structure: a StructureData object
        :param pseudos: a dictionary of pseudopotential nodes
        :return: the content of the input file STRU & a list of pseudopotential files to be copied"""
        # may add some validation here, and maybe some conversions
        print("structure is:", structure)
        print("structure.kinds is:", structure.kinds)

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
        # for species in structure_data["atomic_species"]:
        #     structure_list.append(f"{species['label']} {species['mass']} {species['pseudo_file']} {species['pseudo_type']}")
        # I keep track of the order of species
        kind_names = []
        # I add the pseudopotential files to the list of files to be copied
        for kind in structure.kinds:
            print("kind is:", kind)
            print("kind.name is:", kind.name)
            # This should not give errors, I already checked before that
            # the list of keys of pseudos and kinds coincides
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
            atomic_species.append(f'{kind.name.ljust(6)} {kind.mass:^8}  {filename}')
        print("atomic_species is:", atomic_species)

        structure_list.extend(atomic_species)



        # NUMERICAL_ORBITAL section
        # Numerical atomic orbitals are only needed for LCAO calculations.
        # This section will be neglected in calcultions with plane wave basis.
        # structure_list.append("\nNUMERICAL_ORBITAL\n")
        # for orbital in structure["numerical_orbital"]:
        #     structure_list.append(orbital)
        

        # LATTICE_CONSTANT section
        # The lattice constant of the system in unit of Bohr.
        lattice_constant = ["\nLATTICE_CONSTANT"]
        print("structure.cell is:", structure.cell)
# need to be rechecked!
        # ang_to_bohr = 1.8897161646320724  # 1 Å ≈ 1.8897 Bohr
        # lengths_bohr = [np.linalg.norm(v) * ang_to_bohr for v in structure.cell]
        # lattice_const_in_bohr = max(lengths_bohr)
        # print(f"Calculated LATTICE_CONSTANT: {lattice_const_in_bohr} Bohr")
        # print("cell lengths:", structure.cell_lengths)
        lattice_const_in_bohr = 1.8897259886 		# 1.8897259886 Bohr =  1.0 Angstrom
        lattice_constant.append(str(lattice_const_in_bohr))
        structure_list.extend(lattice_constant)

        # LATTICE_VECTORS section
        # This section is only relevant when latname (see input parameters) is used to specify the Bravais lattice type.
        # structure_list.append("\nLATTICE_VECTORS\n")
        # for vector in structure["lattice_vectors"]:
        #     structure_list.append(" ".join(map(str, vector)))
        lattice_vectors = ["\nLATTICE_VECTORS"]
        for vector in structure.cell:
            lattice_vectors.extend([f"{vector[0]:20}{vector[1]:20}{vector[2]:20}"])
        structure_list.extend(lattice_vectors)

        # ATOMIC_POSITIONS section
        # This section specifies the positions and other information of individual atoms.
        atom_positions = [
            "ATOMIC_POSITIONS",
            "Direct", # The first line signifies method that atom positions are given, e.g. Cartesian or Direct.
            # next lines are atom-specific information, processed in the following code
        ]

        # structure_list.append("\nATOMIC_POSITIONS\n")
        # structure_list.append(structure["atomic_positions"]["coordinate_type"])
        # for element, magnetism, count, positions in structure["atomic_positions"]["atoms"]:
        #     structure_list.append(f"{element} {magnetism} {count}")
        #     for pos in positions:
        #         structure_list.append(" ".join(map(str, pos)))
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
        # keyword m: the atom is allowed to move in geometry relaxation calculations
        move_list = [0, 0, 0] # default value for move_x, move_y, move_z
        coordinates = [site.position for site in structure.sites]
        # Add and count atoms.
        # The following three lines tells the elemental type (Fe),
        # the initial magnetic moment (1.0),
        # and the number of atoms for this particular element (2) repsectively.
        for site, site_coords in zip(structure.sites, coordinates):
            kind_name = site.kind_name
            position = [
                *site_coords,
                'm', # m or NO key word: three numbers, which take value in 0 or 1,
                     # control how the atom move in geometry relaxation calculations. 
                *move_list
            ]
            if kind_name not in atom_position_dict:
                atom_position_dict[kind_name] = {
                    "number_of_atoms": 1,
# need to add magnetism into readin parameters
                    "initial_magnetic_moment": 1.0,
                    "positions": []
                }
            else:
                atom_position_dict[kind_name]["number_of_atoms"] += 1
            atom_position_dict[kind_name]["positions"].append(position)

        # print("atom_position_dict is:", atom_position_dict)

        # write atom_position_dict into atom_positions
        for kind_name, kind_dict in atom_position_dict.items():
            atom_positions.append(
                f"{kind_name}\n{kind_dict["initial_magnetic_moment"]}\n{kind_dict['number_of_atoms']}"
            )
            for position in kind_dict["positions"]:
                atom_positions.append(" ".join(map(str, position)))
        
        # print("atom_positions is:", atom_positions)

        # atom_positions += [
        #     '{0} {1:18.10f} {2:18.10f} {3:18.10f}'.format(site.kind_name.ljust(6), *site_coords)  # pylint: disable=consider-using-f-string
        #     for site, site_coords in zip(structure.sites, coordinates)
        # ]
        # atom_positions.append("\n")
        structure_list.extend(atom_positions)

        # Join the structure_list into a single string
        print("structure_list is:", structure_list)
        structure_content = "\n".join(structure_list)
        return structure_content, local_copy_list_to_append

        # for site in structure.sites:
        #     # The longest parameter is 'bessel_descriptor_tolerence' with 27 characters.
        #     structure_list.append(f"{site.kind_name:<30}{site.position[0]:<20}{site.position[1]:<20}{site.position[2]:<20}")
        # structure_content = "\n".join(structure_list)
        return structure_list
    
    def write_stru(self, stru_file):
        """
        Write the structure file STRU.
        :return: a list of pseudopotential files to be copied
        """
        structure_content, local_pseudo_copy_list = self.generate_structure(self.inputs.structure, self.inputs.pseudos)
        with open(stru_file, "w") as handle:
            handle.write(structure_content)
        return local_pseudo_copy_list
    

# structure_data = {
#     "atomic_species": [
#         {"label": "Si", "mass": 28.00, "pseudo_file": "Si_ONCV_PBE-1.0.upf", "pseudo_type": "upf201"}
#     ],
#     "numerical_orbital": [
#         "Si_gga_8au_60Ry_2s2p1d.orb"
#     ],
#     "lattice_constant": 10.2,
#     "lattice_vectors": [
#         [0.5, 0.5, 0.0],
#         [0.5, 0.0, 0.5],
#         [0.0, 0.5, 0.5]
#     ],
#     "atomic_positions": {
#         "coordinate_type": "Direct",
#         "atoms": [
#             ("Si", 0.0, 2, [
#                 [0.00, 0.00, 0.00, 0, 0, 0],
#                 [0.25, 0.25, 0.25, 1, 1, 1]
#             ])
#         ]
#     }
# }

# # Generate the structure file content
# file_content = generate_structure(structure_data)
# print(file_content)
