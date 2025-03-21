"""Launch a calculation using the 'aiida-abacus' plugin"""
# Minimal example to launch a calculation using the 'aiida-abacus' plugin on a remote computer.

from aiida import orm
from aiida.engine import submit
from aiida.orm import Dict, KpointsData, StructureData, load_group
from ase.build import bulk

###
# set up code
# you can use workstation with slurm
# or direct
computer = orm.load_computer("direct")  # station # direct


code = orm.InstalledCode(
    label="abacus", computer=computer, filepath_executable="abacus", default_calc_job_plugin="abacus.abacus"
)


builder = code.get_builder()

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

input_parameters = {
    "basis_type": "pw",
    "ecutwfc": 100,
    "scf_thr": 1e-4,
    "device": "cpu",
}


###
# set up structure

# STRU


structure = StructureData(ase=bulk("Si", "fcc", 5.43))

# structure parameters
stru_settings = {
    "LATTICE_CONSTANT": 1.8897261258369282,
    "m": [[True, True, True]],
    "mag": [[0.0, 0.0, 0.0]],
}

# KPT
# KpointsData = DataFactory('core.array.kpoints')

kpoints = KpointsData()
kpoints.set_kpoints_mesh([6, 6, 4], offset=[0, 0, 0.5])  # default cartesian=False
#! note that according to aiida.orm.nodes.data.array.kpoints.KpointsData:
# Internally, all k-points are defined in terms of crystal (fractional) coordinates.
# Cell and lattice vector coordinates are in Angstroms, reciprocal lattice vectors in Angstrom^-1 .

###
# prepare pseudos with aiida-pseudo
pseudo_family = load_group("PseudoDojo/0.4/PBE/SR/standard/upf")
builder.pseudos = pseudo_family.get_pseudos(structure=structure)


all_parameters = {
    "input": input_parameters,
    "stru": stru_settings,
}

builder.structure = structure
builder.kpoints = kpoints
builder.settings = stru_settings
builder.metadata.description = "Test job submission with the aiida_abacus plugin"

parameters = Dict(dict=all_parameters)
# Run the calculation & print results
builder.metadata.description = "remote calculation."

# submit
print(submit(builder, parameters=parameters))

# or run
# results, node = engine.run.get_node(builder, parameters=parameters)
# misc = results['misc'].get_dict()
# print(f'Miscellaneous: {misc}')
# retrieved = results['retrieved']
# print(f'Retrieved files: {retrieved.list_object_names()}')
# remote_folder = results['remote_folder'].entry_point #.get_remote_path()
# print(f'Remote folder entry_point: {remote_folder}')

print("Calc launch over.")
