"""
Unit tests to verify that InputGenerator methods actually update builder contents
"""

from pathlib import Path

import pytest
from aiida_abacus.protocols.generator import AbacusBaseInputGenerator, PresetConfig


class TestPresetConfig:
    """Test PresetConfig functionality"""

    def test_preset_config_creation(self):
        """Test that PresetConfig can be created from file"""
        preset = PresetConfig.from_file("testing")
        assert preset is not None

    def test_code_specific_options(self):
        """Test getting code-specific options from PresetConfig"""
        preset = PresetConfig.from_file("testing")
        options = preset.get_code_specific_options("abacus@localhost", "options")

        assert isinstance(options, dict)
        assert "max_wallclock_seconds" in options


class TestBuilderCreation:
    """Test basic builder creation and structure validation"""

    @pytest.fixture
    def generator(self):
        """Create a generator instance for testing"""
        return AbacusBaseInputGenerator(preset_name="testing")

    @pytest.fixture
    def builder(self, generator, si_structure, abacus_code, pseudo_family_v2):
        """Create a builder instance for testing"""
        return generator.get_builder(
            structure=si_structure,
            protocol="balanced",
            overrides={"pseudo_family": "apns-efficiency-test"},
            code=abacus_code.label,
        )

    def test_builder_contains_expected_data(self, builder):
        """Test that builder contains the expected data values"""
        assert builder.abacus.structure is not None
        assert builder.abacus.code is not None
        assert builder.abacus.parameters is not None
        assert builder.abacus.metadata is not None

    def test_builder_parameters_structure(self, builder):
        """Test that builder parameters have expected structure and values"""
        params_dict = builder.abacus.parameters.get_dict()
        assert "input" in params_dict
        assert isinstance(params_dict["input"], dict)

        # Check for some common expected parameters
        input_section = params_dict["input"]
        assert "basis_type" in input_section or "calculation" in input_section

    def test_builder_metadata_options_structure(self, builder):
        """Test that builder metadata options have expected structure and values"""
        options = builder.abacus.metadata.options
        options_dict = dict(options)

        # Check for essential metadata options
        assert "resources" in options_dict
        assert isinstance(options_dict["resources"], dict)


class TestSetInputMethod:
    """Test the set_input method functionality"""

    @pytest.fixture
    def generator(self):
        """Create a generator instance for testing"""
        return AbacusBaseInputGenerator(preset_name="testing")

    @pytest.fixture
    def builder(self, generator, si_structure, abacus_code, pseudo_family_v2):
        """Create a builder instance for testing"""
        return generator.get_builder(
            structure=si_structure,
            protocol="balanced",
            overrides={"pseudo_family": "apns-efficiency-test"},
            code=abacus_code.label,
        )

    def test_set_input_updates_single_parameter(self, generator, builder):
        """Test that set_input updates a single parameter correctly"""
        generator.set_input(ecutwfc=81.0)

        updated_params = builder.abacus.parameters.get_dict()
        assert updated_params["input"]["ecutwfc"] == 81.0

    def test_set_input_updates_multiple_parameters(self, generator, builder):
        """Test that set_input updates multiple parameters correctly"""
        generator.set_input(ecutwfc=81.0, device="gpu", calculation="relax")
        updated_params = builder.abacus.parameters.get_dict()
        assert updated_params["input"]["ecutwfc"] == 81.0
        assert updated_params["input"]["device"] == "gpu"
        assert updated_params["input"]["calculation"] == "relax"

    def test_set_input_preserves_unspecified_parameters(self, generator, builder):
        """Test that set_input preserves parameters that are not specified"""
        original_params = builder.abacus.parameters.get_dict()
        original_scf_thr = original_params["input"]["scf_thr"]

        generator.set_input(ecutwfc=81.0)
        updated_params = builder.abacus.parameters.get_dict()
        assert updated_params["input"]["scf_thr"] == original_scf_thr


class TestSetOptionsMethod:
    """Test the set_options method functionality"""

    @pytest.fixture
    def generator(self):
        """Create a generator instance for testing"""
        return AbacusBaseInputGenerator(preset_name="testing")

    @pytest.fixture
    def builder(self, generator, si_structure, abacus_code, pseudo_family_v2):
        """Create a builder instance for testing"""
        return generator.get_builder(
            structure=si_structure,
            protocol="balanced",
            overrides={"pseudo_family": "apns-efficiency-test"},
            code=abacus_code.label,
        )

    def test_set_options_updates_single_option(self, generator, builder):
        """Test that set_options updates a single option correctly"""
        generator.set_options(max_wallclock_seconds=7201)

        updated_options = builder.abacus.metadata.options
        assert updated_options["max_wallclock_seconds"] == 7201

    def test_set_options_updates_multiple_options(self, generator, builder):
        """Test that set_options updates multiple options correctly"""
        generator.set_options(max_wallclock_seconds=7201, withmpi=False)

        updated_options = builder.abacus.metadata.options
        assert updated_options["max_wallclock_seconds"] == 7201
        assert updated_options["withmpi"] is False

    def test_set_options_preserves_unspecified_options(self, generator, builder):
        """Test that set_options preserves options that are not specified"""
        original_options = dict(builder.abacus.metadata.options)
        original_resources = original_options["resources"]

        generator.set_options(max_wallclock_seconds=7201)

        updated_options = builder.abacus.metadata.options
        assert updated_options["resources"] == original_resources


class TestSetResourcesMethod:
    """Test the set_resources method functionality"""

    @pytest.fixture
    def generator(self):
        """Create a generator instance for testing"""
        return AbacusBaseInputGenerator(preset_name="testing")

    @pytest.fixture
    def builder(self, generator, si_structure, abacus_code, pseudo_family_v2):
        """Create a builder instance for testing"""
        return generator.get_builder(
            structure=si_structure,
            protocol="balanced",
            overrides={"pseudo_family": "apns-efficiency-test"},
            code=abacus_code.label,
        )

    def test_set_resources_updates_single_resource(self, generator, builder):
        """Test that set_resources updates a single resource correctly"""
        generator.set_resources(num_machines=4)

        final_options = builder.abacus.metadata.options
        assert final_options["resources"]["num_machines"] == 4

    def test_set_resources_updates_multiple_resources(self, generator, builder):
        """Test that set_resources updates multiple resources correctly"""
        generator.set_resources(num_machines=4, tot_num_mpiprocs=16)

        final_options = builder.abacus.metadata.options
        assert final_options["resources"]["num_machines"] == 4
        assert final_options["resources"]["tot_num_mpiprocs"] == 16

    def test_set_resources_preserves_other_options(self, generator, builder):
        """Test that set_resources preserves other metadata options"""
        # First set some options
        generator.set_options(max_wallclock_seconds=7201)

        # Then set resources
        generator.set_resources(num_machines=8)

        final_options = builder.abacus.metadata.options
        assert final_options["max_wallclock_seconds"] == 7201
        assert final_options["resources"]["num_machines"] == 8


class TestMethodChaining:
    """Test method chaining functionality"""

    @pytest.fixture
    def generator(self):
        """Create a generator instance for testing"""
        return AbacusBaseInputGenerator(preset_name="testing")

    @pytest.fixture
    def builder(self, generator, si_structure, abacus_code, pseudo_family_v2):
        """Create a builder instance for testing"""
        return generator.get_builder(
            structure=si_structure,
            protocol="balanced",
            overrides={"pseudo_family": "apns-efficiency-test"},
            code=abacus_code.label,
        )

    def test_method_chaining_returns_generator(self, builder, generator):
        """Test that method chaining returns the generator instance"""
        result = generator.set_input(ecutwfc=91.0)
        assert result is generator

    def test_full_method_chaining(self, generator, builder):
        """Test that full method chaining works correctly"""
        chain_result = (
            generator.set_input(ecutwfc=91.0, basis_type="lcao")
            .set_options(max_wallclock_seconds=10801)
            .set_resources(num_machines=8)
        )

        assert chain_result is generator

        final_params = builder.abacus.parameters.get_dict()
        final_options = builder.abacus.metadata.options

        assert final_params["input"]["ecutwfc"] == 91.0
        assert final_params["input"]["basis_type"] == "lcao"
        assert final_options["max_wallclock_seconds"] == 10801
        assert final_options["resources"]["num_machines"] == 8


class TestCustomProtocol:
    """Test custom protocol functionality"""

    def test_custom_protocol_loading(self, si_structure, abacus_code, pseudo_family_v2):
        """Test that custom protocols can be loaded correctly"""
        generator = AbacusBaseInputGenerator(preset_name="testing")
        builder = generator.get_builder(
            structure=si_structure,
            protocol=f"balanced@{Path(__file__).parent}/custom.yaml",
            code=abacus_code.label,
        )

        assert builder.abacus.parameters["input"]["encut_wfc"] == 101
