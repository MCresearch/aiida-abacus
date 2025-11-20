import os
from pathlib import Path

import pytest
from aiida import orm
from aiida.common.exceptions import NotExistent
from aiida.common.extendeddicts import AttributeDict
from aiida.common.links import LinkType
from aiida.engine.utils import instantiate_process
from aiida.manage.manager import get_manager
from aiida.orm import CalcJobNode
from aiida.plugins import DataFactory

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
pytest_plugins = "aiida.tools.pytest_fixtures"


@pytest.fixture(scope="module")
def data_folder():
    return Path(TEST_DIR) / "test_data"


@pytest.fixture(scope="session")
def localhost_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("localhost_work")


@pytest.fixture()
def localhost(aiida_profile_clean, localhost_dir):
    """Fixture for a local computer called localhost. This is currently not in the AiiDA fixtures."""
    try:
        computer = orm.Computer.collection.get(label="localhost")
    except NotExistent:
        computer = orm.Computer(
            label="localhost",
            hostname="localhost",
            transport_type="core.local",
            scheduler_type="core.direct",
            workdir=str(localhost_dir),
        ).store()
        computer.set_minimum_job_poll_interval(0.0)
        computer.configure()
    return computer


@pytest.fixture()
def abacus_code(localhost):
    """Fixture for a abacus code, the executable it points to does not exist."""

    if not localhost.pk:
        localhost.store()
    code = orm.InstalledCode(localhost, "/usr/local/bin/abacus")
    code.label = "abacus"
    code.description = "abacus code"
    code.default_calc_job_plugin = "abacus.abacus"
    code.store()
    return code


@pytest.fixture
def abacus_params(aiida_profile_clean):
    incar_data = orm.Dict(dict={"gga": "PE", "gga_compat": False, "lorbit": 11, "sigma": 0.5, "magmom": "30 * 2*0."})
    return incar_data


@pytest.fixture
def bulk_structure(aiida_profile_clean):
    """Returns a orm.StructureData"""
    from ase.build import bulk

    def inner(*args, **kwargs):
        atoms = bulk(*args, **kwargs)
        return orm.StructureData(ase=atoms)

    return inner


@pytest.fixture
def si_structure(bulk_structure):
    """Returns a orm.StructureData"""
    return bulk_structure("Si", "diamond", 5.4)


@pytest.fixture
def abacus_param(aiida_profile_clean):
    """Some default parameters for Abacus"""
    input_dict = {
        "symmetry": 1,
        "basis_type": "pw",
        "ecutwfc": 60,
        "scf_thr": 1e-7,
        "scf_nmax": 100,
        "device": "cpu",
        "ks_solver": "dav_subspace",
        "precision": "double",
    }
    return orm.Dict({"input": input_dict})


@pytest.fixture
def abacus_kpoints(aiida_profile_clean):
    """Fixture: kpoints object"""
    from aiida.plugins import DataFactory

    kpoints = DataFactory("core.array.kpoints")()
    kpoints.set_kpoints_mesh([2, 2, 2])
    return kpoints


@pytest.fixture
def pseudo_familty(aiida_profile_clean, data_folder):
    """Create a Pseudopotential Family"""
    from aiida_pseudo.data.pseudo import UpfData
    from aiida_pseudo.groups.family import PseudoPotentialFamily

    family = PseudoPotentialFamily.create_from_folder(data_folder / "pseudos", "aiida-abacus-test", pseudo_type=UpfData)
    return family


@pytest.fixture
def pseudo_family_v2(aiida_profile_clean, data_folder):
    """
    Create a Pseudopotential Family namded apns-efficiency-test
    The group contains pseudopotentials for Si, Mg, O
    """
    from aiida.orm import load_group
    from aiida.tools.archive import import_archive

    import_archive(data_folder / "pseudos.aiida")
    return load_group("apns-efficiency-test")


@pytest.fixture()
def abacus_inputs(aiida_profile_clean, abacus_param, abacus_kpoints, si_structure, pseudo_familty, abacus_code):
    """Inputs dictionary for CalcJob Processes."""

    def inner(settings=None, parameters=None):
        """Inner function to prepare a calculation with pre-defined
        parameters and settings"""
        inputs = AttributeDict()

        metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

        if settings is not None:
            inputs.settings = orm.Dict(dict=settings)

        if isinstance(parameters, dict):
            parameters = orm.Dict(dict=parameters)

        if parameters is None:
            parameters = AttributeDict(abacus_param.get_dict())
            parameters = orm.Dict(dict=parameters)

        inputs.code = abacus_code
        inputs.metadata = metadata
        inputs.parameters = parameters
        inputs.kpoints = abacus_kpoints
        inputs.structure = si_structure
        inputs.pseudos = pseudo_familty.get_pseudos(structure=inputs.structure)

        return inputs

    return inner


@pytest.fixture()
def sandbox_folder():
    """Yield a `SandboxFolder` that can be used for tests where a Folder is needed."""
    from aiida.common.folders import SandboxFolder

    with SandboxFolder() as folder:
        yield folder


@pytest.fixture()
def abacus_calc(aiida_profile_clean, abacus_inputs, abacus_code):
    """An instance of a VaspCalcBase Process."""
    from aiida_abacus.calculations import AbacusCalculation

    manager = get_manager()
    runner = manager.get_runner()
    inputs = AttributeDict()

    metadata = AttributeDict({"options": {"resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}}})

    inputs.code = abacus_code
    inputs.metadata = metadata

    settings = {}
    parameters = {"input": {"basis_type": "pw"}}
    inputs = abacus_inputs(settings, parameters)

    return instantiate_process(runner, AbacusCalculation, **inputs)


@pytest.fixture()
def calc_with_retrieved(localhost):
    """A rigged CalcJobNode for testing the parser and that the calculation retrieve what is expected."""

    def _inner(file_path, parameters=None, settings=None):
        # Create a test computer
        computer = localhost

        process_type = "aiida.calculations:abacus.abacus"

        node = CalcJobNode(computer=computer, process_type=process_type)
        node.base.attributes.set("input_filename", "INPUT")
        node.base.attributes.set("output_filename", "running_scf.log")
        node.set_option("resources", {"num_machines": 1, "num_mpiprocs_per_machine": 1})
        node.set_option("max_wallclock_seconds", 1800)

        settings = settings or {}
        parameters = parameters or {"input": {"calculation": "scf"}}

        settings = DataFactory("core.dict")(dict=settings)
        node.base.links.add_incoming(settings, link_type=LinkType.INPUT_CALC, link_label="settings")
        settings.store()

        # Add parameters input
        parameters = DataFactory("core.dict")(dict=parameters)
        node.base.links.add_incoming(parameters, link_type=LinkType.INPUT_CALC, link_label="parameters")
        parameters.store()

        node.store()

        # Create a `FolderData` that will represent the `retrieved` folder. Store the test
        # output fixture in there and link it.
        retrieved = DataFactory("core.folder")()
        retrieved.base.repository.put_object_from_tree(file_path)
        retrieved.base.links.add_incoming(node, link_type=LinkType.CREATE, link_label="retrieved")
        retrieved.store()

        return node

    return _inner
