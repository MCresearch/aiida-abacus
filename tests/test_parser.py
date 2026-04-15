import pathlib

import pytest
from aiida import orm
from aiida_abacus.parsers.abacus import AbacusParser


@pytest.fixture
def parser_with_retrieved(calc_with_retrieved, request):
    """Fixture to create an AbacusParser instance with a given pre-computed data folder"""

    def wrapped(name, parameters=None, settings=None, parse=True):
        _relative_file_path = f"test_data/{name}"
        file_path = str(pathlib.Path(request.fspath).parent / _relative_file_path)
        node = calc_with_retrieved(file_path, parameters=parameters, settings=settings)
        parser = AbacusParser(node)
        exit_code = None
        if parse:
            exit_code = parser.parse()
        return parser, exit_code

    return wrapped


def _write_retrieved_tree(base_path: pathlib.Path, calculation: str, log_content: str, warning_content: str = ""):
    out_folder = base_path / "OUT.aiida"
    out_folder.mkdir(parents=True, exist_ok=True)
    (out_folder / f"running_{calculation}.log").write_text(log_content)
    (out_folder / "warning.log").write_text(warning_content)
    (base_path / "abacus_output").write_text("")


def test_parser_pw_si2(calc_with_retrieved, request):
    """Test parsing pw_Si2 calculation (SCF)"""
    _relative_file_path = "test_data/pw_Si2"
    file_path = str(pathlib.Path(request.fspath).parent / _relative_file_path)
    node = calc_with_retrieved(file_path, {})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    # Check that parsing was successful
    assert exit_code is None

    # Check that basic outputs are present
    assert "misc" in parser.outputs

    misc = parser.outputs["misc"].get_dict()

    # Check for basic calculation information
    assert "fermi_level" in misc
    assert "all_forces" in misc
    assert "all_stress" in misc

    # Check for run_status
    assert "run_status" in misc
    run_status = misc["run_status"]
    assert isinstance(run_status, dict)
    assert "completed" in run_status
    assert "completion_marker_found" in run_status
    assert "termination_marker" in run_status

    # For successful parsing, calculation should be completed
    assert run_status["completed"] is True
    assert run_status["completion_marker_found"] is True
    assert run_status["termination_marker"] == "Total  Time"

    # Check for Fermi level value
    assert isinstance(misc["fermi_level"], float)
    assert misc["fermi_level"] > 0

    # Check forces array - may be empty for SCF calculation or contain final forces
    forces = misc.get("final_forces", misc.get("all_forces", []))
    if forces:  # Only check if forces are present
        assert isinstance(forces, list)
        # For Si2, should have 2 atoms if forces are calculated
        if len(forces) > 0:
            for force in forces:
                assert isinstance(force, list)
                assert len(force) == 3
                for component in force:
                    assert isinstance(component, (int, float))

    # Check stress tensor - may be empty for SCF calculation
    stress = misc.get("all_stress", [])
    if stress:  # Only check if stress is present
        assert isinstance(stress, list)
        if len(stress) > 0:
            for row in stress:
                assert isinstance(row, list)
                assert len(row) == 3
                for component in row:
                    assert isinstance(component, (int, float))

    # Check for other common ABACUS output fields
    expected_fields = ["total_energy", "number_of_bands"]
    for field in expected_fields:
        assert isinstance(misc[field], (int, float, bool, list))

    assert misc["warnings"] == [{"source": "scf", "message": "Threshold on eigenvalues was too large."}]


def test_parser_pw_si2_relax(calc_with_retrieved, request):
    """Test parsing pw_Si2-relax calculation (cell relaxation)"""
    _relative_file_path = "test_data/pw_Si2-relax"
    file_path = str(pathlib.Path(request.fspath).parent / _relative_file_path)

    # Use relax calculation type
    node = calc_with_retrieved(file_path, parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    # Check that parsing was successful
    assert exit_code is None

    # Check that basic outputs are present
    assert "misc" in parser.outputs

    misc = parser.outputs["misc"].get_dict()

    # Check for basic calculation information
    assert "fermi_level" in misc
    assert misc.get("all_forces")
    assert misc.get("all_stress")

    # Check for run_status
    assert "run_status" in misc
    run_status = misc["run_status"]
    assert isinstance(run_status, dict)
    assert "completed" in run_status
    assert "completion_marker_found" in run_status
    assert "termination_marker" in run_status

    # For successful relaxation calculations, calculation should be completed
    assert run_status["completed"] is True
    assert run_status["completion_marker_found"] is True
    assert run_status["termination_marker"] == "Total  Time"

    # Check for Fermi level value
    assert isinstance(misc["fermi_level"], (int, float))
    assert misc["fermi_level"] > 0

    # For relaxation calculations, we expect multiple force steps
    all_forces = misc.get("all_forces", [])
    assert isinstance(all_forces, list)
    # Should have forces from multiple ionic steps for relaxation
    if len(all_forces) > 0:
        for step_forces in all_forces:
            assert isinstance(step_forces, list)
            if step_forces:  # Check if this step has forces
                for force in step_forces:
                    assert isinstance(force, list)
                    assert len(force) == 3
                    for component in force:
                        assert isinstance(component, (int, float))

    # For relaxation calculations, we expect multiple stress steps
    all_stress = misc.get("all_stress", [])
    assert isinstance(all_stress, list)
    if len(all_stress) > 0:
        for step_stress in all_stress:
            assert isinstance(step_stress, list)
            if step_stress:  # Check if this step has stress
                for row in step_stress:
                    assert isinstance(row, list)
                    assert len(row) == 3
                    for component in row:
                        assert isinstance(component, (int, float))

    # Check final forces if available
    final_forces = misc.get("final_forces")
    if final_forces is not None:
        assert isinstance(final_forces, list)
        # For Si2, should have 2 atoms
        if len(final_forces) > 0:
            for force in final_forces:
                assert isinstance(force, list)
                assert len(force) == 3

    # Check for structure output in relaxation calculations
    if "structure" in parser.outputs:
        structure = parser.outputs["structure"]
        assert hasattr(structure, "get_pymatgen") or hasattr(structure, "get_ase")


def test_parser_energy_components(parser_with_retrieved):
    """Test that parser correctly extracts energy components"""
    parser, _ = parser_with_retrieved("pw_Si2")
    misc = parser.outputs["misc"].get_dict()

    # Check for run_status
    assert "run_status" in misc
    run_status = misc["run_status"]
    assert isinstance(run_status, dict)
    assert run_status["completed"] is True
    assert run_status["termination_marker"] == "Total  Time"

    # Check for different energy components if available
    energy_components = [
        "energy",
        "total_energy",
        "efermi",  # alternative name for fermi level
    ]

    for component in energy_components:
        if component in misc:
            # Energy may be stored as string, so convert and test
            energy_value = misc[component]
            if isinstance(energy_value, str):
                try:
                    float(energy_value)
                except ValueError:
                    pytest.fail(f"Energy component {component} is not a valid number: {energy_value}")
            else:
                assert isinstance(energy_value, (int, float))

    # Fermi level is always present in ABACUS output
    assert "fermi_level" in misc
    assert isinstance(misc["fermi_level"], float)


def test_parser_fermi_level(parser_with_retrieved):
    """Test that parser correctly extracts Fermi level"""
    parser, _ = parser_with_retrieved("pw_Si2")
    misc = parser.outputs["misc"].get_dict()

    # Check for run_status
    assert "run_status" in misc
    run_status = misc["run_status"]
    assert isinstance(run_status, dict)
    assert run_status["completed"] is True
    assert run_status["termination_marker"] == "Total  Time"

    # Check for Fermi level
    assert "fermi_level" in misc
    assert isinstance(misc["fermi_level"], float)
    # Fermi level for Si should be around a few eV
    assert -10 < misc["fermi_level"] < 10


def test_parser_relax_trajectory(parser_with_retrieved):
    """Test that parser correctly handles relaxation trajectory data"""
    parser, _ = parser_with_retrieved("pw_Si2-relax", parameters={"input": {"calculation": "cell-relax"}})
    misc = parser.outputs["misc"].get_dict()

    # Check for run_status
    assert "run_status" in misc
    run_status = misc["run_status"]
    assert isinstance(run_status, dict)
    assert run_status["completed"] is True
    assert run_status["termination_marker"] == "Total  Time"

    # Check for trajectory-related information in relaxation
    all_forces = misc.get("all_forces")
    all_stress = misc.get("all_stress")

    # For relaxation, we expect multiple steps
    assert len(all_forces) > 2
    assert len(all_stress) > 2

    # If we have multiple steps, this indicates trajectory data
    if len(all_forces) > 1:
        # Verify each step has proper structure
        for step_forces in all_forces:
            if step_forces:  # non-empty step
                assert isinstance(step_forces, list)

    if len(all_stress) > 1:
        # Verify each step has proper structure
        for step_stress in all_stress:
            if step_stress:  # non-empty step
                assert isinstance(step_stress, list)
    # Check that trajectory output node is present
    assert isinstance(parser.outputs.get("trajectory"), orm.TrajectoryData)
    assert len(parser.outputs["trajectory"].get_array("forces")) == len(misc.get("all_forces"))
    assert len(parser.outputs["trajectory"].get_array("stresses")) == len(misc.get("all_stress"))
    assert parser.outputs.get("trajectory").get_step_structure(1)


def test_parser_pw_si2_incomplete(calc_with_retrieved, request):
    """Test parsing incomplete pw_Si2 calculation (truncated before completion)"""
    _relative_file_path = "test_data/pw_Si2-incomplete"
    file_path = str(pathlib.Path(request.fspath).parent / _relative_file_path)

    # Use relax calculation type to match the original data
    node = calc_with_retrieved(file_path, parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    # For incomplete calculations, parser should return ERROR_CALCULATION_INCOMPLETE
    assert exit_code is not None
    assert exit_code.status == 301  # ERROR_CALCULATION_INCOMPLETE

    # When parser exits with error, no outputs are created
    assert "misc" not in parser.outputs


def test_parser_returns_electronic_not_converged(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_scf_not_converged"
    _write_retrieved_tree(
        file_path,
        "scf",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " !!SCF IS NOT CONVERGED!!",
                " Total  Time  :  1.0 s",
            ]
        ),
    )

    node = calc_with_retrieved(str(file_path))
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is not None
    assert exit_code.status == 302
    assert "misc" not in parser.outputs


def test_parser_returns_ionic_not_converged(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_relax_not_converged"
    _write_retrieved_tree(
        file_path,
        "cell-relax",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " Relaxation is not converged",
                " Total  Time  :  1.0 s",
            ]
        ),
    )

    node = calc_with_retrieved(str(file_path), parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is not None
    assert exit_code.status == 303
    assert "misc" not in parser.outputs


def test_parser_returns_missing_output_files(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_relax_missing_final_structure"
    _write_retrieved_tree(
        file_path,
        "cell-relax",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " Total  Time  :  1.0 s",
            ]
        ),
    )

    node = calc_with_retrieved(str(file_path), parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is not None
    assert exit_code.status == 300
    assert "misc" not in parser.outputs


def test_parser_merges_running_log_warnings(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_warning_merge"
    _write_retrieved_tree(
        file_path,
        "scf",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " Notice: Threshold on eigenvalues was too large.",
                " Total  Time  :  1.0 s",
            ]
        ),
        warning_content="driver warning : Calculation will restart\n",
    )

    node = calc_with_retrieved(str(file_path))
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is None
    assert parser.outputs["misc"].get_dict()["warnings"] == [
        {"source": "driver", "message": "Calculation will restart"},
        {"source": "running_log", "message": "Threshold on eigenvalues was too large."},
    ]


def test_parser_returns_geometry_not_converged(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_geometry_not_converged"
    _write_retrieved_tree(
        file_path,
        "cell-relax",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " Geometry relaxation is not converged",
                " Total  Time  :  1.0 s",
            ]
        ),
    )

    node = calc_with_retrieved(str(file_path), parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is not None
    assert exit_code.status == 303


def test_parser_returns_relax_scf_not_converged(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_relax_scf_not_converged"
    _write_retrieved_tree(
        file_path,
        "cell-relax",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " Relaxation is converged!",
                " Relaxation is converged, but the SCF is unconverged",
                " Total  Time  :  1.0 s",
            ]
        ),
    )

    node = calc_with_retrieved(str(file_path), parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is not None
    assert exit_code.status == 302


def test_parser_allows_relax_with_intermediate_scf_failure_if_final_scf_converges(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_relax_final_scf_converged"
    _write_retrieved_tree(
        file_path,
        "cell-relax",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " !!SCF IS NOT CONVERGED!!",
                " Relaxation is not converged yet!",
                " #SCF IS CONVERGED#",
                " Relaxation is converged!",
                " Total  Time  :  1.0 s",
            ]
        ),
    )
    (file_path / "OUT.aiida" / "STRU_ION_D").write_text(
        "\n".join(
            [
                "ATOMIC_SPECIES",
                "Si 28.0855 Si.upf",
                "",
                "NUMERICAL_ORBITAL",
                "Si.orb",
                "",
                "LATTICE_CONSTANT",
                "1.889726125457828",
                "",
                "LATTICE_VECTORS",
                "5.1 0.0 0.0",
                "0.0 5.1 0.0",
                "0.0 0.0 5.1",
                "",
                "ATOMIC_POSITIONS",
                "Cartesian_angstrom",
                "Si",
                "0.0",
                "1",
                "0.0 0.0 0.0 1 1 1",
            ]
        )
    )
    (file_path / "OUT.aiida" / "STRU_ION1_D").write_text((file_path / "OUT.aiida" / "STRU_ION_D").read_text())

    node = calc_with_retrieved(str(file_path), parameters={"input": {"calculation": "cell-relax"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is None
    assert "misc" in parser.outputs
    assert "structure" in parser.outputs


def test_parser_does_not_apply_scf_convergence_failure_to_nscf(calc_with_retrieved, tmp_path):
    file_path = tmp_path / "pw_nscf_not_converged_marker"
    _write_retrieved_tree(
        file_path,
        "nscf",
        "\n".join(
            [
                " EFERMI = 1.23 eV",
                " NBANDS = 8",
                " !! convergence has not been achieved @_@",
                " Total  Time  :  1.0 s",
            ]
        ),
    )

    node = calc_with_retrieved(str(file_path), parameters={"input": {"calculation": "nscf"}})
    parser = AbacusParser(node)
    exit_code = parser.parse()

    assert exit_code is None
    assert "misc" in parser.outputs
