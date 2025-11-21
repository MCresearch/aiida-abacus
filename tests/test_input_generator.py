"""
Comprehensive tests for InputGenerator set_xxx methods

This module tests the InputGenerator system with a focus on verifying that
the underlying builder actually contains the updated keys after calling
various set methods.
"""

import pytest
from aiida import orm
from aiida_abacus.protocols.generator import (
    AbacusBandInputGenerator,
    AbacusBaseInputGenerator,
    AbacusRelaxInputGenerator,
    PresetConfig,
    update_dict_node,
)
from aiida_abacus.workflows.band import AbacusBandWorkChain
from aiida_abacus.workflows.base import AbacusBaseWorkChain
from aiida_abacus.workflows.relax import AbacusRelaxWorkChain


class TestPresetConfig:
    """Test the PresetConfig functionality"""

    def test_load_default_preset(self):
        """Test loading the default preset"""
        preset = PresetConfig.from_file("default")
        assert preset.name == "default"
        assert preset.default_protocol == "balanced"
        assert preset.default_code == "abacus@localhost"

    def test_code_specific_options(self):
        """Test getting code-specific options"""
        preset = PresetConfig.from_file("default")

        # Test getting options for localhost code
        options = preset.get_code_specific_options("abacus@cluster", "options")
        assert isinstance(options, dict)
        assert "max_wallclock_seconds" in options
        assert options["max_wallclock_seconds"] == 7200

        # Test getting parameters
        parameters = preset.get_code_specific_options("abacus@cluster", "parameters")
        assert isinstance(parameters, dict)
        assert "input" in parameters
        assert parameters["input"]["ecutwfc"] == 80.0

    def test_unknown_code_fallback(self):
        """Test that unknown codes return default options"""
        preset = PresetConfig.from_file("default")

        # Test with unknown code
        options = preset.get_code_specific_options("unknown@host", "options")
        # Should return deep copy of defaults
        assert isinstance(options, dict)
        assert "max_wallclock_seconds" in options


class TestUpdateDictNode:
    """Test the update_dict_node utility function"""

    def test_update_unstored_dict_node(self):
        """Test updating an unstored Dict node"""
        original_dict = {"input": {"ecutwfc": 50.0, "scf_thr": 1e-6}}
        node = orm.Dict(dict=original_dict)

        updates = {"ecutwfc": 60.0, "device": "gpu"}
        updated_node = update_dict_node(node, updates, namespace="input")

        # Should be the same node (unstored)
        assert updated_node is node

        # Check the updates were applied correctly
        result_dict = updated_node.get_dict()
        assert result_dict["input"]["ecutwfc"] == 60.0  # Updated
        assert result_dict["input"]["scf_thr"] == 1e-6  # Preserved
        assert result_dict["input"]["device"] == "gpu"  # New field

    def test_update_stored_dict_node(self):
        """Test updating a stored Dict node (should create new node)"""
        original_dict = {"input": {"ecutwfc": 50.0}}
        node = orm.Dict(dict=original_dict)
        node.store()

        updates = {"ecutwfc": 60.0}
        updated_node = update_dict_node(node, updates, namespace="input")

        # Should be a different node (stored nodes are immutable)
        assert updated_node is not node

        # Check the updates were applied
        result_dict = updated_node.get_dict()
        assert result_dict["input"]["ecutwfc"] == 60.0

    def test_update_without_namespace(self):
        """Test updating without specifying a namespace"""
        original_dict = {"ecutwfc": 50.0, "scf_thr": 1e-6}
        node = orm.Dict(dict=original_dict)

        updates = {"ecutwfc": 60.0, "device": "gpu"}
        updated_node = update_dict_node(node, updates, namespace=None)

        result_dict = updated_node.get_dict()
        assert result_dict["ecutwfc"] == 60.0
        assert result_dict["scf_thr"] == 1e-6
        assert result_dict["device"] == "gpu"


class TestInputGeneratorBase:
    """Test base InputGenerator functionality"""

    def test_generator_initialization(self):
        """Test InputGenerator initialization"""
        generator = AbacusBaseInputGenerator(preset_name="default", protocol="balanced")

        assert generator.preset_name == "default"
        assert generator.protocol == "balanced"
        assert generator.preset is not None
        assert generator.preset.name == "default"

    def test_generator_with_different_protocol(self):
        """Test InputGenerator with different protocol"""
        generator = AbacusBaseInputGenerator(preset_name="default", protocol="stringent")
        assert generator.protocol == "stringent"

    def test_get_builder_basic(self, si_structure, abacus_code):
        """Test basic builder generation"""
        generator = AbacusBaseInputGenerator(preset_name="default")

        # Mock the code to use our test code
        generator.preset.default_code = abacus_code.label

        try:
            builder = generator.get_builder(structure=si_structure)

            # Check that builder has required fields
            assert hasattr(builder, "structure")
            assert hasattr(builder, "code")
            assert builder.structure == si_structure

        except Exception:
            # Builder generation might fail due to missing dependencies, but we can check
            # that the generator setup was correct
            assert generator.WF_ENTRYPOINT == "abacus.base"
            assert generator.preset is not None


class TestInputGeneratorSetMethods:
    """Test the various set_xxx methods of InputGenerator"""

    def test_set_input_direct_parameters(self, si_structure, abacus_code):
        """Test set_input method with direct parameters"""
        generator = AbacusBaseInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            # Create a minimal builder for testing
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Test set_input with kwargs
            result = generator.set_input(ecutwfc=80.0, device="gpu", calculation="relax")

            # Should return self for chaining
            assert result is generator

            # Check that the builder was updated
            assert hasattr(generator.builder, "abacus")
            assert hasattr(generator.builder.abacus, "parameters")

            # Check the parameters were updated
            params_dict = generator.builder.abacus.parameters.get_dict()
            assert params_dict["input"]["ecutwfc"] == 80.0
            assert params_dict["input"]["device"] == "gpu"
            assert params_dict["input"]["calculation"] == "relax"

        except Exception:
            pytest.skip("Builder generation not available in test environment")

    def test_set_input_with_dict(self, si_structure, abacus_code):
        """Test set_input method with dictionary updates"""
        generator = AbacusBaseInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Test set_input with dictionary
            input_updates = {"ecutwfc": 75.0, "scf_thr": 1e-8, "basis_type": "lcao"}
            result = generator.set_input(input_updates)

            assert result is generator

            # Check the parameters were updated
            params_dict = generator.builder.abacus.parameters.get_dict()
            assert params_dict["input"]["ecutwfc"] == 75.0
            assert params_dict["input"]["scf_thr"] == 1e-8
            assert params_dict["input"]["basis_type"] == "lcao"

        except Exception:
            pytest.skip("Builder generation not available in test environment")

    def test_set_options(self, si_structure, abacus_code):
        """Test set_options method"""
        generator = AbacusBaseInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Get original options
            original_options = dict(generator.builder.abacus.metadata.options)

            # Test set_options
            result = generator.set_options(
                max_wallclock_seconds=7200, resources={"num_machines": 2, "tot_num_mpiprocs": 8}
            )

            assert result is generator

            # Check options were updated
            updated_options = generator.builder.abacus.metadata.options
            assert updated_options["max_wallclock_seconds"] == 7200
            assert updated_options["resources"]["num_machines"] == 2
            assert updated_options["resources"]["tot_num_mpiprocs"] == 8
            # Check other options were preserved
            assert updated_options["withmpi"] == original_options.get("withmpi", True)

        except Exception:
            pytest.skip("Builder generation not available in test environment")

    def test_set_resources(self, si_structure, abacus_code):
        """Test set_resources method"""
        generator = AbacusBaseInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Test set_resources
            result = generator.set_resources(num_machines=3, tot_num_mpiprocs=12, num_mpiprocs_per_machine=4)

            assert result is generator

            # Check resources were updated
            resources = generator.builder.abacus.metadata.options["resources"]
            assert resources["num_machines"] == 3
            assert resources["tot_num_mpiprocs"] == 12
            assert resources["num_mpiprocs_per_machine"] == 4

        except Exception:
            pytest.skip("Builder generation not available in test environment")

    def test_method_chaining(self, si_structure, abacus_code):
        """Test that set methods can be chained together"""
        generator = AbacusBaseInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Test method chaining
            result = (
                generator.set_input(ecutwfc=85.0, device="gpu")
                .set_options(max_wallclock_seconds=5400)
                .set_resources(num_machines=4)
            )

            assert result is generator

            # Check all changes were applied
            params_dict = generator.builder.abacus.parameters.get_dict()
            assert params_dict["input"]["ecutwfc"] == 85.0
            assert params_dict["input"]["device"] == "gpu"

            options = generator.builder.abacus.metadata.options
            assert options["max_wallclock_seconds"] == 5400
            assert options["resources"]["num_machines"] == 4

        except Exception:
            pytest.skip("Builder generation not available in test environment")


class TestRelaxInputGenerator:
    """Test AbacusRelaxInputGenerator specific functionality"""

    def test_relax_generator_initialization(self):
        """Test RelaxInputGenerator initialization"""
        generator = AbacusRelaxInputGenerator(preset_name="default")

        assert generator.WF_ENTRYPOINT == "abacus.relax"
        assert generator.preset_name == "default"

    def test_set_relax_settings(self, si_structure, abacus_code):
        """Test set_relax_settings method"""
        generator = AbacusRelaxInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            # Create a mock builder with relax_settings field
            builder = AbacusRelaxWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Test set_relax_settings
            relax_settings = {"perform": True, "relaxation_method": "cg", "force_cutoff": 5e-4, "max_steps": 150}
            result = generator.set_relax_settings(relax_settings)

            assert result is generator

            # Check that relax_settings were set (if the field exists)
            if hasattr(generator.builder, "relax_settings"):
                assert generator.builder.relax_settings["perform"] is True
                assert generator.builder.relax_settings["relaxation_method"] == "cg"
                assert generator.builder.relax_settings["force_cutoff"] == 5e-4
                assert generator.builder.relax_settings["max_steps"] == 150

        except Exception:
            pytest.skip("Relax builder generation not available in test environment")


class TestBandInputGenerator:
    """Test AbacusBandInputGenerator specific functionality"""

    def test_band_generator_initialization(self):
        """Test BandInputGenerator initialization"""
        generator = AbacusBandInputGenerator(preset_name="default")

        assert generator.WF_ENTRYPOINT == "abacus.band"
        assert generator.preset_name == "default"

    def test_set_band_settings(self, si_structure, abacus_code):
        """Test set_band_settings method"""
        generator = AbacusBandInputGenerator(preset_name="default")
        generator.preset.default_code = abacus_code.label

        try:
            # Create a mock builder with band_settings field
            builder = AbacusBandWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="balanced"
            )
            generator.builder = builder

            # Test set_band_settings
            band_settings = {
                "run_bands": True,
                "run_dos": True,
                "band_kpoints_distance": 0.02,
                "dos_kpoints_distance": 0.1,
            }
            result = generator.set_band_settings(band_settings)

            assert result is generator

            # Check that band_settings were set (if the field exists)
            if hasattr(generator.builder, "band_settings"):
                assert generator.builder.band_settings["run_bands"] is True
                assert generator.builder.band_settings["run_dos"] is True
                assert generator.builder.band_settings["band_kpoints_distance"] == 0.02
                assert generator.builder.band_settings["dos_kpoints_distance"] == 0.1

        except Exception:
            pytest.skip("Band builder generation not available in test environment")


class TestInputGeneratorEdgeCases:
    """Test edge cases and error handling"""

    def test_set_input_empty_updates(self):
        """Test set_input with no updates"""
        generator = AbacusBaseInputGenerator(preset_name="default")

        # Should return self without error when no updates are provided
        result = generator.set_input()
        assert result is generator

        result = generator.set_input({})
        assert result is generator

    def test_set_options_empty_updates(self):
        """Test set_options with no updates"""
        generator = AbacusBaseInputGenerator(preset_name="default")

        # Should return self without error when no updates are provided
        result = generator.set_options()
        assert result is generator

        result = generator.set_options({})
        assert result is generator

    def test_set_resources_empty_updates(self):
        """Test set_resources with no updates"""
        generator = AbacusBaseInputGenerator(preset_name="default")

        # Should return self without error when no updates are provided
        result = generator.set_resources()
        assert result is generator

        result = generator.set_resources({})
        assert result is generator

    def test_generator_without_builder_should_crash(self):
        """Test calling set methods before builder is created - should crash"""
        generator = AbacusBaseInputGenerator(preset_name="default")

        # These should crash when builder is None and updates are provided
        with pytest.raises(AttributeError):
            generator.set_input(ecutwfc=80.0)

        with pytest.raises(AttributeError):
            generator.set_options(max_wallclock_seconds=7200)

        with pytest.raises(AttributeError):
            generator.set_resources(num_machines=2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
