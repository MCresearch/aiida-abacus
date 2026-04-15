# Concepts

This section explains key concepts behind aiida-abacus and how it integrates with the AiiDA workflow management system.

Understanding these concepts will help you make the most of aiida-abacus for your computational materials science workflows. While detailed conceptual guides are under development, the resources below provide essential background information.

## Key Concepts

### ABACUS and AiiDA Integration

Learn how the ABACUS DFT package integrates with AiiDA's workflow engine to enable automated, reproducible calculations with full data provenance.

**Resources**:
- [AiiDA Documentation](https://aiida.readthedocs.io/projects/aiida-core/en/latest/) - Understanding AiiDA's workflow engine and data provenance
- [ABACUS Documentation](https://abacus.deepmodeling.com/) - ABACUS DFT package documentation
- [ABACUS User Guide](https://mcresearch.github.io/abacus-user-guide/) - Comprehensive ABACUS tutorials and guides

### Pseudopotentials and Orbitals

Understand what pseudopotentials and numerical atomic orbitals are, why ABACUS needs both for LCAO calculations, and how collections differ from families.

**Resources**:
- [Managing Pseudopotentials and Orbitals](../howto/pseudos.md) - Practical guide to working with pseudos and orbitals
- [APNS Database](https://aissquare.com/datasets/detail?pageType=datasets&name=ABACUS-APNS-PPORBs-v1) - ABACUS Pseudopotential-NAO Square database

### Data Provenance

AiiDA automatically tracks the full provenance of all calculations, recording inputs, outputs, and metadata in a queryable graph structure. This ensures reproducibility and enables powerful data analysis workflows.

**Resources**:
- [AiiDA Provenance](https://aiida.readthedocs.io/projects/aiida-core/en/latest/topics/provenance/index.html) - Understanding data provenance in AiiDA
- [AiiDA Tutorials](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/basics.html#provenance) - Working with the provenance graph

### Plugin Architecture

aiida-abacus extends AiiDA through its plugin system, providing custom data types, calculation classes, and parsers specifically for ABACUS calculations.

**Resources**:
- [AiiDA Plugin Development](https://aiida.readthedocs.io/projects/aiida-core/en/latest/topics/plugins.html) - How AiiDA plugins work
- [aiida-abacus Source Code](https://github.com/MCresearch/aiida-abacus) - Plugin implementation

### Protocol-Driven Input Generators

The workflow builders in `aiida-abacus` can be initialized from predefined protocol presets instead of manually wiring every input port. This keeps launch scripts short while still allowing runtime overrides for code, structure, resources, and workflow-specific settings.

**Resources**:
- [Protocol-driven workflow builders](../howto/workflows.md) - User-facing guide to `AbacusBaseInputGenerator`, `AbacusRelaxInputGenerator`, and `AbacusBandInputGenerator`
- The implementation lives in `src/aiida_abacus/protocols/generator.py` and the preset YAML files under `src/aiida_abacus/protocols/`

## Note

Detailed conceptual guides with diagrams and in-depth explanations are under development. For now, please refer to the external resources linked above and the how-to guides for practical information. If you have questions or would like to contribute to expanding this section, please see our [Contributing](../contributing.md) guide.
