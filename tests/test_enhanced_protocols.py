"""
Test the enhanced protocol system and InputGenerator functionality
"""

from pathlib import Path
from types import SimpleNamespace

from aiida import orm

import aiida_abacus.protocols.generator as generator_module
from aiida_abacus.protocols.generator import (
    AbacusBandInputGenerator,
    AbacusBaseInputGenerator,
    AbacusRelaxInputGenerator,
    PresetConfig,
    list_protocol_presets,
)
from aiida_abacus.workflows.band import AbacusBandWorkChain
from aiida_abacus.workflows.base import AbacusBaseWorkChain
from aiida_abacus.workflows.relax import AbacusRelaxWorkChain


class _Namespace(SimpleNamespace):
    """Small namespace object that supports both attribute and mapping-style access."""

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def get(self, key, default=None):
        return getattr(self, key, default)


def _make_fake_builder(structure, code):
    """Create a minimal builder-like object for generator wrapper tests."""

    return _Namespace(
        structure=structure,
        metadata=_Namespace(label=None),
        abacus=_Namespace(
            structure=structure,
            code=code,
            parameters=orm.Dict({"input": {"basis_type": "pw", "ecutwfc": 60.0, "scf_thr": 1e-7}}),
            settings=orm.Dict({}),
            metadata=_Namespace(options={"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}),
        ),
        relax_settings=orm.Dict({}),
        band_settings=orm.Dict({}),
    )


def _patch_generator_helpers(monkeypatch, builder):
    """Patch the generator module to return a fake builder and predictable namespace lookups."""

    class _Factory:
        def __init__(self, _entrypoint):
            self.entrypoint = _entrypoint

        def get_builder_from_protocol(self, **_):
            return builder

    monkeypatch.setattr(generator_module, "WorkflowFactory", _Factory)
    monkeypatch.setattr(
        generator_module,
        "recursive_search_dict_with_key",
        lambda namespace, search_key: (
            [["abacus.parameters", builder.abacus.parameters]] if search_key == "input" else []
        ),
    )
    monkeypatch.setattr(
        generator_module,
        "recursive_search_port_basename",
        lambda namespace, basename: {
            "abacus": [["abacus", builder.abacus]],
            "settings": [["abacus.settings", builder.abacus.settings]],
            "relax_settings": [["relax_settings", builder.relax_settings]],
            "band_settings": [["band_settings", builder.band_settings]],
        }.get(basename, []),
    )


def test_enhanced_protocol_mixin():
    """Test the enhanced ProtocolMixin functionality"""

    # Test basic protocol listing
    base_protocols = AbacusBaseWorkChain.get_available_protocols()
    assert "balanced" in base_protocols
    assert "stringent" in base_protocols
    assert "fast" in base_protocols

    # Test default protocol
    default_protocol = AbacusBaseWorkChain.get_default_protocol()
    assert default_protocol == "balanced"

    # Test protocol file listing
    protocol_files = AbacusBaseWorkChain.list_protocol_files()
    assert len(protocol_files) > 0

    # Test protocol input generation
    inputs = AbacusBaseWorkChain.get_protocol_inputs("balanced")
    assert "abacus" in inputs
    assert "kpoints_distance" in inputs


def test_protocol_alias_support():
    """Test protocol alias support"""

    # Test that aliases work
    inputs1 = AbacusBaseWorkChain.get_protocol_inputs("moderate")
    inputs2 = AbacusBaseWorkChain.get_protocol_inputs("balanced")
    assert inputs1 == inputs2

    inputs3 = AbacusBaseWorkChain.get_protocol_inputs("precise")
    inputs4 = AbacusBaseWorkChain.get_protocol_inputs("stringent")
    assert inputs3 == inputs4


def test_preset_config():
    """Test PresetConfig functionality"""

    # Test loading default preset
    preset = PresetConfig.from_file("default")
    assert preset.name == "default"
    assert preset.default_protocol == "balanced"
    assert preset.default_code == "abacus@localhost"

    # Test code-specific options
    options = preset.get_code_specific_options("abacus@cluster", "options")
    assert "max_wallclock_seconds" in options
    assert options["max_wallclock_seconds"] == 7200

    parameters = preset.get_code_specific_options("abacus@cluster", "parameters")
    assert "input" in parameters
    assert parameters["input"]["ecutwfc"] == 80.0


def test_protocol_preset_discovery():
    """Test that the packaged protocol presets are discoverable."""

    preset_names = {path.name for path in list_protocol_presets()}

    assert {"default.yaml", "testing.yaml"} <= preset_names


def test_input_generator_basic():
    """Test basic InputGenerator functionality"""

    # Test creating a generator
    generator = AbacusBaseInputGenerator(preset_name="default")
    assert generator.preset_name == "default"
    assert generator.protocol == "balanced"

    # Test preset loading
    assert generator.preset is not None
    assert generator.preset.name == "default"


def test_base_input_generator_builds_and_tracks_reference_structure(monkeypatch, abacus_code, si_structure):
    """Test that the base generator constructs a builder and exposes the reference structure."""

    si_structure.label = "Silicon reference"

    builder = _make_fake_builder(si_structure, abacus_code)
    _patch_generator_helpers(monkeypatch, builder)

    generator = AbacusBaseInputGenerator(preset_name="testing")
    builder = generator.get_builder(
        structure=si_structure,
        code=abacus_code.label,
        protocol="balanced",
    )

    assert generator.builder is builder
    assert generator.reference_structure == si_structure
    assert builder.abacus.structure is si_structure

    generator.set_label()
    assert builder.metadata.label == "Silicon reference"


def test_relax_input_generator():
    """Test AbacusRelaxInputGenerator"""

    generator = AbacusRelaxInputGenerator(preset_name="default")
    assert generator.WF_ENTRYPOINT == "abacus.relax"

    # Test relax settings
    assert hasattr(generator.preset, "default_relax_settings")
    if generator.preset.default_relax_settings:
        assert "perform" in generator.preset.default_relax_settings


def test_relax_input_generator_applies_default_relax_settings(monkeypatch, abacus_code, si_structure):
    """Test that the relax generator applies preset relax settings to the builder."""

    builder = _make_fake_builder(si_structure, abacus_code)
    _patch_generator_helpers(monkeypatch, builder)

    generator = AbacusRelaxInputGenerator(preset_name="testing")
    builder = generator.get_builder(
        structure=si_structure,
        code=abacus_code.label,
        protocol="balanced",
    )

    assert generator.builder is builder
    assert builder.relax_settings.get_dict()["perform"] is True
    assert builder.relax_settings.get_dict()["relaxation_method"] == "cg"
    assert builder.relax_settings.get_dict()["force_cutoff"] == "1e-3"
    assert builder.relax_settings.get_dict()["max_steps"] == 100


def test_band_input_generator():
    """Test AbacusBandInputGenerator"""

    generator = AbacusBandInputGenerator(preset_name="default")
    assert generator.WF_ENTRYPOINT == "abacus.band"

    # Test band settings
    assert hasattr(generator.preset, "default_band_settings")
    if generator.preset.default_band_settings:
        assert "run_bands" in generator.preset.default_band_settings


def test_band_input_generator_applies_default_band_settings(monkeypatch, abacus_code, si_structure):
    """Test that the band generator applies preset band settings to the builder."""

    builder = _make_fake_builder(si_structure, abacus_code)
    _patch_generator_helpers(monkeypatch, builder)

    generator = AbacusBandInputGenerator(preset_name="testing")
    builder = generator.get_builder(
        structure=si_structure,
        code=abacus_code.label,
        protocol="balanced",
    )

    assert generator.builder is builder
    assert builder.band_settings.get_dict()["run_bands"] is True
    assert builder.band_settings.get_dict()["run_dos"] is False
    assert builder.band_settings.get_dict()["band_mode"] == "seekpath-aiida"
    assert builder.band_settings.get_dict()["band_kpoints_distance"] == 0.025


def test_protocol_filepath_resolution():
    """Test that protocol filepath resolution works correctly"""

    # Test that we can get the filepath
    filepath = AbacusBaseWorkChain.get_protocol_filepath()
    assert isinstance(filepath, Path)
    assert filepath.exists()

    # Test with the relax workflow
    relax_filepath = AbacusRelaxWorkChain.get_protocol_filepath()
    assert isinstance(relax_filepath, Path)
    assert relax_filepath.exists()

    # Test with the band workflow
    band_filepath = AbacusBandWorkChain.get_protocol_filepath()
    assert isinstance(band_filepath, Path)
    assert band_filepath.exists()


def test_protocol_tags():
    """Test that protocol tags are correctly set"""

    assert AbacusBaseWorkChain._protocol_tag == "base"
    assert AbacusRelaxWorkChain._protocol_tag == "relax"
    assert AbacusBandWorkChain._protocol_tag == "band"
