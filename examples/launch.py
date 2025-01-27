"""Launch a calculation using the 'diff-tutorial' plugin"""

from pathlib import Path

from aiida import engine, orm
from aiida.common.exceptions import NotExistent
from aiida.plugins import CalculationFactory, DataFactory
import numpy as np

INPUT_DIR = Path(__file__).resolve().parent / 'input_files'
print(f'Input files directory: {INPUT_DIR}')

DiffParameters = DataFactory("abacus")
parameters = DiffParameters({"ignore-case": True})
# parameters = {"ignore-case": True}

# STRU
# adadpted from aiida-vasp
StructureData = DataFactory('structure')
a = 3.092
c = 5.073
lattice = [[a, 0, 0], [-a / 2, a / 2 * np.sqrt(3), 0], [0, 0, c]]
structure = StructureData(cell=lattice)

# KPT
KpointsData = DataFactory('array.kpoints')
kpoints = KpointsData()
kpoints.set_kpoints_mesh([6, 6, 4], offset=[0, 0, 0.5])

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
# builder.file1 = orm.SinglefileData(file=INPUT_DIR / 'file1.txt')
# builder.file2 = orm.SinglefileData(file=INPUT_DIR / 'file2.txt')
builder.structure = structure
builder.kpoints = kpoints
builder.metadata.description = 'Test job submission with the aiida_abacus plugin'

# Run the calculation & parse results
result = engine.run(builder, parameters=parameters)
computed_diff = result['abacus'].get_content()
print(f'Computed diff between files:\n{computed_diff}')
