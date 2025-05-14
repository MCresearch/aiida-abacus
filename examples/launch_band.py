"""
Example script to run a band calculation with Abacus.
"""

from aiida import engine, orm
from aiida.orm import KpointsData, StructureData, load_group
from aiida.tools import get_explicit_kpoints_path
from ase.build import bulk

computer = orm.load_computer("localhost")  # Set to your localhost computer
code = orm.load_code("abacus-3.10@localhost")  # Set to your configured abacus InstalledCode object
builder = code.get_builder()

builder.metadata.options = {
    "resources": {
        "num_machines": 1,
        "num_mpiprocs_per_machine": 4,
    },
    "max_wallclock_seconds": 180,
}

structure = StructureData(ase=bulk("Si", "fcc", 5.43))
# Generate the path
seekpathout = get_explicit_kpoints_path(structure, reference_distance=0.15)

# Configuration for SCF calculation
builder.structure = seekpathout["primitive_structure"]
builder.kpoints = KpointsData()
builder.kpoints.set_kpoints_mesh([8, 8, 8], offset=[0.5, 0.5, 0.5])
pseudo_family = load_group("PseudoDojo/0.4/PBE/SR/standard/upf")
# builder.pseudos = pseudo_family.get_pseudos(structure=structure)
builder.pseudos = {"Si": orm.load_node("49841b6d-5829-4d5b-b16f-133db53b9d4c")}
builder.parameters = {
    "input": {
        "basis_type": "lcao",
        "ecutwfc": 100,
        "scf_thr": 1e-4,  # 1e-7,
        "device": "cpu",
    }
}

# RUN SCF
results, node = engine.run.get_node(builder)

# Switch to none-scf parameters
builder.parameters = {
    "input": {
        "basis_type": "lcao",
        "ecutwfc": 100,
        "scf_thr": 1e-4,  # 1e-7,
        "device": "cpu",
        "calculation": "nscf",
    }
}
# Set the calculation to use the explicit k-points
builder.kpoints = seekpathout["explicit_kpoints"]
builder.settings = {
    "include_bands": True  # Activate band structure output TODO: make default with nscf calculation?
}
# Reuse previous calculation folder
builder.restart_folder = node.outputs.remote_folder
# Run NSCF
nscf_results, nscf_node = engine.run.get_node(builder)

# Example  plot
# nscf_node.outputs.bands.show_mpl()
print(f"NSCF calculation {nscf_node} completed")
