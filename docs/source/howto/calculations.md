# Calculations

This page provides guidance on setting up and running ABACUS calculations with AiiDA.

## Using ASE Constraints for Selective Dynamics

AiiDA-ABACUS supports ASE constraints for controlling which atoms can move during geometry optimization. Constraints are automatically converted to ABACUS's selective dynamics format (the `m` keyword in the STRU file).

### Quick Start

```python
from ase.build import bulk
from ase.constraints import FixAtoms
from aiida.orm import StructureData

# Create structure with constraints
atoms = bulk("Si", "diamond", a=5.43).repeat((2, 2, 2))
atoms.set_constraint(FixAtoms(indices=[0, 1, 2, 3]))  # Fix first 4 atoms

# Use with builder - constraints are automatically handled
builder.structure = StructureData(ase=atoms)
builder.dynamics = atoms  # This converts constraints to ABACUS format
```

### Supported Constraint Types

AiiDA-ABACUS supports two ASE constraint types. ABACUS selective dynamics operates in Cartesian directions.

#### FixAtoms

Fixes all three directions (x, y, z) for specified atoms:

```python
from ase.constraints import FixAtoms

# Fix atoms by index
atoms.set_constraint(FixAtoms(indices=[0, 1, 2]))
```

**Use case:** Surface slabs where you want to fix the bottom layers that represent the bulk substrate.

#### FixCartesian

Fixes specific Cartesian directions:

```python
from ase.constraints import FixCartesian

# Fix x and y directions, allow z
atoms.set_constraint(FixCartesian(
    indices=[3, 4],
    mask=(True, True, False)  # True = fixed, False = movable
))
```

**Important:** ASE uses `True=fixed`, but ABACUS uses `1=movable`. The conversion is automatic.

**Use case:** Constraining motion along specific Cartesian directions, such as fixing the z-coordinate for surface atoms while allowing xy relaxation.

**Note:** FixScaled is NOT supported - ABACUS selective dynamics uses Cartesian directions. Use FixCartesian instead.

### Multiple Constraints

You can combine multiple constraints - restrictions are accumulated (union):

```python
from ase.constraints import FixAtoms, FixCartesian

constraint1 = FixAtoms(indices=[0, 1])  # Fix atoms 0, 1 completely
constraint2 = FixCartesian([2, 3], mask=(False, False, True))  # Fix z for atoms 2, 3

atoms.set_constraint([constraint1, constraint2])
```

### Three Ways to Specify Selective Dynamics

There are three methods to control which atoms can move (in priority order):

#### 1. ASE Atoms via dynamics port (NEW, recommended)

```python
from ase.build import bulk
from ase.constraints import FixAtoms

atoms = bulk("Si").repeat((2, 2, 2))
atoms.set_constraint(FixAtoms(indices=[0, 1]))
builder.dynamics = atoms  # Automatic conversion
```

**Advantages:**
- Most intuitive and Pythonic
- Leverages ASE's well-documented constraint system
- Type-safe with proper validation
- Automatic mask convention inversion

#### 2. Manual dynamics Dict (NEW, explicit control)

```python
builder.dynamics = orm.Dict({
    "m": [
        [True, True, True],    # Atom 0: fully movable
        [False, False, False], # Atom 1: fully fixed
        [True, True, False],   # Atom 2: xy movable, z fixed
    ]
})
```

**Advantages:**
- Explicit control over each degree of freedom
- No dependency on ASE
- Direct mapping to ABACUS format

#### 3. Legacy parameters approach (EXISTING, backwards compatible)

```python
builder.parameters = orm.Dict({
    "input": {...},
    "stru": {
        "m": [[True, True, True], [False, False, False], ...]
    }
})
```

**Priority resolution:**
- If `builder.dynamics` is provided → uses it (highest priority)
- Else if `parameters["stru"]["m"]` exists → uses it (legacy fallback)
- Else → defaults to all atoms movable (ABACUS default)

**Important:** An error will be raised if you specify the `m` flags in both `builder.dynamics` and `parameters["stru"]["m"]` to avoid ambiguity. Use only one method.

This ensures zero breaking changes while providing a superior user experience.

### ABACUS Format Details

Internally, constraints are converted to ABACUS STRU file format:
- `True` (movable) → `1` in STRU file
- `False` (fixed) → `0` in STRU file

Example STRU file content:
```
Si
0.0
2
0.00 0.00 0.00 m 0 0 0    # Fixed atom (cannot move)
0.25 0.25 0.25 m 1 1 1    # Movable atom (can move in all directions)
```

### Troubleshooting

**Issue:** Constraints not being applied

**Solution:** Make sure you're passing ASE Atoms to `builder.dynamics`.


**Issue:** Error about specifying 'm' flags in both dynamics and parameters

**Solution:** You cannot specify selective dynamics in both places. Choose one method: either `builder.dynamics` (recommended) or `parameters["stru"]["m"]` (legacy).

**Issue:** How to check if constraints were converted correctly?

**Solution:** Use the `serialize_dynamics` function to verify:
```python
from aiida_abacus.utils import serialize_dynamics

dynamics_dict = serialize_dynamics(atoms)
print(dynamics_dict.get_dict())
# Shows: {"m": [[True, True, True], [False, False, False], ...]}
```

### Related Documentation

- **ABACUS STRU format**: https://abacus.deepmodeling.com/en/latest/advanced/input_files/stru.html
- **ASE constraints**: https://wiki.fysik.dtu.dk/ase/ase/constraints.html

### API Reference

For detailed API documentation, see:
- `aiida_abacus.utils.atoms_to_move_list()` - Convert ASE constraints to move_list
- `aiida_abacus.utils.serialize_dynamics()` - Serialize for builder.dynamics port
