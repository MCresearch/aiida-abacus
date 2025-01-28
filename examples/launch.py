"""Launch a calculation using the 'diff-tutorial' plugin"""

from pathlib import Path

from aiida import engine, orm
from aiida.orm import Dict, KpointsData, StructureData, load_code, load_group
from aiida.common.exceptions import NotExistent
from aiida.plugins import CalculationFactory, DataFactory
import numpy as np

INPUT_DIR = Path(__file__).resolve().parent / 'input_files'
print(f'Input files directory: {INPUT_DIR}')

DiffParameters = DataFactory("abacus")
parameters = DiffParameters({"ignore-case": True})
# parameters = {"ignore-case": True}


# Create or load code
computer = orm.load_computer('localhost')
# try:
#     code = orm.load_code('diff@localhost')
# except NotExistent:
#     # Setting up code via python API (or use "verdi code setup")
#     code = orm.InstalledCode(
#         label='diff', computer=computer,
#         filepath_executable='/usr/bin/diff',
#         default_calc_job_plugin='abacus'
#     )
code = orm.InstalledCode(
    label='diff', computer=computer,
    filepath_executable='~/.local/bin/abacus',
    default_calc_job_plugin='abacus'
)

# Set up inputs
builder = code.get_builder()


# STRU
# adadpted from aiida-vasp
# StructureData = DataFactory('core.structure')
# /miniconda3/envs/aiida/lib/python3.12/site-packages/aiida/plugins/entry_point.py:350:
# AiidaDeprecationWarning: The entry point `structure` is deprecated.
# Please replace it with `core.structure`. (this will be removed in v3)
a = 3.092
c = 5.073
lattice = [[a, 0, 0], [-a / 2, a / 2 * np.sqrt(3), 0], [0, 0, c]]
structure = StructureData(cell=lattice)

# KPT
# KpointsData = DataFactory('core.array.kpoints')
# The entry point `array.kpoints` is deprecated.
# Please replace it with `core.array.kpoints`. (this will be removed in v3)
kpoints = KpointsData()
kpoints.set_kpoints_mesh([6, 6, 4], offset=[0, 0, 0.5])


pseudo_family = load_group('SSSP/1.1/PBE/efficiency')
builder.pseudos = pseudo_family.get_pseudos(structure=structure)


builder.structure = structure
builder.kpoints = kpoints
builder.metadata.description = 'Test job submission with the aiida_abacus plugin'

# Run the calculation & parse results
result = engine.run(builder, parameters=parameters)
computed_diff = result['abacus'].get_content()
print(f'Computed diff between files:\n{computed_diff}')
