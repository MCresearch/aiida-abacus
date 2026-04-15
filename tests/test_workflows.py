from types import SimpleNamespace

from aiida import orm
from aiida.common.extendeddicts import AttributeDict
from aiida.engine import ProcessHandlerReport
from aiida.engine.utils import instantiate_process
from aiida.manage.manager import get_manager

from aiida_abacus.workflows.base import AbacusBaseWorkChain


def _make_failed_calc(exit_status, outputs=None, pk=1):
    return SimpleNamespace(
        exit_status=exit_status,
        outputs=outputs or AttributeDict(),
        process_label="AbacusCalculation",
        pk=pk,
        exit_message="failed",
    )


def _instantiate_base_workchain(abacus_inputs, abacus_kpoints):
    manager = get_manager()
    runner = manager.get_runner()
    base_inputs = abacus_inputs()
    base_inputs.pop("kpoints", None)

    inputs = AttributeDict()
    inputs.abacus = base_inputs
    inputs.kpoints = abacus_kpoints
    inputs.max_iterations = orm.Int(5)

    workchain = instantiate_process(runner, AbacusBaseWorkChain, **inputs)
    workchain.setup()
    return workchain


def test_handler_unfinished_calc_retries_once(aiida_profile_clean, abacus_inputs, abacus_kpoints):
    workchain = _instantiate_base_workchain(abacus_inputs, abacus_kpoints)
    calculation = _make_failed_calc(301)

    report = workchain.handler_unfinished_calc(calculation)

    assert isinstance(report, ProcessHandlerReport)
    assert report.exit_code.status == 0
    assert workchain.ctx.last_calc_was_unfinished is True


def test_handler_unfinished_calc_aborts_on_second_consecutive_failure(
    aiida_profile_clean, abacus_inputs, abacus_kpoints
):
    workchain = _instantiate_base_workchain(abacus_inputs, abacus_kpoints)
    calculation = _make_failed_calc(301)

    workchain.handler_unfinished_calc(calculation)
    report = workchain.handler_unfinished_calc(calculation)

    assert isinstance(report, ProcessHandlerReport)
    assert report.exit_code.status == workchain.exit_codes.ERROR_UNRECOVERABLE_FAILURE.status


def test_handler_electronic_convergence_sequence(aiida_profile_clean, abacus_inputs, abacus_kpoints):
    workchain = _instantiate_base_workchain(abacus_inputs, abacus_kpoints)
    calculation = _make_failed_calc(302)

    report = workchain.handler_electronic_convergence(calculation)
    assert report.exit_code.status == 0
    assert workchain.ctx.inputs.parameters["input"]["scf_nmax"] == 150

    report = workchain.handler_electronic_convergence(calculation)
    assert report.exit_code.status == 0
    assert workchain.ctx.inputs.parameters["input"]["mixing_beta"] == 0.4

    report = workchain.handler_electronic_convergence(calculation)
    assert report.exit_code.status == 0
    assert workchain.ctx.inputs.parameters["input"]["mixing_beta"] == 0.2

    report = workchain.handler_electronic_convergence(calculation)
    assert report.exit_code.status == 0
    assert workchain.ctx.inputs.parameters["input"]["mixing_beta"] == 0.1

    report = workchain.handler_electronic_convergence(calculation)
    assert report.exit_code.status == workchain.exit_codes.ERROR_KNOWN_UNRECOVERABLE_FAILURE.status


def test_handler_ionic_convergence_restarts_from_output_structure(
    aiida_profile_clean, abacus_inputs, abacus_kpoints, si_structure
):
    workchain = _instantiate_base_workchain(abacus_inputs, abacus_kpoints)
    calculation = _make_failed_calc(303, outputs=AttributeDict({"structure": si_structure}))

    report = workchain.handler_ionic_convergence(calculation)

    assert report.exit_code.status == 0
    assert workchain.ctx.ionic_restart_attempted is True
    assert workchain.ctx.inputs.structure is si_structure


def test_handler_ionic_convergence_aborts_without_structure(aiida_profile_clean, abacus_inputs, abacus_kpoints):
    workchain = _instantiate_base_workchain(abacus_inputs, abacus_kpoints)
    calculation = _make_failed_calc(303)

    report = workchain.handler_ionic_convergence(calculation)

    assert report.exit_code.status == workchain.exit_codes.ERROR_KNOWN_UNRECOVERABLE_FAILURE.status
