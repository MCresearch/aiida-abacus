"""
Integration tests to verify that InputGenerator methods actually update builder contents
"""

from pathlib import Path

from aiida_abacus.protocols.generator import AbacusBaseInputGenerator, PresetConfig


def test_builder_update_integration(si_structure, abacus_code, pseudo_family_v2):
    """Test that InputGenerator methods actually update the builder contents"""
    print("Testing InputGenerator builder update integration...")

    # Test 1: Test PresetConfig code-specific options
    print("  ✓ Testing PresetConfig...")
    preset = PresetConfig.from_file("testing")
    options = preset.get_code_specific_options("abacus@localhost", "options")
    assert isinstance(options, dict)
    assert "max_wallclock_seconds" in options
    print("    ✓ PresetConfig works correctly")

    # Test 2: Test InputGenerator with actual workflow builder
    print("  ✓ Testing InputGenerator with workflow builder...")
    generator = AbacusBaseInputGenerator(preset_name="testing")

    # Create builder using the workflow
    builder = generator.get_builder(
        structure=si_structure,
        protocol="balanced",
        overrides={"pseudo_family": "apns-efficiency-test"},
    )

    # Verify builder has expected structure
    assert hasattr(builder, "abacus")
    assert hasattr(builder.abacus, "structure")
    assert hasattr(builder.abacus, "code")
    assert hasattr(builder.abacus, "parameters")
    assert hasattr(builder.abacus, "metadata")
    print("    ✓ Builder created successfully")

    # Store original values
    original_params = builder.abacus.parameters.get_dict()
    original_options = dict(builder.abacus.metadata.options)

    print(f"    Original ecutwfc: {original_params.get('input', {}).get('ecutwfc')}")
    print(f"    Original max_wallclock_seconds: {original_options.get('max_wallclock_seconds')}")

    # Test set_input method
    generator.set_input(ecutwfc=80.0, device="gpu", calculation="relax")

    # Check parameters were updated
    updated_params = builder.abacus.parameters.get_dict()
    assert updated_params["input"]["ecutwfc"] == 80.0
    assert updated_params["input"]["device"] == "gpu"
    assert updated_params["input"]["calculation"] == "relax"
    assert updated_params["input"]["scf_thr"] == original_params["input"]["scf_thr"]  # Should be preserved
    print("    ✓ set_input method updated builder correctly")

    # Test set_options method
    generator.set_options(max_wallclock_seconds=7200, withmpi=False)

    # Check options were updated
    updated_options = builder.abacus.metadata.options
    assert updated_options["max_wallclock_seconds"] == 7200
    assert updated_options["withmpi"] is False
    assert updated_options["resources"] == original_options["resources"]  # Should be preserved
    print("    ✓ set_options method updated builder correctly")

    # Test set_resources method
    generator.set_resources(num_machines=4, tot_num_mpiprocs=16)

    # Check resources were updated
    final_options = builder.abacus.metadata.options
    assert final_options["resources"]["num_machines"] == 4
    assert final_options["resources"]["tot_num_mpiprocs"] == 16
    assert final_options["max_wallclock_seconds"] == 7200  # Should be preserved from previous update
    print("    ✓ set_resources method updated builder correctly")

    # Test method chaining
    chain_result = (
        generator.set_input(ecutwfc=90.0, basis_type="lcao")
        .set_options(max_wallclock_seconds=10800)
        .set_resources(num_machines=8)
    )

    assert chain_result is generator
    final_params = builder.abacus.parameters.get_dict()
    final_options = builder.abacus.metadata.options

    assert final_params["input"]["ecutwfc"] == 90.0
    assert final_params["input"]["basis_type"] == "lcao"
    assert final_options["max_wallclock_seconds"] == 10800
    assert final_options["resources"]["num_machines"] == 8
    print("    ✓ Method chaining works correctly")

    print("  ✓ All InputGenerator integration tests passed!")

    # Test customized protocol

    generator = AbacusBaseInputGenerator(preset_name="testing")
    builder = generator.get_builder(
        structure=si_structure,
        protocol=f"balanced@{Path(__file__).parent}/custom.yaml",
    )
    # assert builder.pseudo_family == "apns-efficiency-test"
    assert builder.abacus.parameters["input"]["encut_wfc"] == 101
