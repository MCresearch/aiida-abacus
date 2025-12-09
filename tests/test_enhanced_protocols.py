"""
Test the enhanced protocol system and InputGenerator functionality
"""

from pathlib import Path

from aiida_abacus.protocols.generator import (
    AbacusBandInputGenerator,
    AbacusBaseInputGenerator,
    AbacusRelaxInputGenerator,
    PresetConfig,
)
from aiida_abacus.workflows.band import AbacusBandWorkChain
from aiida_abacus.workflows.base import AbacusBaseWorkChain
from aiida_abacus.workflows.relax import AbacusRelaxWorkChain


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


def test_input_generator_basic():
    """Test basic InputGenerator functionality"""

    # Test creating a generator
    generator = AbacusBaseInputGenerator(preset_name="default")
    assert generator.preset_name == "default"
    assert generator.protocol == "balanced"

    # Test preset loading
    assert generator.preset is not None
    assert generator.preset.name == "default"


def test_relax_input_generator():
    """Test AbacusRelaxInputGenerator"""

    generator = AbacusRelaxInputGenerator(preset_name="default")
    assert generator.WF_ENTRYPOINT == "abacus.relax"

    # Test relax settings
    assert hasattr(generator.preset, "default_relax_settings")
    if generator.preset.default_relax_settings:
        assert "perform" in generator.preset.default_relax_settings


def test_band_input_generator():
    """Test AbacusBandInputGenerator"""

    generator = AbacusBandInputGenerator(preset_name="default")
    assert generator.WF_ENTRYPOINT == "abacus.band"

    # Test band settings
    assert hasattr(generator.preset, "default_band_settings")
    if generator.preset.default_band_settings:
        assert "run_bands" in generator.preset.default_band_settings


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
