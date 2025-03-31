from aiida import orm
from aiida.engine import run_get_node
from aiida_abacus.workflows import AbacusRelaxWorkChain
from ase.build import bulk

Si2 = bulk("Si", "diamond", 5.4)
structure = orm.StructureData(ase=Si2)
computer = orm.load_computer("localhost")

code = orm.load_code("abacus@localhost")

builder = AbacusRelaxWorkChain.get_builder_from_protocol(code, structure, protocol="fast")

# The options of the calculation still needs to be set manually
builder.base.abacus.metadata.options = {
    "resources": {
        "num_machines": 1,
        "num_mpiprocs_per_machine": 1,  # use 1 cores per machine
    },
    "max_wallclock_seconds": 180,  # how long it can run before it should be killed
    # 'withmpi': False, # Set withmpi to False in case abacus was compiled without MPI support.
}
builder.base_final_scf.abacus.metadata.options = {
    "resources": {
        "num_machines": 1,
        "num_mpiprocs_per_machine": 1,  # use 1 cores per machine
    },
    "max_wallclock_seconds": 180,  # how long it can run before it should be killed
    # 'withmpi': False, # Set withmpi to False in case abacus was compiled without MPI support.
}

results, node = run_get_node(builder)

misc = results["misc"].get_dict()
print(f"Miscellaneous: {misc}")
retrieved = results["retrieved"]
print(f"Retrieved files: {retrieved.list_object_names()}")
remote_folder = results["remote_folder"].entry_point  # .get_remote_path()
print(f"Remote folder entry_point: {remote_folder}")

print("Calc launch over.")
