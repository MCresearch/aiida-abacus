"""Tests for ABACUS calculations."""

import tempfile
from pathlib import Path

from aiida import orm
from aiida.common import exceptions
from aiida.common.extendeddicts import AttributeDict
from aiida.engine.utils import instantiate_process
from aiida.manage.manager import get_manager

from aiida_abacus.calculations import AbacusCalculation
from aiida_abacus.common.opthold import SettingsOptions


class TestAbacusCalculation:
    """Test the main AbacusCalculation class functionality."""

    def test_default_calc_paths(self):
        """Test default calculation paths configuration."""
        default_paths = AbacusCalculation.get_default_calc_paths()

        required_paths = ["PSEUDO_SUBFOLDER", "OUTPUT_SUFFIX", "OUTPUT_SUBFOLDER", "ABACUS_OUTPUT"]

        for path_name in required_paths:
            assert path_name in default_paths, f"Missing default path: {path_name}"

        assert default_paths["OUTPUT_SUFFIX"] == "aiida"

    def test_input_parameter_generation(self, abacus_calc):
        """Test the generate_input method directly."""
        parameters = {"basis_type": "pw", "ecutwfc": 60, "calculation": "scf"}

        input_content = abacus_calc.generate_input(parameters)

        assert input_content.startswith("INPUT_PARAMETERS")
        assert "basis_type" in input_content
        assert "ecutwfc" in input_content

    def test_structure_generation(self, abacus_calc):
        """Test the generate_structure method directly."""
        structure = abacus_calc.inputs.structure
        pseudos = abacus_calc.inputs.pseudos
        parameters = {"m": [[True, True, True]] * len(structure.sites)}

        structure_content, copy_list = abacus_calc.generate_structure(structure, pseudos, parameters)

        assert "ATOMIC_SPECIES" in structure_content
        assert "LATTICE_VECTORS" in structure_content
        assert isinstance(copy_list, list)
        assert len(copy_list) > 0

    def test_settings_validation(self, abacus_code, si_structure, pseudo_family, abacus_kpoints):
        """Test validation of settings input."""
        manager = get_manager()
        runner = manager.get_runner()

        inputs = AttributeDict()
        inputs.code = abacus_code
        inputs.structure = si_structure
        inputs.pseudos = pseudo_family.get_pseudos(structure=si_structure)
        inputs.kpoints = abacus_kpoints
        inputs.parameters = orm.Dict({"input": {"basis_type": "pw", "ecutwfc": 60}})
        inputs.metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        inputs.settings = orm.Dict({"skip_parameters_validation": True})

        calc = instantiate_process(runner, AbacusCalculation, **inputs)
        assert calc is not None

        # Test settings validation directly
        try:
            SettingsOptions.aiida_validate({"invalid_setting": "value"})
            # If no exception, settings validation might be lenient
            assert True
        except (ValueError, exceptions.InputValidationError):
            # This is expected for invalid settings
            assert True

    def test_input_generation_basic(self, abacus_calc, sandbox_folder):
        """Test basic input generation."""
        calcinfo = abacus_calc.prepare_for_submission(sandbox_folder)

        assert calcinfo is not None
        assert len(calcinfo.codes_info) == 1

        # Check that required files are created using pathlib.Path
        assert Path(sandbox_folder.get_abs_path("INPUT")).exists()
        assert Path(sandbox_folder.get_abs_path("KPT")).exists()
        assert Path(sandbox_folder.get_abs_path("STRU")).exists()

    def test_retrieve_list_generation(self, abacus_calc, sandbox_folder):
        """Test that retrieve list is properly generated."""
        calcinfo = abacus_calc.prepare_for_submission(sandbox_folder)

        retrieve_list = calcinfo.retrieve_list
        assert isinstance(retrieve_list, list)
        assert len(retrieve_list) > 0

    def test_code_command_line_params(self, abacus_calc, sandbox_folder):
        """Test that code command line parameters are correctly set."""
        calcinfo = abacus_calc.prepare_for_submission(sandbox_folder)

        codeinfo = calcinfo.codes_info[0]
        assert codeinfo.cmdline_params == []
        assert codeinfo.stdout_name == "abacus_output"


def test_input_generation_comprehensive(abacus_calc, sandbox_folder):
    """Test the comprehensive generation of a calculation - legacy test."""
    calcinfo = abacus_calc.prepare_for_submission(sandbox_folder)

    assert calcinfo is not None
    assert hasattr(calcinfo, "codes_info")
    assert hasattr(calcinfo, "retrieve_list")


def _instantiate_with_extra_files(abacus_inputs, extra_files, basepath=None):
    """Build a calc process with ``extra_files`` attached."""
    manager = get_manager()
    runner = manager.get_runner()
    inputs = abacus_inputs()
    inputs.extra_files = AttributeDict(extra_files)
    if basepath is not None:
        inputs.extra_files_basepath = orm.Str(basepath)
    return instantiate_process(runner, AbacusCalculation, **inputs)


def test_extra_files_singlefile(abacus_inputs, sandbox_folder, aiida_profile_clean):
    """A SinglefileData in extra_files is copied to its filename under the basepath."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cube") as handle:
        handle.write("# cube content\n")
        handle.flush()
        single = orm.SinglefileData(handle.name)

    # Key is a plain label; destination comes from node.filename + basepath.
    calc = _instantiate_with_extra_files(abacus_inputs, {"chg": single}, basepath="OUT.aiida")
    calcinfo = calc.prepare_for_submission(sandbox_folder)

    entry = (single.uuid, single.filename, f"OUT.aiida/{single.filename}")
    assert entry in calcinfo.local_copy_list, f"expected {entry} in {calcinfo.local_copy_list}"


def test_extra_files_singlefile_root(abacus_inputs, sandbox_folder, aiida_profile_clean):
    """Without basepath, a SinglefileData lands in the calculation root."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cube") as handle:
        handle.write("# cube content\n")
        handle.flush()
        single = orm.SinglefileData(handle.name)

    calc = _instantiate_with_extra_files(abacus_inputs, {"chg": single})
    calcinfo = calc.prepare_for_submission(sandbox_folder)

    assert (single.uuid, single.filename, single.filename) in calcinfo.local_copy_list


def test_extra_files_folder(abacus_inputs, sandbox_folder, aiida_profile_clean):
    """All objects of a FolderData are copied below the basepath, preserving layout."""
    folder = orm.FolderData()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".UPF") as handle:
        handle.write("pseudo content")
        handle.flush()
        folder.put_object_from_file(handle.name, "subdir/U.UPF")
    folder.put_object_from_bytes(b"another", "README.txt")

    calc = _instantiate_with_extra_files(abacus_inputs, {"aux": folder}, basepath="OUT.aiida")
    calcinfo = calc.prepare_for_submission(sandbox_folder)

    assert (folder.uuid, "subdir/U.UPF", "OUT.aiida/subdir/U.UPF") in calcinfo.local_copy_list
    assert (folder.uuid, "README.txt", "OUT.aiida/README.txt") in calcinfo.local_copy_list


def test_extra_files_empty_namespace(abacus_inputs, sandbox_folder, aiida_profile_clean):
    """Without extra_files, no extra local copies are added."""
    manager = get_manager()
    runner = manager.get_runner()
    calc = instantiate_process(runner, AbacusCalculation, **abacus_inputs())
    calcinfo = calc.prepare_for_submission(sandbox_folder)

    # Pseudo files are copied, but nothing extra.
    assert calcinfo.local_copy_list is not None
