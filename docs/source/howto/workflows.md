---
myst:
  substitutions:
    AbacusBaseInputGenerator: "{py:class}`AbacusBaseInputGenerator <aiida_abacus.protocols.AbacusBaseInputGenerator>`"
    AbacusRelaxInputGenerator: "{py:class}`AbacusRelaxInputGenerator <aiida_abacus.protocols.AbacusRelaxInputGenerator>`"
    AbacusBandInputGenerator: "{py:class}`AbacusBandInputGenerator <aiida_abacus.protocols.AbacusBandInputGenerator>`"
---

(howto-workflows)=

# Protocol-driven workflow builders

`aiida-abacus` ships protocol-driven input generators that pre-populate AiiDA builders with recommended defaults. They are useful when you want to launch a workchain without filling every input port by hand.

The generators live in `aiida_abacus.protocols` and wrap the standard AiiDA `WorkflowFactory(...).get_builder_from_protocol(...)` pattern with a lighter, user-facing interface.

## Available generators

The current public generators are:

- {py:class}`AbacusBaseInputGenerator <aiida_abacus.protocols.AbacusBaseInputGenerator>` for `AbacusBaseWorkChain`
- {py:class}`AbacusRelaxInputGenerator <aiida_abacus.protocols.AbacusRelaxInputGenerator>` for `AbacusRelaxWorkChain`
- {py:class}`AbacusBandInputGenerator <aiida_abacus.protocols.AbacusBandInputGenerator>` for `AbacusBandWorkChain`

Each generator starts from a named preset and protocol, then applies any runtime overrides on top.

## Protocols and presets

Protocol data is stored as YAML files under `src/aiida_abacus/protocols/`.
The default preset is `src/aiida_abacus/protocols/presets/default.yaml`, which defines the default code, options, and workflow-specific defaults such as relax and band settings.

The generator looks for presets in three places:

- the package data shipped with `aiida-abacus`
- user-defined files under `~/.aiida-abacus/presets/`
- legacy user-defined files under `~/.aiida-abacus/protocol_presets/`

This makes it possible to keep site-specific settings outside the source tree while still using the same public Python API.

## Basic usage

```python
from aiida import orm
from aiida_abacus.protocols import AbacusRelaxInputGenerator

structure = orm.StructureData(...)  # supply your structure here

generator = AbacusRelaxInputGenerator(preset_name="default", protocol="balanced")
builder = generator.build(
    structure=structure,
    code="abacus@localhost",
)

generator.set_label("silicon-relax")
generator.set_resources(num_machines=1, tot_num_mpiprocs=4)
generator.set_options(max_wallclock_seconds=3600)
```

After `build(...)` returns, the generator keeps a reference to the builder and can update common ports through helper methods such as:

- `set_options(...)`
- `set_resources(...)`
- `set_settings(...)`
- `set_input(...)`
- `set_kpoints_distance(...)`
- `set_kpoints_mesh(...)`
- `set_pseudo_family(...)`
- `set_code(...)`

Use `submit()` to launch the workflow on the daemon, or `run_get_node()` for local execution during development.

## Relax and band helpers

The specialized generators expose a small number of workflow-specific ports:

- `AbacusRelaxInputGenerator.set_relax_settings(...)` updates the relaxation settings namespace.
- `AbacusBandInputGenerator.set_band_settings(...)` updates the band-structure settings namespace.

Both classes also apply their workflow defaults from the active preset when those defaults are defined in the YAML file.

## Practical notes

The generators are intended to reduce boilerplate, not to hide the underlying builder.
You can always inspect or further modify the returned builder before submission if a calculation needs manual adjustments.

For ABACUS-specific input details, see the [calculations how-to](calculations.md) and [pseudopotential guide](pseudos.md).
