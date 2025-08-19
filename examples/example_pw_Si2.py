"""Launch a calculation using the 'aiida-abacus' plugin"""
# We will use the abacus-develop/examples/scf/pw_Si2 directory as an example
# different pseudos are referenced here!
# We will
# 1. set input parameters
# 2. generate structure
# 3. generate kpoints

import numpy as np
from aiida import engine, orm
from aiida.common.exceptions import NotExistent
from aiida.orm import Dict, KpointsData, StructureData, load_group

###
# set up computer
# You can easily switch to other computational resources you have
# including workstation, clusters, etc.

computer = orm.load_computer("localhost")


# It is possible to configure different versions of code on different computer
# and the computational results will keep this code info
try:
    code = orm.load_code("abacus@localhost")
except NotExistent:
    # Setting up code via python API (or use "verdi code setup") if not already set up
    code = orm.InstalledCode(
        label="abacus", computer=computer, filepath_executable="abacus", default_calc_job_plugin="abacus.abacus"
    )

# We will next construct the builder
builder = code.get_builder()

# This is metadata for running the calculation, including
# the resources to be used, etc.
builder.metadata.options = {
    "resources": {
        "num_machines": 1,
        "num_mpiprocs_per_machine": 1,  # use 1 cores per machine
    },
    "max_wallclock_seconds": 180,  # how long it can run before it should be killed
    # 'withmpi': False, # Set withmpi to False in case abacus was compiled without MPI support.
}

###
# set up inputs
# this is the INPUT intended
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
"""

# The INPUT above can be written into Python dictionaries as follows:
input_parameters = {
    # pseudo_dir will be set by the plugin based on the pseudos
    "symmetry": 1,
    "basis_type": "pw",
    "ecutwfc": 60,
    "scf_thr": 1e-7,
    "scf_nmax": 100,
    "device": "cpu",
    "ks_solver": "dav_subspace",
    "precision": "double",
}


###
# set up structure
"""
#This is the atom file containing all the information
#about the lattice structure.

ATOMIC_SPECIES
Si 28.0855 Si.pbe-n-rrkjus_psl.1.0.0.UPF 	#Element, Mass, Pseudopotential

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

# STRUCTURE
lattice_vectors_fractional = np.array([[0.0, 0.5, 0.5], [0.5, 0.0, 0.5], [0.5, 0.5, 0.0]])
atomic_positions_fractional = [[0.00, 0.00, 0.00], [0.25, 0.25, 0.25]]
# create StructureData
structure = StructureData(cell=lattice_vectors_fractional)
for pos in atomic_positions_fractional:
    structure.append_atom(position=pos, symbols="Si")

# structure parameters
stru_settings = {
    "LATTICE_CONSTANT": 10.2,
    # KEYWORD m : whether or not allowed to move in geometry relaxation calculations.
    "m": [[False, False, False], [True, True, True]],  # default set to True
    # KEYWORD mag or magmom : set the start magnetization for each atom.
    # "mag": [
    #     [0.0, 0.0, 0.0]
    # ],
}

# note ase API is supported by AiiDA and can be used to create structures
# from ase.build import bulk
# structure = StructureData(ase=bulk('Si', 'fcc', 5.43))

# KPT
kpoints = KpointsData()
kpoints.set_kpoints_mesh([4, 4, 4], offset=[0, 0, 0])  # default cartesian=False
#! note that according to aiida.orm.nodes.data.array.kpoints.KpointsData:
# Internally, all k-points are defined in terms of crystal (fractional) coordinates.
# Cell and lattice vector coordinates are in Angstroms, reciprocal lattice vectors in Angstrom^-1 .

###
# prepare pseudos with aiida-pseudo
pseudo_family = load_group("PseudoDojo/0.4/PBE/SR/standard/upf")
builder.pseudos = pseudo_family.get_pseudos(structure=structure)

# parameters dict used to genereate INPUT & STRU files along with structure itself
all_parameters = {
    "input": input_parameters,
    "stru": stru_settings,
}

builder.structure = structure
builder.kpoints = kpoints
builder.settings = stru_settings
builder.metadata.description = "Simple pw_Si2 job submission with the aiida_abacus plugin"

parameters = Dict(dict=all_parameters)
# Run the calculation with parameters & print results
results, node = engine.run.get_node(builder, parameters=parameters)
misc = results["misc"].get_dict()
print(f"Miscellaneous: {misc}")
print(f"Total energy is: {misc['total_energy']} eV")
retrieved = results["retrieved"]
print(f"Retrieved files: {retrieved.list_object_names()}")
remote_folder_path = results["remote_folder"].get_remote_path()
print(f"Remote folder path: {remote_folder_path}")

print("Calculation over.")
print("""
You can use
    `verdi process list -a`
to see the status of the calculation.""")
