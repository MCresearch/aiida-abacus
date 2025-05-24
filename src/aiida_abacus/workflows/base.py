"""
Base workflows for Abacus calculation
"""

import pathlib
from typing import Union

from aiida import orm
from aiida.common import AttributeDict, exceptions
from aiida.common.exceptions import NotExistent
from aiida.common.lang import type_check
from aiida.engine import calcfunction, while_
from aiida.engine.processes.workchains.restart import BaseRestartWorkChain
from aiida.orm.nodes.data.base import to_aiida_type
from aiida.plugins import GroupFactory
from aiida_pseudo.groups.family import PseudoPotentialFamily

from aiida_abacus.calculations import AbacusCalculation
from aiida_abacus.common import (
    ElectronicType,
    ProtocolMixin,
    SpinType,
    recursive_merge,
)
from aiida_abacus.group.orb_group import AtomicOrbitalFamily


class AbacusBaseWorkChain(ProtocolMixin, BaseRestartWorkChain):
    """
    Base restart workflow for abacus.
    """

    _process_class = AbacusCalculation

    @classmethod
    def get_protocol_filepath(cls) -> pathlib.Path:
        """Return the ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        return pathlib.Path(__file__).parent.parent / "protocols/base.yaml"

    @classmethod
    def define(cls, spec):
        """
        Define the work chain specification.
        """
        super().define(spec)

        spec.expose_inputs(AbacusCalculation, namespace="abacus", exclude=("kpoints",))
        spec.input(
            "kpoints",
            valid_type=orm.KpointsData,
            required=False,
            help="An explicit k-points list or mesh. Either this or `kpoints_distance` has to be provided.",
        )
        spec.input(
            "kpoints_distance",
            valid_type=orm.Float,
            required=False,
            serializer=to_aiida_type,
            help="The minimum desired distance in 1/Å between k-points in reciprocal space. The explicit k-points will "
            "be generated automatically by a calculation function based on the input structure.",
        )
        spec.input(
            "kpoints_force_parity",
            valid_type=orm.Bool,
            serializer=to_aiida_type,
            required=False,
            help="Optional input when constructing the k-points based on a desired `kpoints_distance`. Setting this to "
            "`True` will force the k-point mesh to have an even number of points along each lattice vector except "
            "for any non-periodic directions.",
        )
        spec.input(
            "pseudo_family",
            valid_type=orm.Str,
            serializer=to_aiida_type,
            required=False,
            help="Name of pseudopotential family to use for the calculation.",
            validator=check_pseudo_family,
        )
        spec.outline(
            cls.setup,
            cls.validate_kpoints,
            while_(cls.should_run_process)(
                cls.prepare_process,
                cls.run_process,
                cls.inspect_process,
            ),
            cls.results,
        )
        spec.expose_outputs(AbacusCalculation)
        spec.exit_code(
            201,
            "ERROR_INVALID_INPUT_PSEUDO_POTENTIALS",
            message="The explicit `pseudos` or `pseudo_family` could not be used to get the necessary pseudos.",
        )
        spec.exit_code(
            202,
            "ERROR_INVALID_INPUT_KPOINTS",
            message="Neither the `kpoints` nor the `kpoints_distance` input was specified.",
        )
        spec.exit_code(
            203,
            "ERROR_INVALID_INPUT_RESOURCES",
            message="Neither the `options` nor `automatic_parallelization` input was specified. "
            "This exit status has been deprecated as the check it corresponded to was incorrect.",
        )
        spec.exit_code(
            204,
            "ERROR_INVALID_INPUT_RESOURCES_UNDERSPECIFIED",
            message="The `metadata.options` did not specify both `resources.num_machines` and `max_wallclock_seconds`. "
            "This exit status has been deprecated as the check it corresponded to was incorrect.",
        )
        spec.exit_code(
            300,
            "ERROR_UNRECOVERABLE_FAILURE",
            message="The calculation failed with an unidentified unrecoverable error.",
        )
        spec.exit_code(
            310, "ERROR_KNOWN_UNRECOVERABLE_FAILURE", message="The calculation failed with a known unrecoverable error."
        )
        spec.exit_code(320, "ERROR_INITIALIZATION_CALCULATION_FAILED", message="The initialization calculation failed.")
        spec.exit_code(
            501,
            "ERROR_IONIC_CONVERGENCE_REACHED_EXCEPT_IN_FINAL_SCF",
            message="Then ionic minimization cycle converged but the thresholds are exceeded in the final SCF.",
        )
        spec.exit_code(
            710,
            "WARNING_ELECTRONIC_CONVERGENCE_NOT_REACHED",
            message="The electronic minimization cycle did not reach self-consistency, but `scf_must_converge` "
            "is `False` and/or `electron_maxstep` is 0.",
        )

    def validate_kpoints(self):
        """Validate the inputs related to k-points.

        Either an explicit `KpointsData` with given mesh/path, or a desired k-points distance should be specified. In
        the case of the latter, the `KpointsData` will be constructed for the input `StructureData` using the
        `create_kpoints_from_distance` calculation function.
        """
        if all(key not in self.inputs for key in ["kpoints", "kpoints_distance"]):
            return self.exit_codes.ERROR_INVALID_INPUT_KPOINTS

        try:
            kpoints = self.inputs.kpoints
        except AttributeError:
            inputs = {
                "structure": self.inputs.abacus.structure,
                "distance": self.inputs.kpoints_distance,
                "force_parity": self.inputs.get("kpoints_force_parity", orm.Bool(False)),
                "metadata": {"call_link_label": "create_kpoints_from_distance"},
            }
            kpoints = create_kpoints_from_distance(**inputs)  # pylint: disable=unexpected-keyword-arg

        self.ctx.inputs.kpoints = kpoints

    def report_error_handled(self, calculation, action):
        """Report an action taken for a calculation that has failed.

        This should be called in a registered error handler if its condition is met and an action was taken.

        :param calculation: the failed calculation node
        :param action: a string message with the action taken
        """
        arguments = [calculation.process_label, calculation.pk, calculation.exit_status, calculation.exit_message]
        self.report("{}<{}> failed with exit status {}: {}".format(*arguments))
        self.report(f"Action taken: {action}")

    def setup(self):
        """Call the ``setup`` of the ``BaseRestartWorkChain`` and create the inputs dictionary in ``self.ctx.inputs``.

        This ``self.ctx.inputs`` dictionary will be used by the ``BaseRestartWorkChain`` to submit the calculations
        in the internal loop.

        The ``parameters`` and ``settings`` input ``Dict`` nodes are converted into a regular dictionary and the
        default namelists for the ``parameters`` are set to empty dictionaries if not specified.
        """
        super().setup()
        self.ctx.inputs = AttributeDict(self.exposed_inputs(AbacusCalculation, "abacus"))

        self.ctx.inputs.parameters = self.ctx.inputs.parameters.get_dict()
        if "pseudo_family" in self.inputs:
            pseudos, cutoff_wfc, _ = get_pseudos_cutoff_via_family(
                self.inputs.abacus.structure, self.inputs.pseudo_family.value
            )
            self.ctx.inputs.pseudos = pseudos
            # Set the default ecutwfc if not specified
            if self.ctx.inputs.parameters["input"].get("ecutwfc", None) is None:
                self.ctx.inputs.parameters["input"]["ecutwfc"] = cutoff_wfc
                self.report(f"Using the default cut off energy from the pseudopotentials {cutoff_wfc} Ry.")

        # calculation_type = self.ctx.inputs.parameters['input'].get('type', 'scf')

        self.ctx.inputs.settings = self.ctx.inputs.settings.get_dict() if "settings" in self.ctx.inputs else {}

    def prepare_process(self):
        """Prepare the inputs for the next calculation."""
        pass

    @classmethod
    def get_builder_from_protocol(
        cls,
        code,
        structure,
        protocol=None,
        overrides=None,
        electronic_type=ElectronicType.METAL,
        spin_type=SpinType.NONE,
        initial_magnetic_moments=None,
        options=None,
        **_,
    ):
        """Return a builder prepopulated with inputs selected according to the chosen protocol.

        :param code: the ``Code`` instance configured for the ``abacus.abacus`` plugin.
        :param structure: the ``StructureData`` instance to use.
        :param protocol: protocol to use, if not specified, the default will be used.
        :param overrides: optional dictionary of inputs to override the defaults of the protocol.
        :param electronic_type: indicate the electronic character of the system through ``ElectronicType`` instance.
        :param spin_type: indicate the spin polarization type to use through a ``SpinType`` instance.
        :param initial_magnetic_moments: optional dictionary that maps the initial magnetic moment of each kind to a
            desired value for a spin polarized calculation. Note that in case the ``starting_magnetization`` is also
            provided in the ``overrides``, this takes precedence over the values provided here. In case neither is
            provided and ``spin_type == SpinType.COLLINEAR``, an initial guess for the magnetic moments is used.
        :param options: A dictionary of options that will be recursively set for the ``metadata.options`` input of all
            the ``CalcJobs`` that are nested in this work chain.
        :return: a process builder instance with all inputs defined ready for launch.
        """

        if isinstance(code, str):
            code = orm.load_code(code)

        type_check(code, orm.AbstractCode)
        type_check(electronic_type, ElectronicType)
        type_check(spin_type, SpinType)

        if electronic_type not in [ElectronicType.METAL, ElectronicType.INSULATOR]:
            raise NotImplementedError(f"electronic type `{electronic_type}` is not supported.")

        if spin_type not in [SpinType.NONE, SpinType.COLLINEAR]:
            raise NotImplementedError(f"spin type `{spin_type}` is not supported.")

        if initial_magnetic_moments is not None and spin_type is not SpinType.COLLINEAR:
            raise ValueError(f"`initial_magnetic_moments` is specified but spin type `{spin_type}` is incompatible.")

        inputs = cls.get_protocol_inputs(protocol, overrides)

        meta_parameters = inputs.pop("meta_parameters")
        pseudo_family_name = inputs.pop("pseudo_family")

        natoms = len(structure.sites)

        pseudos, cutoff_wfc, cutoff_rho = get_pseudos_cutoff_via_family(structure, pseudo_family_name)
        # Update the parameters based on the protocol inputs
        parameters = inputs["abacus"]["parameters"]
        parameters["input"]["scf_thr"] = natoms * meta_parameters["conv_thr_per_atom"]
        # Set the wavefunction cutoff energy
        if cutoff_wfc is not None:
            parameters["input"]["ecutwfc"] = cutoff_wfc

        if electronic_type is ElectronicType.INSULATOR:
            parameters["input"]["smearing_method"] = "fixed"

        if spin_type is SpinType.COLLINEAR:
            # Set the initial magnetization
            pass

        # If overrides are provided, they are considered absolute
        if overrides:
            parameter_overrides = overrides.get("abacus", {}).get("parameters", {})
            parameters = recursive_merge(parameters, parameter_overrides)

            # # if tot_magnetization in overrides , remove starting_magnetization from parameters
            # if parameters.get('stru', {}).get('tot_magnetization') is not None:
            #     parameters.setdefault('stru', {}).pop('starting_magnetization', None)

            pseudos_overrides = overrides.get("abacus", {}).get("pseudos", {})
            pseudos = recursive_merge(pseudos, pseudos_overrides)

        metadata = inputs["abacus"]["metadata"]

        if options:
            metadata["options"] = recursive_merge(inputs["abacus"]["metadata"]["options"], options)

        # pylint: disable=no-member
        builder = cls.get_builder()
        builder.abacus["code"] = code
        builder.abacus["pseudos"] = pseudos
        builder.abacus["structure"] = structure
        builder.abacus["parameters"] = orm.Dict(parameters)
        builder.abacus["metadata"] = metadata
        if "settings" in inputs["abacus"]:
            builder.abacus["settings"] = orm.Dict(inputs["abacus"]["settings"])
        builder.clean_workdir = orm.Bool(inputs["clean_workdir"])
        if "kpoints" in inputs:
            builder.kpoints = inputs["kpoints"]
        else:
            builder.kpoints_distance = orm.Float(inputs["kpoints_distance"])
        builder.kpoints_force_parity = orm.Bool(inputs["kpoints_force_parity"])
        builder.max_iterations = orm.Int(inputs["max_iterations"])
        # pylint: enable=no-member

        return builder


@calcfunction
def create_kpoints_from_distance(structure, distance, force_parity):
    """Generate a uniformly spaced kpoint mesh for a given structure.
    Based on aiida-abacus's function `create_kpoints_from_distance`

    The spacing between kpoints in reciprocal space is guaranteed to be at least the defined distance.

    :param structure: the StructureData to which the mesh should apply
    :param distance: a Float with the desired distance between kpoints in reciprocal space
    :param force_parity: a Bool to specify whether the generated mesh should maintain parity
    :returns: a KpointsData with the generated mesh
    """
    from aiida.orm import KpointsData
    from numpy import linalg

    epsilon = 1e-5

    kpoints = KpointsData()
    kpoints.set_cell_from_structure(structure)
    kpoints.set_kpoints_mesh_from_density(distance.value, force_parity=force_parity.value)

    lengths_vector = [linalg.norm(vector) for vector in structure.cell]
    lengths_kpoint = kpoints.get_kpoints_mesh()[0]

    is_symmetric_cell = all(abs(length - lengths_vector[0]) < epsilon for length in lengths_vector)
    is_symmetric_mesh = all(length == lengths_kpoint[0] for length in lengths_kpoint)

    # If the vectors of the cell all have the same length, the kpoint mesh should be isotropic as well
    if is_symmetric_cell and not is_symmetric_mesh:
        nkpoints = max(lengths_kpoint)
        kpoints.set_kpoints_mesh([nkpoints, nkpoints, nkpoints])

    return kpoints


def check_pseudo_family(family_name: Union[str, orm.Str]):
    """Check the existence of a pseudo family"""
    if isinstance(family_name, orm.Str):
        family_name = family_name.value
    try:
        group = orm.load_group(family_name)
    except NotExistent:
        raise NotExistent(f"Pseudo family {family_name} does not exist")
    if not isinstance(group, PseudoPotentialFamily):
        raise ValueError(f"Pseudo family {family_name} is not a pseudo family")


def get_pseudos_cutoff_via_family(structure: orm.StructureData, pseudo_family_name: str) -> tuple:
    """
    Set up the pseudos and cutoffs for the given structure with the given pseudo family.
    :param structure: the structure to get the pseudos for
    :param pseudo_family_name: the name of the pseudo family
    :return: a tuple of pseudos, cutoff_wfc, cutoff_rho
    """
    # Setting up the pseudo that is a dojo family
    pseudo_family = None
    cutoff_wfc = None
    cutoff_rho = None
    # Check for existing AtomicOrbitalFamily
    try:
        pseudo_family = orm.QueryBuilder().append(AtomicOrbitalFamily, filters={"label": pseudo_family_name}).one()[0]
        pseudos = pseudo_family.get_pseudos(structure=structure)
        cutoff_wfc = next(iter(pseudos.values())).cut_off_energy  # Use the first pseudo's cut off energy
    except exceptions.NotExistent:
        pass
    if pseudo_family is not None:
        return pseudos, cutoff_wfc, cutoff_rho

    # Check for pseudo_dojo family
    try:
        family = GroupFactory("pseudo.family.pseudo_dojo")
        cutoffs = GroupFactory("pseudo.family.cutoffs")
        pseudo_set = (family, cutoffs)
        pseudo_family = orm.QueryBuilder().append(pseudo_set, filters={"label": pseudo_family_name}).one()[0]
    except exceptions.NotExistent as exception:
        raise ValueError(
            f"required pseudo family `{pseudo_family}` is not installed. Please use `aiida-pseudo install` to"
            "install it."
        ) from exception

    try:
        cutoff_wfc, cutoff_rho = pseudo_family.get_recommended_cutoffs(structure=structure, unit="Ry")
        pseudos = pseudo_family.get_pseudos(structure=structure)
    except ValueError as exception:
        raise ValueError(
            f"failed to obtain recommended cutoffs for pseudo family `{pseudo_family}`: {exception}"
        ) from exception
    # TODO - support for SSSP and other families
    return pseudos, cutoff_wfc, cutoff_rho
