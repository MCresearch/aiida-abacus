"""Tests for protocol-based input generation in ABACUS workflows."""

import pathlib

import pytest
from aiida.common.exceptions import NotExistent

from aiida_abacus.workflows.base import AbacusBaseWorkChain


class TestProtocolInputGeneration:
    """Test protocol-based input generation for ABACUS workflows."""

    @pytest.fixture
    def protocol_file_path(self):
        """Return the path to the protocol file."""
        return pathlib.Path(__file__).parent.parent / "src" / "aiida_abacus" / "protocols" / "base.yaml"

    def test_protocol_file_exists(self, protocol_file_path):
        """Test that the protocol file exists."""
        assert protocol_file_path.exists()

    def test_get_protocol_filepath(self):
        """Test that the protocol file path is correctly returned."""
        filepath = AbacusBaseWorkChain.get_protocol_filepath()
        assert filepath.exists()
        assert filepath.name == "base.yaml"

    def test_get_protocol_inputs_default(self):
        """Test getting protocol inputs with default protocol."""
        inputs = AbacusBaseWorkChain.get_protocol_inputs()

        assert "abacus" in inputs
        assert "kpoints_distance" in inputs

        abacus_inputs = inputs["abacus"]
        assert "parameters" in abacus_inputs
        assert "metadata" in abacus_inputs

        parameters = abacus_inputs["parameters"]
        assert "input" in parameters

        input_params = parameters["input"]
        assert "basis_type" in input_params
        assert "ecutwfc" in input_params

    def test_get_protocol_inputs_specific(self):
        """Test getting protocol inputs for specific protocols."""
        test_protocols = ["fast", "balanced", "stringent"]

        for protocol in test_protocols:
            inputs = AbacusBaseWorkChain.get_protocol_inputs(protocol)

            assert "abacus" in inputs
            assert "kpoints_distance" in inputs

            abacus_inputs = inputs["abacus"]
            parameters = abacus_inputs["parameters"]
            input_params = parameters["input"]

            assert "ecutwfc" in input_params
            assert isinstance(input_params["ecutwfc"], (int, float))

    def test_protocol_with_overrides(self):
        """Test protocol inputs with parameter overrides."""
        overrides = {
            "abacus": {"parameters": {"input": {"ecutwfc": 100, "custom_parameter": "test_value"}}},
            "kpoints_distance": 0.1,
        }

        inputs = AbacusBaseWorkChain.get_protocol_inputs(overrides=overrides)

        assert inputs["abacus"]["parameters"]["input"]["ecutwfc"] == 100
        assert inputs["abacus"]["parameters"]["input"]["custom_parameter"] == "test_value"
        assert inputs["kpoints_distance"] == 0.1

    def test_invalid_protocol_name(self):
        """Test handling of invalid protocol names."""
        with pytest.raises((ValueError, KeyError)):
            AbacusBaseWorkChain.get_protocol_inputs("invalid_protocol")

    def test_get_builder_basic(self, abacus_code, si_structure):
        """Test basic builder creation from protocol."""
        try:
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, protocol="fast"
            )

            assert hasattr(builder, "abacus")
            assert hasattr(builder, "kpoints_distance")
            assert builder.abacus.code == abacus_code
            assert builder.abacus.structure == si_structure

        except (NotExistent, ValueError):
            pytest.skip("Pseudopotential family not available")

    def test_get_builder_with_options(self, abacus_code, si_structure):
        """Test builder creation with custom options."""
        options = {"resources": {"num_machines": 2, "num_mpiprocs_per_machine": 4}, "max_wallclock_seconds": 7200}

        try:
            builder = AbacusBaseWorkChain.get_builder_from_protocol(
                code=abacus_code, structure=si_structure, options=options, protocol="fast"
            )

            assert builder.abacus.metadata.options.resources.num_machines == 2
            assert builder.abacus.metadata.options.max_wallclock_seconds == 7200

        except (NotExistent, ValueError):
            pytest.skip("Pseudopotential family not available")

    def test_protocol_merge_functionality(self):
        """Test the merging of protocol parameters with overrides."""
        overrides = {"abacus": {"parameters": {"input": {"new_parameter": "test", "ecutwfc": 80}}}}

        inputs = AbacusBaseWorkChain.get_protocol_inputs("balanced", overrides)

        assert inputs["abacus"]["parameters"]["input"]["new_parameter"] == "test"
        assert inputs["abacus"]["parameters"]["input"]["ecutwfc"] == 80
        assert "basis_type" in inputs["abacus"]["parameters"]["input"]
