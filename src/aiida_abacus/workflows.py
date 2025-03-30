"""
Workflows
"""

import pathlib

from aiida import orm
from aiida.common import AttributeDict, exceptions
from aiida.common.lang import type_check
from aiida.engine import ToContext, WorkChain, append_, calcfunction, if_, while_
from aiida.engine.processes.workchains.restart import BaseRestartWorkChain
from aiida.plugins import GroupFactory

from aiida_abacus.calculations import AbacusCalculation
from aiida_abacus.common import (
    ElectronicType,
    ProtocolMixin,
    RelaxType,
    SpinType,
    prepare_process_inputs,
    recursive_merge,
)

PseudoDojoFamily = GroupFactory("pseudo.family.pseudo_dojo")
CutoffsPseudoPotentialFamily = GroupFactory("pseudo.family.cutoffs")


class AbacusWorkChain(ProtocolMixin, BaseRestartWorkChain):
    """
    Base restart workflow for abacus.
    """

    _process_class = AbacusCalculation

    @classmethod
    def get_protocol_filepath(cls) -> pathlib.Path:
        """Return the ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        return pathlib.Path(__file__).parent / "protocols/base.yaml"

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
            help="The minimum desired distance in 1/Å between k-points in reciprocal space. The explicit k-points will "
            "be generated automatically by a calculation function based on the input structure.",
        )
        spec.input(
            "kpoints_force_parity",
            valid_type=orm.Bool,
            required=False,
            help="Optional input when constructing the k-points based on a desired `kpoints_distance`. Setting this to "
            "`True` will force the k-point mesh to have an even number of points along each lattice vector except "
            "for any non-periodic directions.",
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
        pseudo_family = inputs.pop("pseudo_family")

        natoms = len(structure.sites)

        try:
            pseudo_set = (PseudoDojoFamily, CutoffsPseudoPotentialFamily)
            pseudo_family = orm.QueryBuilder().append(pseudo_set, filters={"label": pseudo_family}).one()[0]
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

        # Update the parameters based on the protocol inputs
        parameters = inputs["abacus"]["parameters"]
        parameters["input"]["scf_thr"] = natoms * meta_parameters["conv_thr_per_atom"]
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


def validate_relax_inputs(inputs, _):
    """Validate the top level namespace."""
    parameters = inputs["base"]["abacus"]["parameters"].get_dict()

    if "calculation" not in parameters.get("input", {}):
        return "The parameters in `base.abacus.parameters` do not specify the required key `input.calculation`."


class AbacusRelaxWorkchain(ProtocolMixin, WorkChain):
    """Workchain to relax a structure using Abacus"""

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        # yapf: disable
        super().define(spec)
        spec.expose_inputs(AbacusWorkChain, namespace='base',
            exclude=('clean_workdir', 'abacus.structure', 'abacus.parent_folder'),
            namespace_options={'help': 'Inputs for the `AbacusWorkChain` for the main relax loop.'})
        spec.expose_inputs(AbacusWorkChain, namespace='base_final_scf',
            exclude=('clean_workdir', 'abacus.structure', 'abacus.parent_folder'),
            namespace_options={'required': False, 'populate_defaults': False,
                'help': 'Inputs for the `AbacusWorkChain` for the final scf.'})
        spec.input('structure', valid_type=orm.StructureData, help='The inputs structure.')
        spec.input('meta_convergence', valid_type=orm.Bool, default=lambda: orm.Bool(True),
            help='If `True` the workchain will perform a meta-convergence on the cell volume.')
        spec.input('max_meta_convergence_iterations', valid_type=orm.Int, default=lambda: orm.Int(5),
            help='The maximum number of variable cell relax iterations in the meta convergence cycle.')
        spec.input('volume_convergence', valid_type=orm.Float, default=lambda: orm.Float(0.01),
            help='The volume difference threshold between two consecutive meta convergence iterations.')
        spec.input('clean_workdir', valid_type=orm.Bool, default=lambda: orm.Bool(False),
            help='If `True`, work directories of all called calculation will be cleaned at the end of execution.')
        spec.inputs.validator = validate_relax_inputs
        spec.outline(
            cls.setup,
            while_(cls.should_run_relax)(
                cls.run_relax,
                cls.inspect_relax,
            ),
            if_(cls.should_run_final_scf)(
                cls.run_final_scf,
                cls.inspect_final_scf,
            ),
            cls.results,
        )
        spec.exit_code(401, 'ERROR_SUB_PROCESS_FAILED_RELAX',
            message='the relax AbacusWorkChain sub process failed')
        spec.exit_code(402, 'ERROR_SUB_PROCESS_FAILED_FINAL_SCF',
            message='the final scf AbacusWorkChain sub process failed')
        spec.expose_outputs(AbacusWorkChain, exclude=('structure',))
        spec.output('structure', valid_type=orm.StructureData, required=False,
            help='The successfully relaxed structure.')
        # yapf: enable

    @classmethod
    def get_protocol_filepath(cls) -> pathlib.Path:
        """Return the ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        return pathlib.Path(__file__).parent / "protocols/relax.yaml"

    @classmethod
    def get_builder_from_protocol(
        cls, code, structure, protocol=None, overrides=None, relax_type=RelaxType.POSITIONS_CELL, options=None, **kwargs
    ):
        """Return a builder prepopulated with inputs selected according to the chosen protocol.

        :param code: the ``Code`` instance configured for the ``abacus.abacus`` plugin.
        :param structure: the ``StructureData`` instance to use.
        :param protocol: protocol to use, if not specified, the default will be used.
        :param overrides: optional dictionary of inputs to override the defaults of the protocol.
        :param relax_type: the relax type to use: should be a value of the enum ``common.types.RelaxType``.
        :param options: A dictionary of options that will be recursively set for the ``metadata.options`` input of all
            the ``CalcJobs`` that are nested in this work chain.
        :param kwargs: additional keyword arguments that will be passed to the ``get_builder_from_protocol`` of all the
            sub processes that are called by this workchain.
        :return: a process builder instance with all inputs defined ready for launch.
        """
        type_check(relax_type, RelaxType)

        inputs = cls.get_protocol_inputs(protocol, overrides)

        args = (code, structure, protocol)
        base = AbacusWorkChain.get_builder_from_protocol(
            *args, overrides=inputs.get("base", None), options=options, **kwargs
        )
        base_final_scf = AbacusWorkChain.get_builder_from_protocol(
            *args, overrides=inputs.get("base_final_scf", None), options=options, **kwargs
        )

        base["abacus"].pop("structure", None)
        base.pop("clean_workdir", None)
        base_final_scf["abacus"].pop("structure", None)
        base_final_scf.pop("clean_workdir", None)

        # Map relaxation types to the corresponding abacus input parameters
        # See: http://abacus.deepmodeling.com/en/latest/advanced/opt.html#fixing-cell-parameters
        # for more detail
        if relax_type is RelaxType.NONE:
            base.abacus.parameters["input"]["calculation"] = "scf"

        if relax_type is RelaxType.POSITIONS:
            base.abacus.parameters["input"]["calculation"] = "relax"
        else:
            # Variable cell relaxation
            base.abacus.parameters["input"]["calculation"] = "cell-relax"

        if relax_type is RelaxType.VOLUME:
            base.abacus.parameters["input"]["fixed_axes"] = "shape"
            base.abacus.parameters["input"]["fixed_atoms"] = True

        if relax_type is RelaxType.SHAPE:
            base.abacus.parameters["input"]["fixed_axes"] = "volume"
            base.abacus.parameters["input"]["fixed_atoms"] = True

        if relax_type is RelaxType.CELL:
            base.abacus.parameters["input"]["fixed_atoms"] = True

        if relax_type is RelaxType.POSITIONS_SHAPE:
            base.abacus.parameters["input"]["fixed_axes"] = "volume"

        if relax_type is RelaxType.POSITIONS_VOLUME:
            base.abacus.parameters["CELL"]["fixed_axes"] = "shape"

        builder = cls.get_builder()
        builder.base = base
        builder.base_final_scf = base_final_scf
        builder.structure = structure
        builder.clean_workdir = orm.Bool(inputs["clean_workdir"])
        builder.max_meta_convergence_iterations = orm.Int(inputs["max_meta_convergence_iterations"])
        builder.meta_convergence = orm.Bool(inputs["meta_convergence"])
        builder.volume_convergence = orm.Float(inputs["volume_convergence"])

        return builder

    def setup(self):
        """Input validation and context setup."""
        self.ctx.current_number_of_bands = None
        self.ctx.current_structure = self.inputs.structure
        self.ctx.current_cell_volume = None
        self.ctx.is_converged = False
        self.ctx.iteration = 0

        self.ctx.relax_inputs = AttributeDict(self.exposed_inputs(AbacusWorkChain, namespace="base"))
        self.ctx.relax_inputs.abacus.parameters = self.ctx.relax_inputs.abacus.parameters.get_dict()

        self.ctx.relax_inputs.abacus.parameters.setdefault("input", {})

        # Set the meta_convergence and add it to the context
        self.ctx.meta_convergence = self.inputs.meta_convergence.value
        volume_cannot_change = self.ctx.relax_inputs.abacus.parameters["input"].get("calculation", "scf") in (
            "scf",
            "relax",
        )
        if self.ctx.meta_convergence and volume_cannot_change:
            self.report(
                "No change in volume possible for the provided base input parameters. Meta convergence is turned off."
            )
            self.ctx.meta_convergence = False

        # Add the final scf inputs to the context if a final scf should be run
        if "base_final_scf" in self.inputs:
            self.ctx.final_scf_inputs = AttributeDict(self.exposed_inputs(AbacusWorkChain, namespace="base_final_scf"))

            if self.ctx.relax_inputs.abacus.parameters["input"].get("calculation", "scf") == "scf":
                self.report(
                    "Work chain will not run final SCF when `calculation` is set to `scf` for the relaxation "
                    "`AbacusWorkChain`."
                )
                self.ctx.pop("final_scf_inputs")

            else:
                self.ctx.final_scf_inputs.abacus.parameters = self.ctx.final_scf_inputs.abacus.parameters.get_dict()

                self.ctx.final_scf_inputs.abacus.parameters.setdefault("input", {})
                self.ctx.final_scf_inputs.metadata.call_link_label = "final_scf"

    def should_run_relax(self):
        """Return whether a relaxation workchain should be run.

        This is the case as long as the volume change between two consecutive relaxation runs is larger than the volume
        convergence threshold value and the maximum number of meta convergence iterations is not exceeded.
        """
        return not self.ctx.is_converged and self.ctx.iteration < self.inputs.max_meta_convergence_iterations.value

    def should_run_final_scf(self):
        """Return whether after successful relaxation a final scf calculation should be run.

        If the maximum number of meta convergence iterations has been exceeded and convergence has not been reached, the
        structure cannot be considered to be relaxed and the final scf should not be run.
        """
        return self.ctx.is_converged and "final_scf_inputs" in self.ctx

    def run_relax(self):
        """Run the `AbacusWorkChain` to run a relax `PwCalculation`."""
        self.ctx.iteration += 1

        inputs = self.ctx.relax_inputs
        inputs.abacus.structure = self.ctx.current_structure

        # If one of the nested `AbacusWorkChains` changed the number of bands, apply it here
        if self.ctx.current_number_of_bands is not None:
            inputs.abacus.parameters.setdefault("input", {})["nbands"] = self.ctx.current_number_of_bands

        # Set the `CALL` link label
        inputs.metadata.call_link_label = f"iteration_{self.ctx.iteration:02d}"

        inputs = prepare_process_inputs(AbacusWorkChain, inputs)
        running = self.submit(AbacusWorkChain, **inputs)

        self.report(f"launching AbacusWorkChain<{running.pk}>")

        return ToContext(workchains=append_(running))

    def inspect_relax(self):
        """Inspect the results of the last `AbacusWorkChain`.

        Compare the cell volume of the relaxed structure of the last completed workchain with the previous. If the
        difference ratio is less than the volume convergence threshold we consider the cell relaxation converged.
        """
        workchain = self.ctx.workchains[-1]

        acceptable_statuses = ["ERROR_IONIC_CONVERGENCE_REACHED_EXCEPT_IN_FINAL_SCF"]

        if workchain.is_excepted or workchain.is_killed:
            self.report("relax AbacusWorkChain was excepted or killed")
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_RELAX

        if workchain.is_failed and workchain.exit_status not in AbacusWorkChain.get_exit_statuses(acceptable_statuses):
            self.report(f"relax AbacusWorkChain failed with exit status {workchain.exit_status}")
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_RELAX

        try:
            structure = workchain.outputs.structure
        except exceptions.NotExistent:
            # If the calculation is set to 'scf', this is expected, so we are done
            if self.ctx.relax_inputs.abacus.parameters["input"]["calculation"] == "scf":
                self.ctx.is_converged = True
                return

            self.report("`cell-relax` or `relax` AbacusWorkChain finished successfully but without output structure")
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_RELAX

        prev_cell_volume = self.ctx.current_cell_volume
        curr_cell_volume = structure.get_cell_volume()

        # Set relaxed structure as input structure for next iteration
        self.ctx.current_structure = structure
        self.ctx.current_number_of_bands = workchain.outputs.misc.get_dict()["number_of_bands"]
        self.report(f"after iteration {self.ctx.iteration} cell volume of relaxed structure is {curr_cell_volume}")

        # After first iteration, simply set the cell volume and restart the next base workchain
        if not prev_cell_volume:
            self.ctx.current_cell_volume = curr_cell_volume

            # If meta convergence is switched off we are done
            if not self.ctx.meta_convergence:
                self.ctx.is_converged = True
            return

        # Check whether the cell volume is converged
        volume_threshold = self.inputs.volume_convergence.value
        volume_difference = abs(prev_cell_volume - curr_cell_volume) / prev_cell_volume

        if volume_difference < volume_threshold:
            self.ctx.is_converged = True
            self.report(
                f"relative cell volume difference {volume_difference} smaller than threshold {volume_threshold}"
            )
        else:
            self.report(
                f"current relative cell volume difference {volume_difference} larger than threshold {volume_threshold}"
            )

        self.ctx.current_cell_volume = curr_cell_volume

        return

    def run_final_scf(self):
        """Run the `AbacusWorkChain` to run a final scf `PwCalculation` for the relaxed structure."""
        inputs = self.ctx.final_scf_inputs
        inputs.abacus.structure = self.ctx.current_structure

        inputs_nbnd = inputs.abacus.parameters.get("input", {}).get("nbands", None)
        if self.ctx.current_number_of_bands is not None and inputs_nbnd is None:
            inputs.abacus.parameters.setdefault("input", {})["nbands"] = self.ctx.current_number_of_bands

        inputs = prepare_process_inputs(AbacusWorkChain, inputs)
        running = self.submit(AbacusWorkChain, **inputs)

        self.report(f"launching AbacusWorkChain<{running.pk}> for final scf")

        return ToContext(workchain_scf=running)

    def inspect_final_scf(self):
        """Inspect the result of the final scf `AbacusWorkChain`."""
        workchain = self.ctx.workchain_scf

        if not workchain.is_finished_ok:
            self.report(f"final scf AbacusWorkChain failed with exit status {workchain.exit_status}")
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_FINAL_SCF

    def results(self):
        """Attach the output parameters and structure of the last workchain to the outputs."""
        if self.ctx.is_converged and self.ctx.iteration <= self.inputs.max_meta_convergence_iterations.value:
            self.report(f"workchain completed after {self.ctx.iteration} iterations")
        else:
            self.report("maximum number of meta convergence iterations exceeded")

        # Get the latest relax workchain and pass the outputs
        final_relax_workchain = self.ctx.workchains[-1]

        if self.ctx.relax_inputs.abacus.parameters["input"]["calculation"] != "scf":
            self.out("structure", final_relax_workchain.outputs.structure)

        try:
            self.out_many(self.exposed_outputs(self.ctx.workchain_scf, AbacusWorkChain))
        except AttributeError:
            self.out_many(self.exposed_outputs(final_relax_workchain, AbacusWorkChain))

    def on_terminated(self):
        """Clean the working directories of all child calculations if `clean_workdir=True` in the inputs."""
        super().on_terminated()

        if self.inputs.clean_workdir.value is False:
            self.report("remote folders will not be cleaned")
            return

        cleaned_calcs = []

        for called_descendant in self.node.called_descendants:
            if isinstance(called_descendant, orm.CalcJobNode):
                try:
                    called_descendant.outputs.remote_folder._clean()  # pylint: disable=protected-access
                    cleaned_calcs.append(called_descendant.pk)
                except (IOError, OSError, KeyError):
                    pass

        if cleaned_calcs:
            self.report(f"cleaned remote folders of calculations: {' '.join(map(str, cleaned_calcs))}")
