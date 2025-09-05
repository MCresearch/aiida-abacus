"""
Workflows
"""

import pathlib

from aiida import orm
from aiida.common import AttributeDict, exceptions
from aiida.common.lang import type_check
from aiida.engine import ToContext, WorkChain, append_, if_, while_
from aiida.plugins import GroupFactory

from aiida_abacus.common import (
    ProtocolMixin,
    RelaxType,
    prepare_process_inputs,
)

from .base import AbacusBaseWorkChain

PseudoDojoFamily = GroupFactory("pseudo.family.pseudo_dojo")
CutoffsPseudoPotentialFamily = GroupFactory("pseudo.family.cutoffs")


def validate_relax_inputs(inputs, _):
    """Validate the top level namespace."""
    parameters = inputs["base"]["abacus"]["parameters"].get_dict()

    if "calculation" not in parameters.get("input", {}):
        return "The parameters in `base.abacus.parameters` do not specify the required key `input.calculation`."


class AbacusRelaxWorkChain(ProtocolMixin, WorkChain):
    """WorkChain to relax a structure using Abacus"""

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        # yapf: disable
        super().define(spec)
        spec.expose_inputs(AbacusBaseWorkChain, namespace="base",
            exclude=("clean_workdir", "abacus.structure", "abacus.parent_folder"),
            namespace_options={"help": "Inputs for the `AbacusBaseWorkChain` for the main relax loop."})
        spec.expose_inputs(AbacusBaseWorkChain, namespace="base_final_scf",
            exclude=("clean_workdir", "abacus.structure", "abacus.parent_folder"),
            namespace_options={"required": False, "populate_defaults": False,
                "help": "Inputs for the `AbacusBaseWorkChain` for the final scf."})
        spec.input("structure", valid_type=orm.StructureData, help="The inputs structure.")
        spec.input("meta_convergence", valid_type=orm.Bool, default=lambda: orm.Bool(True),
            help="If `True` the workchain will perform a meta-convergence on the cell volume.")
        spec.input("max_meta_convergence_iterations", valid_type=orm.Int, default=lambda: orm.Int(5),
            help="The maximum number of variable cell relax iterations in the meta convergence cycle.")
        spec.input("volume_convergence", valid_type=orm.Float, default=lambda: orm.Float(0.01),
            help="The volume difference threshold between two consecutive meta convergence iterations.")
        spec.input("clean_workdir", valid_type=orm.Bool, default=lambda: orm.Bool(False),
            help="If `True`, work directories of all called calculation will be cleaned at the end of execution.")
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
        spec.exit_code(401, "ERROR_SUB_PROCESS_FAILED_RELAX",
            message="the relax AbacusBaseWorkChain sub process failed")
        spec.exit_code(402, "ERROR_SUB_PROCESS_FAILED_FINAL_SCF",
            message="the final scf AbacusBaseWorkChain sub process failed")
        spec.expose_outputs(AbacusBaseWorkChain, exclude=("structure",))
        spec.output("structure", valid_type=orm.StructureData, required=False,
            help="The successfully relaxed structure.")
        # yapf: enable

    @classmethod
    def get_protocol_filepath(cls) -> pathlib.Path:
        """Return the ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        return pathlib.Path(__file__).parent.parent / "protocols/relax.yaml"

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
        base = AbacusBaseWorkChain.get_builder_from_protocol(
            *args, overrides=inputs.get("base", None), options=options, **kwargs
        )
        base_final_scf = AbacusBaseWorkChain.get_builder_from_protocol(
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
        elif relax_type is RelaxType.POSITIONS:
            base.abacus.parameters["input"]["calculation"] = "relax"
        else:
            # All other kinds quires cell change so it has to be cell-relax
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

        self.ctx.relax_inputs = AttributeDict(self.exposed_inputs(AbacusBaseWorkChain, namespace="base"))
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
            self.ctx.final_scf_inputs = AttributeDict(
                self.exposed_inputs(AbacusBaseWorkChain, namespace="base_final_scf")
            )

            if self.ctx.relax_inputs.abacus.parameters["input"].get("calculation", "scf") == "scf":
                self.report(
                    "Work chain will not run final SCF when `calculation` is set to `scf` for the relaxation "
                    "`AbacusBaseWorkChain`."
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
        """Run the `AbacusBaseWorkChain` to run a relax `PwCalculation`."""
        self.ctx.iteration += 1

        inputs = self.ctx.relax_inputs
        inputs.abacus.structure = self.ctx.current_structure

        # If one of the nested `AbacusBaseWorkChains` changed the number of bands, apply it here
        if self.ctx.current_number_of_bands is not None:
            inputs.abacus.parameters.setdefault("input", {})["nbands"] = self.ctx.current_number_of_bands

        # Set the `CALL` link label
        inputs.metadata.call_link_label = f"iteration_{self.ctx.iteration:02d}"

        inputs = prepare_process_inputs(AbacusBaseWorkChain, inputs)
        running = self.submit(AbacusBaseWorkChain, **inputs)

        self.report(f"launching AbacusBaseWorkChain<{running.pk}>")

        return ToContext(workchains=append_(running))

    def inspect_relax(self):
        """Inspect the results of the last `AbacusBaseWorkChain`.

        Compare the cell volume of the relaxed structure of the last completed workchain with the previous. If the
        difference ratio is less than the volume convergence threshold we consider the cell relaxation converged.
        """
        workchain = self.ctx.workchains[-1]

        acceptable_statuses = ["ERROR_IONIC_CONVERGENCE_REACHED_EXCEPT_IN_FINAL_SCF"]

        if workchain.is_excepted or workchain.is_killed:
            self.report("relax AbacusBaseWorkChain was excepted or killed")
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_RELAX

        if workchain.is_failed and workchain.exit_status not in AbacusBaseWorkChain.get_exit_statuses(
            acceptable_statuses
        ):
            self.report(f"relax AbacusBaseWorkChain failed with exit status {workchain.exit_status}")
            return self.exit_codes.ERROR_SUB_PROCESS_FAILED_RELAX

        try:
            structure = workchain.outputs.structure
        except exceptions.NotExistent:
            # If the calculation is set to 'scf', this is expected, so we are done
            if self.ctx.relax_inputs.abacus.parameters["input"]["calculation"] == "scf":
                self.ctx.is_converged = True
                return

            self.report(
                "`cell-relax` or `relax` AbacusBaseWorkChain finished successfully but without output structure"
            )
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
        """Run the `AbacusBaseWorkChain` to run a final scf `PwCalculation` for the relaxed structure."""
        inputs = self.ctx.final_scf_inputs
        inputs.abacus.structure = self.ctx.current_structure

        inputs_nbnd = inputs.abacus.parameters.get("input", {}).get("nbands", None)
        if self.ctx.current_number_of_bands is not None and inputs_nbnd is None:
            inputs.abacus.parameters.setdefault("input", {})["nbands"] = self.ctx.current_number_of_bands

        inputs = prepare_process_inputs(AbacusBaseWorkChain, inputs)
        running = self.submit(AbacusBaseWorkChain, **inputs)

        self.report(f"launching AbacusBaseWorkChain<{running.pk}> for final scf")

        return ToContext(workchain_scf=running)

    def inspect_final_scf(self):
        """Inspect the result of the final scf `AbacusBaseWorkChain`."""
        workchain = self.ctx.workchain_scf

        if not workchain.is_finished_ok:
            self.report(f"final scf AbacusBaseWorkChain failed with exit status {workchain.exit_status}")
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
            self.out_many(self.exposed_outputs(self.ctx.workchain_scf, AbacusBaseWorkChain))
        except AttributeError:
            self.out_many(self.exposed_outputs(final_relax_workchain, AbacusBaseWorkChain))

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
