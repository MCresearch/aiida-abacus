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

DiffParameters = DataFactory("abacus")
LegacyUpfData = DataFactory('core.upf')
UpfData = DataFactory('pseudo.upf')


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
            "num_mpiprocs_per_machine": 1,
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

        # dynamic pseudopotential input port namespace, adapted from aiida-castep
        spec.input_namespace(
            "pseudos",
            help=(
                "Use nodes for the pseudopotentails of one of the element in the structure."
                "Pass a dictionary specifying the pseudpotential node for each kind,"
                "such as {O: <PsudoNode>}."
            ),
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
        INPUT = folder.get_abs_path("INPUT")
        KPT = folder.get_abs_path("KPT")
        STRU = folder.get_abs_path("STRU")

        self.write_input(INPUT)
        self.write_kpoints(KPT)
        self.write_stru(STRU)

        codeinfo = datastructures.CodeInfo()
        # codeinfo.cmdline_params = self.inputs.parameters.cmdline_params(
        #     file1_name=self.inputs.file1.filename, file2_name=self.inputs.file2.filename
        # )

        # no cmdline params needed
        codeinfo.cmdline_params = []
        codeinfo.code_uuid = self.inputs.code.uuid
        codeinfo.stdout_name = self.metadata.options.output_filename

        # Prepare a `CalcInfo` to be returned to the engine
        calcinfo = datastructures.CalcInfo()
        calcinfo.codes_info = [codeinfo]
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
        :return: the content of the input file STRU"""
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
        atomic_species = ["ATOMIC_SPECIES\n"]
        # for species in structure_data["atomic_species"]:
        #     structure_list.append(f"{species['label']} {species['mass']} {species['pseudo_file']} {species['pseudo_type']}")
        # I keep track of the order of species
        kind_names = []
        # I add the pseudopotential files to the list of files to be copied
        for kind in structure.kinds:
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
            atomic_species.append(f'{kind.name.ljust(6)} {kind.mass} {filename}\n')

        structure_list.extend(atomic_species)



        # NUMERICAL_ORBITAL section
        # Numerical atomic orbitals are only needed for LCAO calculations.
        # This section will be neglected in calcultions with plane wave basis.
        # structure_list.append("\nNUMERICAL_ORBITAL\n")
        # for orbital in structure["numerical_orbital"]:
        #     structure_list.append(orbital)
        

        # LATTICE_CONSTANT section
        # The lattice constant of the system in unit of Bohr.
        # structure_list.append("\nLATTICE_CONSTANT\n")
        # structure_list.append(f"{structure['lattice_constant']}")

        # LATTICE_VECTORS section
        # This section is only relevant when latname (see input parameters) is used to specify the Bravais lattice type.
        # structure_list.append("\nLATTICE_VECTORS\n")
        # for vector in structure["lattice_vectors"]:
        #     structure_list.append(" ".join(map(str, vector)))
        lattice_vectors = ["LATTICE_VECTORS\n"]
        for vector in structure.cell:
            lattice_vectors.extend([f"{vector[0]:20}{vector[1]:20}{vector[2]:20}"])

        # ATOMIC_POSITIONS section
        # This section specifies the positions and other information of individual atoms.
        atom_positions = ["ATOMIC_POSITIONS\n"]
        structure_list.append("\nATOMIC_POSITIONS\n")
        structure_list.append(structure["atomic_positions"]["coordinate_type"])
        for element, magnetism, count, positions in structure["atomic_positions"]["atoms"]:
            structure_list.append(f"{element} {magnetism} {count}")
            for pos in positions:
                structure_list.append(" ".join(map(str, pos)))

        # Join the structure_list into a single string
        structure_content = "\n".join(structure_list)
        return structure_content

        # for site in structure.sites:
        #     # The longest parameter is 'bessel_descriptor_tolerence' with 27 characters.
        #     structure_list.append(f"{site.kind_name:<30}{site.position[0]:<20}{site.position[1]:<20}{site.position[2]:<20}")
        # structure_content = "\n".join(structure_list)
        return structure_list
    
    def write_stru(self, stru_file):
        """Write the structure file STRU."""
        structure_content = self.generate_structure(self.inputs.structure.get_dict())
        with open(stru_file, "w") as handle:
            handle.write(structure_content)
    

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
