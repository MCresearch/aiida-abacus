"""
Utilities for converting ASE constraints to ABACUS "m" key in STRU file.

This module provides functions to convert ASE constraint objects (FixAtoms, FixCartesian)
into ABACUS's "m" key in the STRU file.
"""

from __future__ import annotations

from typing import Union

import numpy as np
from aiida import orm
from aiida.common.exceptions import InputValidationError
from aiida.orm.nodes.data.base import to_aiida_type
from ase import Atoms
from ase.constraints import FixAtoms, FixCartesian, FixScaled


def atoms_to_move_list(atoms: Atoms) -> np.ndarray | None:
    """
    Convert ASE constraints to ABACUS move_list format.

    This function extracts FixAtoms and FixCartesian constraints from an ASE Atoms object
    and converts them to ABACUS's selective dynamics format (the "m" keyword in STRU file).
    Multiple constraints are properly accumulated using a union of restrictions.

    :param atoms: ASE Atoms object with optional constraints
    :type atoms: Atoms
    :returns: Numpy array of shape (N, 3) with dtype=bool, where True means the atom
        can move in that direction (ABACUS convention: True→1, False→0), False means fixed.
        Returns None if no constraints are present.
    :rtype: np.ndarray | None
    :raises InputValidationError: If an unsupported constraint type is encountered (e.g., FixScaled)

    .. note::
        - Supports FixAtoms (fixes all 3 directions) and FixCartesian (fixes Cartesian directions).
        - ASE mask convention (True=fixed) is automatically inverted to ABACUS
          convention (True=movable, converted to 1 in STRU file).
        - ABACUS selective dynamics operates in Cartesian directions.
        - FixScaled is NOT supported - use FixCartesian instead.
        - Multiple constraints on the same atom are accumulated (union of restrictions).

    Example::

        >>> from ase import Atoms
        >>> from ase.constraints import FixAtoms
        >>> atoms = Atoms('H2O', positions=[[0,0,0], [1,0,0], [0,1,0]])
        >>> atoms.set_constraint(FixAtoms(indices=[0]))
        >>> dof = atoms_to_move_list(atoms)
        >>> dof[0]  # First atom fixed
        array([False, False, False])
        >>> dof[1]  # Second atom free
        array([True, True, True])
    """
    # Return None if no constraints
    if not atoms.constraints:
        return None

    # Initialize all atoms as movable (True = movable in ABACUS, converted to 1 in STRU)
    natoms = len(atoms)
    move_list = np.ones((natoms, 3), dtype=bool)

    # Process each constraint
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            # FixAtoms: fix all 3 directions for specified atoms
            indices = constraint.get_indices()
            move_list[indices, :] = False

        elif isinstance(constraint, FixScaled):
            # FixScaled is NOT supported - ABACUS selective dynamics uses Cartesian directions
            raise InputValidationError(
                "FixScaled constraint is not supported for ABACUS calculations. "
                "ABACUS selective dynamics operates in Cartesian directions. "
                "Please use FixCartesian instead to constrain specific Cartesian directions."
            )

        elif isinstance(constraint, FixCartesian):
            # FixCartesian: fix specific Cartesian directions
            # ABACUS selective dynamics operates in Cartesian directions
            # ASE mask convention: True = fixed, False = movable
            # ABACUS convention: True = movable, False = fixed (converted to 1/0 in STRU file)
            indices = constraint.get_indices()
            mask = constraint.mask  # ASE convention: True = fixed

            # Invert mask: where ASE mask is True (fixed), set ABACUS move flag to False (fixed)
            fixed_directions = np.where(mask)[0]
            move_list[np.ix_(indices, fixed_directions)] = False

        else:
            # Unsupported constraint type
            constraint_type = type(constraint).__name__
            raise InputValidationError(
                f"Unsupported constraint type '{constraint_type}'. "
                f"Only FixAtoms and FixCartesian are supported for ABACUS selective dynamics. "
                f"For complex constraints, manually specify the 'dynamics' port with a move_list array."
            )

    return move_list


def serialize_dynamics(atoms: Union[Atoms, dict]) -> orm.Dict | None:
    """
    Serialize ASE Atoms with constraints to dynamics Dict for builder.dynamics port.

    This is a convenience function that converts ASE constraints to an AiiDA Dict
    node ready for direct use with the builder.dynamics port. The output Dict
    contains the "m" key corresponding to ABACUS STRU file's move flags.

    :param atoms: ASE Atoms object with optional constraints, or dict to pass through
    :type atoms: Union[Atoms, dict]
    :returns: orm.Dict with "m" key containing move flags, or None if no constraints.
        The Dict is ready for direct assignment: ``builder.dynamics = serialize_dynamics(atoms)``
    :rtype: orm.Dict | None

    .. note::
        Handles FixAtoms and FixCartesian constraints. Multiple constraints
        are properly accumulated (union of restrictions). FixScaled is NOT
        supported - use FixCartesian instead.

        The output format is: ``{"m": [[bool, bool, bool], ...]}`` where True means
        movable (converted to 1 in STRU file) and False means fixed (converted to 0),
        matching ABACUS's convention.

        Additionally supports velocity through dict input: ``{"m": [...], "v": [...]}``
        where the "v" key contains velocity vectors in atomic units (1 a.u. = 21.877 Å/fs).

    Example::

        >>> from ase.build import bulk
        >>> from ase.constraints import FixAtoms
        >>> from aiida_abacus.utils import serialize_dynamics
        >>>
        >>> atoms = bulk("Si", "diamond", a=5.43).repeat((2, 2, 2))
        >>> atoms.set_constraint(FixAtoms(indices=[0, 1, 2, 3]))
        >>>
        >>> # Direct usage with builder
        >>> builder.dynamics = serialize_dynamics(atoms)

    Example with velocity::

        >>> from aiida_abacus.utils import serialize_dynamics
        >>> from aiida import orm
        >>>
        >>> # With velocities for molecular dynamics
        >>> builder.dynamics = serialize_dynamics({
        ...     "m": [[True, True, True]] * 4,
        ...     "v": [[0.1, 0.0, 0.0]] * 4  # velocities in a.u.
        ... })
    """
    if not isinstance(atoms, Atoms):
        return to_aiida_type(atoms)

    # Get move_list array
    move_list = atoms_to_move_list(atoms)

    # Return None if no constraints
    if move_list is None:
        return None

    # Convert to Dict node (tolist() converts numpy array to JSON-serializable list)
    return orm.Dict(dict={"m": move_list.tolist()})
