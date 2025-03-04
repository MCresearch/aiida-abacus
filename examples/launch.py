"""Launch a calculation using the 'aiida-abacus' plugin"""
# We will use the abacus-develop/examples/scf/pw_Si2 directory as an example

from pathlib import Path

from aiida import engine, orm
from aiida.orm import Dict, KpointsData, StructureData, load_code, load_group
from aiida.common.exceptions import NotExistent
from aiida.plugins import CalculationFactory, DataFactory
import numpy as np


###
# set up code
computer = orm.load_computer('localhost')

# try:
#     code = orm.load_code('abacus@localhost')
# except NotExistent:
#     # Setting up code via python API (or use "verdi code setup")
#     code = orm.InstalledCode(
#         label='abacus', computer=computer,
#         filepath_executable='abacus',
#         default_calc_job_plugin='abacus'
#     )

code = orm.InstalledCode(
    label='abacus', computer=computer,
    filepath_executable='abacus',
    default_calc_job_plugin='abacus.abacus'
)


builder = code.get_builder()

builder.metadata.options = {
    'resources': {
        'num_machines': 1,
        "num_mpiprocs_per_machine": 1, # use 1 cores per machine
    },
    'max_wallclock_seconds': 180, # how long it can run before it should be killed
    # 'withmpi': False, # Set withmpi to False in case abacus was compiled without MPI support.
}

###
# set up inputs
"""
INPUT_PARAMETERS
#Parameters  (General)
pseudo_dir      ./pseudo/
symmetry        1
#Parameters  (Accuracy)
basis_type      pw
ecutwfc         60  ###Energy cutoff needs to be tested to ensure your calculation is reliable.[1]
scf_thr         1e-7
scf_nmax        100
device          cpu
ks_solver       dav_subspace
precision       double

### [1] Energy cutoff determines the quality of numerical quadratures in your calculations.
###     So it is strongly recommended to test whether your result (such as converged SCF energies) is
###     converged with respect to the energy cutoff.
"""

'''
#Parameters (1.General)
suffix                  Si
calculation             scf
symmetry                1
pseudo_dir              .
orbital_dir             .
basis_type              pw
ecutwfc                 100

#Parameters (2. SCF iterations)
scf_nmax                100
scf_thr                 1e-8

#Parameters (3. Solve KS equation)
nbands                  26
ks_solver               cg

#Parameters (4.Smearing)
smearing_method         gauss
smearing_sigma          0.01

#Parameters (5.Mixing)
mixing_type             broyden
mixing_beta             0.7
mixing_gg0              0
'''
# input_parameters = {
#     'calculation': 'scf',
# }
input_parameters = {
    # pseudo_dir will be set by the plugin based on the pseudos
    # 'symmetry': 1,
    'basis_type': 'pw',
    'ecutwfc': 100,
    'scf_thr': 1e-4, #1e-7,
    # 'scf_nmax': 100,
    'device': 'cpu',
    # 'ks_solver': 'dav_subspace',
    # 'precision': 'double',
}


###
# set up structure
"""
#This is the atom file containing all the information
#about the lattice structure.

ATOMIC_SPECIES
Si 1.000 Si.pz-vbc.UPF 	#Element, Mass, Pseudopotential

LATTICE_CONSTANT
10.2  			#Lattice constant

LATTICE_VECTORS
0.5 0.5 0.0 		#Lattice vector 1
0.5 0.0 0.5 		#Lattice vector 2
0.0 0.5 0.5 		#Lattice vector 3

ATOMIC_POSITIONS
Cartesian 		#Cartesian(Unit is LATTICE_CONSTANT)
Si 			#Name of element
0.0			#Magnetic for this element.
2			#Number of atoms
0.00 0.00 0.00 0 0 0	#x,y,z, move_x, move_y, move_z
0.25 0.25 0.25 1 1 1
"""
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


# STRU
# adadpted from aiida-vasp
# StructureData = DataFactory('core.structure')
# /miniconda3/envs/aiida/lib/python3.12/site-packages/aiida/plugins/entry_point.py:350:
# AiidaDeprecationWarning: The entry point `structure` is deprecated.
# Please replace it with `core.structure`. (this will be removed in v3)
a = 3.092
c = 5.073
lattice = [[a, 0, 0], [-a / 2, a / 2 * np.sqrt(3), 0], [0, 0, c]]
# structure = StructureData(cell=lattice)
from ase.build import bulk
structure = StructureData(ase=bulk('Si', 'fcc', 5.43))

# structure parameters
stru_settings ={
    "LATTICE_CONSTANT": 1.8897261258369282,
    # KEYWORD m : whether or not allowed to move in geometry relaxation calculations.
    # three numbers, which take value in 0 or 1, control how the atom move in geometry relaxation calculations. 
    "m": [[True, True, True]],
    # KEYWORD mag or magmom : set the start magnetization for each atom.
    # In colinear case only one number should be given.
    # In non-colinear case set three number for the xyz commponent of magnetization here (e. g. mag 0.0 0.0 1.0).
    # Note that if this parameter is set, the initial magnetic moment setting will be overrided.
    "mag": [[0.0, 0.0, 0.0]],
}

# KPT
# KpointsData = DataFactory('core.array.kpoints')
# The entry point `array.kpoints` is deprecated.
# Please replace it with `core.array.kpoints`. (this will be removed in v3)
kpoints = KpointsData()
kpoints.set_kpoints_mesh([6, 6, 4], offset=[0, 0, 0.5]) # default cartesian=False
#! note that according to aiida.orm.nodes.data.array.kpoints.KpointsData:
# Internally, all k-points are defined in terms of crystal (fractional) coordinates.
# Cell and lattice vector coordinates are in Angstroms, reciprocal lattice vectors in Angstrom^-1 .

###
# prepare pseudos with aiida-pseudo
pseudo_family = load_group('SSSP/1.1/PBE/efficiency')
builder.pseudos = pseudo_family.get_pseudos(structure=structure)



all_parameters = {
    "input": input_parameters,
    "stru": stru_settings,
}

builder.structure = structure
builder.kpoints = kpoints
builder.settings = stru_settings
builder.metadata.description = 'Test job submission with the aiida_abacus plugin'

parameters = Dict(dict=all_parameters)
# Run the calculation & print results
results, node = engine.run.get_node(builder, parameters=parameters)
misc = results['misc'].get_dict()
print(f'Miscellaneous: {misc}')
retrieved = results['retrieved']
print(f'Retrieved files: {retrieved.list_object_names()}')
remote_folder = results['remote_folder'].entry_point #.get_remote_path()
print(f'Remote folder entry_point: {remote_folder}')

print("Calc launch over.")
