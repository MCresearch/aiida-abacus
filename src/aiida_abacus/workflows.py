"""
Workflows
"""

from aiida import orm
from aiida.common.extendeddicts import AttributeDict
from aiida.engine import while_
from aiida.engine.processes.workchains.restart import BaseRestartWorkChain

from aiida_abacus.calculations import AbacusCalculation


class AbacusWorkChain(BaseRestartWorkChain):
    """
    Base restart workflow for abacus.
    """

    _process_class = AbacusCalculation

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
            202,
            "ERROR_INVALID_INPUT_KPOINTS",
            message="Neither the `kpoints` nor the `kpoints_distance` input was specified.",
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


def create_kpoints_from_distance(structure, distance, force_parity):
    """Generate a uniformly spaced kpoint mesh for a given structure.
    Based on aiida-quantumespresso's function `create_kpoints_from_distance`

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
