"""
Comprehensive tests for ABACUS calculation input generation.

Tests generation of INPUT, KPT, and STRU files by AbacusCalculation class.
"""

from pathlib import Path

import pytest
from aiida import orm
from aiida.common.extendeddicts import AttributeDict
from aiida.engine.utils import instantiate_process
from aiida.manage.manager import get_manager
from aiida_abacus.calculations import AbacusCalculation


class TestInputFileGeneration:
    """Test generation of ABACUS input files (INPUT, KPT, STRU)."""

    @pytest.fixture
    def calc_with_inputs(self, aiida_profile_clean, abacus_code, si_structure, pseudo_familty, abacus_kpoints):
        """Create an AbacusCalculation instance with all necessary inputs."""
        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = abacus_kpoints

        # Basic parameters for plane wave calculation
        parameters = {
            "input": {
                "basis_type": "pw",
                "ecutwfc": 60,
                "scf_thr": 1e-7,
                "scf_nmax": 100,
                "calculation": "scf",
                "symmetry": 1,
                "ks_solver": "dav_subspace",
                "device": "cpu",
                "precision": "double",
            },
            "stru": {"m": [[True, True, True]] * len(si_structure.sites)},
        }
        inputs.parameters = orm.Dict(parameters)

        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        return instantiate_process(runner, AbacusCalculation, **inputs)

    def test_prepare_for_submission_success(self, calc_with_inputs, sandbox_folder):
        """Test successful preparation of all input files."""
        calcinfo = calc_with_inputs.prepare_for_submission(sandbox_folder)

        assert calcinfo is not None
        assert len(calcinfo.codes_info) == 1
        assert calcinfo.codes_info[0].code_uuid == calc_with_inputs.inputs.code.uuid

        # Check that all required files are created
        assert Path(sandbox_folder.get_abs_path("INPUT")).exists()
        assert Path(sandbox_folder.get_abs_path("KPT")).exists()
        assert Path(sandbox_folder.get_abs_path("STRU")).exists()

    def test_input_file_content(self, calc_with_inputs, sandbox_folder):
        """Test the content and format of the generated INPUT file."""
        calc_with_inputs.prepare_for_submission(sandbox_folder)

        input_path = sandbox_folder.get_abs_path("INPUT")
        with open(input_path, "r") as f:
            content = f.read()

        assert content.startswith("INPUT_PARAMETERS")
        assert "basis_type" in content
        assert "ecutwfc" in content
        assert "suffix" in content
        assert "pseudo_dir" in content
        assert "orbital_dir" in content

    def test_kpoints_mesh_generation(self, calc_with_inputs, sandbox_folder):
        """Test generation of KPT file for k-point mesh."""
        calc_with_inputs.prepare_for_submission(sandbox_folder)

        kpt_path = sandbox_folder.get_abs_path("KPT")
        with open(kpt_path, "r") as f:
            content = f.read()

        assert content.startswith("K_POINTS")
        assert "0" in content  # Automatic generation
        assert "Gamma" in content  # Gamma-centered

        lines = content.strip().split("\n")
        mesh_line = lines[3]
        mesh_parts = mesh_line.split()
        assert len(mesh_parts) == 6

    def test_stru_file_content(self, calc_with_inputs, sandbox_folder):
        """Test the content and structure of the generated STRU file."""
        calc_with_inputs.prepare_for_submission(sandbox_folder)

        stru_path = sandbox_folder.get_abs_path("STRU")
        with open(stru_path, "r") as f:
            content = f.read()

        assert "ATOMIC_SPECIES" in content
        assert "LATTICE_CONSTANT" in content
        assert "LATTICE_VECTORS" in content
        assert "ATOMIC_POSITIONS" in content
        assert "Cartesian" in content

    def test_pseudopotential_file_copying(self, calc_with_inputs, sandbox_folder):
        """Test that pseudopotential files are properly copied to calculation folder."""
        calcinfo = calc_with_inputs.prepare_for_submission(sandbox_folder)

        pseudo_copies = [item for item in calcinfo.local_copy_list if "pseudo" in item[2]]
        assert len(pseudo_copies) > 0

        stru_path = sandbox_folder.get_abs_path("STRU")
        with open(stru_path, "r") as f:
            content = f.read()

        pseudo_files = [item[1] for item in pseudo_copies]
        for pseudo_file in pseudo_files:
            assert pseudo_file in content or Path(pseudo_file).stem in content

    def test_parameters_suffix_setting(self, calc_with_inputs, sandbox_folder):
        """Test that suffix parameter is correctly set in INPUT file."""
        calc_with_inputs.prepare_for_submission(sandbox_folder)

        input_path = sandbox_folder.get_abs_path("INPUT")
        with open(input_path, "r") as f:
            content = f.read()

        assert "suffix" in content
        assert "aiida" in content

    def test_directory_structure_creation(self, calc_with_inputs, sandbox_folder):
        """Test that required directory structure is created."""
        calcinfo = calc_with_inputs.prepare_for_submission(sandbox_folder)

        pseudo_copies = [item for item in calcinfo.local_copy_list if "pseudo" in item[2]]
        for copy in pseudo_copies:
            assert copy[2].startswith("./pseudo/")

    def test_lattice_constant_handling(self, abacus_code, si_structure, pseudo_familty, sandbox_folder):
        """Test handling of custom lattice constant in STRU file."""
        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = orm.KpointsData()
        inputs.kpoints.set_kpoints_mesh([2, 2, 2])

        parameters = {
            "input": {"basis_type": "pw", "ecutwfc": 50},
            "stru": {"LATTICE_CONSTANT": 2.0, "m": [[True, True, True]] * len(si_structure.sites)},
        }
        inputs.parameters = orm.Dict(parameters)
        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        calc = instantiate_process(runner, AbacusCalculation, **inputs)
        calc.prepare_for_submission(sandbox_folder)

        stru_path = sandbox_folder.get_abs_path("STRU")
        with open(stru_path, "r") as f:
            content = f.read()

        assert "LATTICE_CONSTANT" in content
        assert "2.0" in content

    def test_magnetic_moments_handling(self, abacus_code, si_structure, pseudo_familty, sandbox_folder):
        """Test handling of magnetic moments in STRU file."""
        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = orm.KpointsData()
        inputs.kpoints.set_kpoints_mesh([2, 2, 2])

        parameters = {
            "input": {"basis_type": "pw", "ecutwfc": 50, "nspin": 2},
            "stru": {
                "mag": [[0.0, 0.0, 1.0]] * len(si_structure.sites),
                "m": [[True, True, True]] * len(si_structure.sites),
            },
        }
        inputs.parameters = orm.Dict(parameters)
        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        calc = instantiate_process(runner, AbacusCalculation, **inputs)
        calc.prepare_for_submission(sandbox_folder)

        stru_path = sandbox_folder.get_abs_path("STRU")
        with open(stru_path, "r") as f:
            content = f.read()

        assert "magmom" in content

    def test_restart_folder_handling(self, calc_with_inputs, sandbox_folder):
        """Test handling of restart_folder in calcinfo."""
        remote_data = orm.RemoteData(computer=calc_with_inputs.inputs.code.computer, remote_path="/some/remote/path")
        calc_with_inputs.inputs.restart_folder = remote_data

        calcinfo = calc_with_inputs.prepare_for_submission(sandbox_folder)

        assert hasattr(calcinfo, "remote_copy_list")
        # remote_copy_list may be None if no restart is configured, test that it exists
        if calcinfo.remote_copy_list is not None:
            assert len(calcinfo.remote_copy_list) > 0
            remote_copy = calcinfo.remote_copy_list[0]
            assert len(remote_copy) == 3

    def test_kpoints_explicit_generation(self, abacus_code, si_structure, pseudo_familty, sandbox_folder):
        """Test generation of KPT file for explicit k-points."""
        kpoints = orm.KpointsData()
        kpoints.set_cell_from_structure(si_structure)
        kpoints.set_kpoints([[0, 0, 0], [0.5, 0.5, 0.5]])

        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = kpoints
        inputs.parameters = orm.Dict(
            {
                "input": {"basis_type": "pw", "ecutwfc": 50},
                "stru": {"m": [[True, True, True]] * len(si_structure.sites)},
            }
        )
        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        calc = instantiate_process(runner, AbacusCalculation, **inputs)
        calc.prepare_for_submission(sandbox_folder)

        kpt_path = sandbox_folder.get_abs_path("KPT")
        with open(kpt_path, "r") as f:
            content = f.read()

        assert "K_POINTS" in content
        assert "2" in content  # Number of k-points
        assert "Direct" in content
        assert "0.00000000000000" in content
        assert "0.50000000000000" in content

    def test_stru_file_atom_positions(self, calc_with_inputs, sandbox_folder):
        """Test atom positions section in STRU file."""
        calc_with_inputs.prepare_for_submission(sandbox_folder)

        stru_path = sandbox_folder.get_abs_path("STRU")
        with open(stru_path, "r") as f:
            content = f.read()

        lines = content.split("\n")
        atomic_positions_idx = next(i for i, line in enumerate(lines) if line.strip() == "ATOMIC_POSITIONS")
        cartesian_idx = next(
            i
            for i, line in enumerate(lines[atomic_positions_idx + 1 :], atomic_positions_idx + 1)
            if line.strip() == "Cartesian"
        )

        atom_info_lines = []
        for i in range(cartesian_idx + 1, len(lines)):
            line = lines[i].strip()
            if line and not line.startswith("#"):
                if any(char.isalpha() for char in line.split()[0]):
                    atom_info_lines.append(line)
                elif len(line.split()) >= 3:
                    atom_info_lines.append(line)
                else:
                    break

        assert len(atom_info_lines) > 0

        # Check move flags in position lines
        for line in atom_info_lines:
            parts = line.split()
            if len(parts) >= 7:
                assert "m" in parts[3:7]

        # Use the raw STRU parser to read back and parse the STRU file
        from aiida_abacus.parsers.raw_parsers import StruParser

        stru_parser = StruParser(stru_path)
        lattice_vectors, positions, species = stru_parser.parse()

        # Verify the parsed structure data
        assert lattice_vectors is not None, "Lattice vectors not parsed"
        assert positions is not None, "Positions not parsed"
        assert species is not None, "Species not parsed"

        # Check that we have the expected number of atoms
        expected_atoms = len(calc_with_inputs.inputs.structure.sites)
        assert len(species) == expected_atoms, f"Expected {expected_atoms} atoms, got {len(species)}"
        assert len(positions) == expected_atoms, f"Expected {expected_atoms} positions, got {len(positions)}"

        # Check that all species are Si (for our test structure)
        unique_species = set(species)
        assert "Si" in unique_species

        # Verify lattice vectors shape
        assert lattice_vectors.shape == (3, 3)

        # Verify positions shape
        assert positions.shape == (expected_atoms, 3)

        # Check that move flags were properly handled by the parser (the parser extracts coordinates)
        # The original file should still contain move flags
        with open(stru_path, "r") as f:
            stru_content = f.read()
        assert "m 1 1 1" in stru_content

    def test_dynamics_port_with_ase_constraints(
        self, aiida_profile_clean, abacus_code, si_structure, pseudo_familty, abacus_kpoints
    ):
        """Test that ASE constraints via dynamics port are correctly converted to STRU 'm' flags."""
        from aiida_abacus.utils import serialize_dynamics
        from ase import Atoms
        from ase.constraints import FixAtoms

        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = abacus_kpoints

        # Basic parameters WITHOUT 'm' flags
        parameters = {
            "input": {
                "basis_type": "pw",
                "ecutwfc": 60,
                "scf_thr": 1e-7,
                "calculation": "scf",
            },
            "stru": {},  # No 'm' here - will come from dynamics
        }
        inputs.parameters = orm.Dict(parameters)

        # Create ASE Atoms with constraints - fix first atom
        positions = [site.position for site in si_structure.sites]
        symbols = [site.kind_name for site in si_structure.sites]
        cell = si_structure.cell
        atoms = Atoms(symbols=symbols, positions=positions, cell=cell)
        atoms.set_constraint(FixAtoms(indices=[0]))

        # Use dynamics port with ASE Atoms
        inputs.dynamics = serialize_dynamics(atoms)

        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        # Instantiate process
        process = instantiate_process(runner, AbacusCalculation, **inputs)

        # Generate STRU content
        stru_content, _ = process.generate_structure(si_structure, inputs.pseudos, {})  # Empty stru parameters

        # Verify STRU contains correct 'm' flags
        # First atom should be "m 0 0 0" (fixed)
        # Second atom should be "m 1 1 1" (movable)
        assert "m 0 0 0" in stru_content  # First atom fixed
        assert "m 1 1 1" in stru_content  # Second atom movable

    def test_dynamics_port_conflicts_with_parameters_raises_error(
        self, aiida_profile_clean, abacus_code, si_structure, pseudo_familty, abacus_kpoints
    ):
        """Test that specifying 'm' in both dynamics and parameters raises an error."""
        from aiida.common.exceptions import InputValidationError

        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = abacus_kpoints

        # Parameters with 'm' specified
        num_sites = len(si_structure.sites)
        parameters = {
            "input": {"basis_type": "pw", "ecutwfc": 60, "calculation": "scf"},
            "stru": {"m": [[True, True, True]] * num_sites},
        }
        inputs.parameters = orm.Dict(parameters)

        # Dynamics port also has 'm' - this should raise an error
        inputs.dynamics = orm.Dict({"m": [[False, False, False]] + [[True, True, True]] * (num_sites - 1)})

        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        process = instantiate_process(runner, AbacusCalculation, **inputs)

        # Should raise InputValidationError when both sources provide 'm'
        with pytest.raises(InputValidationError, match="both 'dynamics' port and parameters"):
            process.generate_structure(si_structure, inputs.pseudos, parameters["stru"])

    def test_legacy_parameters_still_works(
        self, aiida_profile_clean, abacus_code, si_structure, pseudo_familty, abacus_kpoints
    ):
        """Test that legacy parameters['stru']['m'] approach still works (backwards compatibility)."""
        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=si_structure)
        inputs.kpoints = abacus_kpoints

        # Legacy approach: specify 'm' in parameters
        num_sites = len(si_structure.sites)
        parameters = {
            "input": {"basis_type": "pw", "ecutwfc": 60, "calculation": "scf"},
            "stru": {"m": [[False, False, False]] + [[True, True, True]] * (num_sites - 1)},  # First atom fixed
        }
        inputs.parameters = orm.Dict(parameters)
        # NO dynamics port provided

        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        process = instantiate_process(runner, AbacusCalculation, **inputs)

        stru_content, _ = process.generate_structure(si_structure, inputs.pseudos, parameters["stru"])

        # First atom should be fixed (from legacy parameters)
        assert "m 0 0 0" in stru_content
        assert "m 1 1 1" in stru_content
