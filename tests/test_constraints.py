"""Tests for ASE constraints to ABACUS move flags conversion."""

import numpy as np
import pytest
from aiida import orm
from aiida.common.exceptions import InputValidationError
from aiida_abacus.utils import atoms_to_move_list, serialize_dynamics
from ase import Atoms
from ase.constraints import FixAtoms, FixBondLength, FixCartesian, FixScaled


# Fixtures
@pytest.fixture
def h3_atoms():
    """Three hydrogen atoms in a line."""
    return Atoms("H3", positions=[[i, 0, 0] for i in range(3)], cell=[5, 5, 5])


# FixAtoms tests
def test_fixatoms_basic():
    """Test FixAtoms fixes all 3 directions."""
    atoms = Atoms("H3", positions=[[i, 0, 0] for i in range(3)])
    atoms.set_constraint(FixAtoms(indices=[0, 2]))

    move_list = atoms_to_move_list(atoms)

    assert not np.any(move_list[0])  # Atom 0 fixed
    assert np.all(move_list[1])  # Atom 1 free
    assert not np.any(move_list[2])  # Atom 2 fixed


def test_no_constraints_returns_none():
    """Test that atoms without constraints return None."""
    atoms = Atoms("H2", positions=[[0, 0, 0], [1, 0, 0]])
    assert atoms_to_move_list(atoms) is None


# FixScaled tests - should raise error
def test_fixscaled_raises_error(h3_atoms):
    """Test that FixScaled constraint raises an error."""
    h3_atoms.set_constraint(FixScaled([1], mask=(True, False, True)))

    with pytest.raises(InputValidationError, match="FixScaled constraint is not supported"):
        atoms_to_move_list(h3_atoms)


# FixCartesian tests
def test_fixcartesian_basic(h3_atoms):
    """Test FixCartesian with partial constraints."""
    h3_atoms.set_constraint(FixCartesian([1], mask=(True, False, True)))

    move_list = atoms_to_move_list(h3_atoms)

    np.testing.assert_array_equal(move_list[0], [True, True, True])
    np.testing.assert_array_equal(move_list[1], [False, True, False])  # x,z fixed
    np.testing.assert_array_equal(move_list[2], [True, True, True])


def test_fixcartesian_mask_inversion():
    """Test ASE mask convention (True=fixed) inverts to ABACUS (True=movable)."""
    atoms = Atoms("H2", positions=[[0, 0, 0], [1, 0, 0]], cell=[5, 5, 5])
    atoms.set_constraint(FixCartesian([1], mask=(True, True, False)))

    move_list = atoms_to_move_list(atoms)

    # ASE mask (True, True, False) = fix x,y → ABACUS (False, False, True)
    np.testing.assert_array_equal(move_list[1], [False, False, True])


# Multiple constraints
def test_multiple_fixatoms():
    """Test multiple FixAtoms constraints accumulate."""
    atoms = Atoms("H4", positions=[[i, 0, 0] for i in range(4)])
    atoms.set_constraint([FixAtoms(indices=[0]), FixAtoms(indices=[2, 3])])

    move_list = atoms_to_move_list(atoms)

    assert not np.any(move_list[0])  # Fixed
    assert np.all(move_list[1])  # Free
    assert not np.any(move_list[2])  # Fixed
    assert not np.any(move_list[3])  # Fixed


def test_mixed_fixatoms_and_fixcartesian():
    """Test FixAtoms + FixCartesian combine correctly."""
    atoms = Atoms("H4", positions=[[i, 0, 0] for i in range(4)], cell=[5, 5, 5])
    atoms.set_constraint([FixAtoms(indices=[0]), FixCartesian([1], mask=(False, True, False))])

    move_list = atoms_to_move_list(atoms)

    np.testing.assert_array_equal(move_list[0], [False, False, False])
    np.testing.assert_array_equal(move_list[1], [True, False, True])
    np.testing.assert_array_equal(move_list[2], [True, True, True])


def test_overlapping_fixcartesian_constraints():
    """Test overlapping FixCartesian constraints use union of restrictions."""
    atoms = Atoms("H2", positions=[[0, 0, 0], [1, 0, 0]], cell=[5, 5, 5])
    atoms.set_constraint(
        [
            FixCartesian([1], mask=(True, False, False)),  # Fix x
            FixCartesian([1], mask=(False, True, False)),  # Fix y
        ]
    )

    move_list = atoms_to_move_list(atoms)
    np.testing.assert_array_equal(move_list[1], [False, False, True])  # x,y fixed


# Error handling
def test_unsupported_constraint_raises():
    """Test unsupported constraint types raise error."""
    atoms = Atoms("H2O", positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    atoms.set_constraint(FixBondLength(0, 1))

    with pytest.raises(InputValidationError, match="Unsupported constraint"):
        atoms_to_move_list(atoms)


# Serialization tests
def test_serialize_dynamics_with_constraints(aiida_profile_clean):
    """Test serialize_dynamics converts constraints to Dict."""
    atoms = Atoms("H3", positions=[[i, 0, 0] for i in range(3)])
    atoms.set_constraint(FixAtoms(indices=[0]))

    result = serialize_dynamics(atoms)

    assert isinstance(result, orm.Dict)
    assert result.get_dict()["m"] == [
        [False, False, False],
        [True, True, True],
        [True, True, True],
    ]


def test_serialize_dynamics_no_constraints(aiida_profile_clean):
    """Test serialize_dynamics returns None for unconstrained atoms."""
    atoms = Atoms("H2", positions=[[0, 0, 0], [1, 0, 0]])
    assert serialize_dynamics(atoms) is None


def test_serialize_dynamics_dict_passthrough(aiida_profile_clean):
    """Test serialize_dynamics passes through dict inputs."""
    input_dict = {"m": [[True, True, True]]}
    result = serialize_dynamics(input_dict)

    assert isinstance(result, orm.Dict)
    assert result.get_dict() == input_dict


# Edge cases
def test_single_atom():
    """Test single atom structure."""
    atoms = Atoms("H", positions=[[0, 0, 0]])
    atoms.set_constraint(FixAtoms(indices=[0]))

    move_list = atoms_to_move_list(atoms)
    np.testing.assert_array_equal(move_list, [[False, False, False]])


def test_large_structure():
    """Test constraint on large structure."""
    natoms = 100
    atoms = Atoms("H" * natoms, positions=[[i, 0, 0] for i in range(natoms)])
    atoms.set_constraint(FixAtoms(indices=list(range(0, natoms, 2))))

    move_list = atoms_to_move_list(atoms)

    assert move_list.shape == (natoms, 3)
    assert not np.any(move_list[0::2])  # Even indices fixed
    assert np.all(move_list[1::2])  # Odd indices free


def test_empty_atoms():
    """Test empty atoms object."""
    assert atoms_to_move_list(Atoms()) is None


# Integration test
def test_boolean_to_abacus_format():
    """Test boolean move_list converts to ABACUS 0/1 format."""
    atoms = Atoms("H3", positions=[[i, 0, 0] for i in range(3)])
    atoms.set_constraint(FixAtoms(indices=[1]))

    move_list = atoms_to_move_list(atoms)
    abacus_flags = move_list.astype(int)

    expected = np.array([[1, 1, 1], [0, 0, 0], [1, 1, 1]])
    np.testing.assert_array_equal(abacus_flags, expected)


# ==============================================================================
# Velocity Tests
# ==============================================================================


def test_velocity_in_dynamics_dict(aiida_profile_clean):
    """Test velocity can be specified in dynamics Dict."""
    velocities = [[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [-0.1, 0.0, 0.0]]

    dynamics_dict = {"v": velocities}
    result = serialize_dynamics(dynamics_dict)

    assert isinstance(result, orm.Dict)
    assert result.get_dict()["v"] == velocities


def test_velocity_with_move_flags(aiida_profile_clean):
    """Test velocity and move flags can be combined."""
    dynamics_dict = {
        "m": [[True, True, True], [False, False, False], [True, True, True]],
        "v": [[0.1, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.1, 0.0]],
    }

    result = serialize_dynamics(dynamics_dict)

    assert isinstance(result, orm.Dict)
    assert result.get_dict()["m"] == dynamics_dict["m"]
    assert result.get_dict()["v"] == dynamics_dict["v"]


def test_velocity_aliases(aiida_profile_clean):
    """Test all velocity aliases are supported."""
    velocities = [[0.1, 0.0, 0.0]]

    for alias in ["v", "vel", "velocity"]:
        dynamics_dict = {alias: velocities}
        result = serialize_dynamics(dynamics_dict)
        assert result.get_dict()[alias] == velocities
