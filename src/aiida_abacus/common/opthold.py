"""
Module containing the OptionHolder class
"""

from typing import Optional

from aiida.orm import Dict
from pydantic import BaseModel, Field, ValidationError

from aiida_abacus.common import RelaxType

# pylint:disable=raise-missing-from


class OptionContainer(BaseModel):
    """
    Base class for a container of options
    """

    def aiida_dict(self):
        """Return an ``aiida.orm.Dict`` presentation"""

        python_dict = self.model_dump()
        return Dict(dict=python_dict)

    @classmethod
    def aiida_validate(cls, input_dict, namespace=None) -> None:  # pylint:disable=unused-argument
        """
        Validate a dictionary/Dict node, this can be used as the validator for
        the Port accepting the inputs
        """
        if isinstance(input_dict, Dict):
            input_dict = input_dict.get_dict()
        try:
            cls(**input_dict)
        except ValidationError as error:
            return str(error)
        return None

    @classmethod
    def aiida_serialize(cls, python_dict: dict):
        """
        serialize a dictionary into Dict

        This method can be passed as a `serializer` key word parameter of for the `spec.input` call.
        """
        obj = cls(**python_dict)
        return obj.aiida_dict()

    @classmethod
    def aiida_description(cls):
        """
        Return a string for the options of a OptionContains in a human-readable format.
        """

        obj = cls()
        template = "{:>{width_name}s}:  {:10s} \n{default:>{width_name2}}: {}"
        entries = []
        for name, field in obj.model_fields.items():
            # Each entry is name, type, doc, default value
            entries.append([name, str(field.annotation.__name__), field.description, field.default])
        max_width_name = max(len(entry[0]) for entry in entries) + 2

        lines = []
        for entry in entries:
            lines.append(
                template.format(
                    *entry,
                    width_name=max_width_name,
                    width_name2=max_width_name + 10,
                    default="Default",
                )
            )
        return "\n".join(lines)


class SettingsOptions(OptionContainer):
    """Options for the settings input of a AbacusCalculation"""

    include_bands: bool = Field(
        description="Flag for including the bands in the output",
        default=False,
    )
    include_internal_parameters: bool = Field(
        description="Flag for including the internal parameters in the output",
        default=False,
    )
    include_kpoints: bool = Field(
        description="Flag for including the kpoints in the output",
        default=False,
    )
    excluded_retrieve_list: list = Field(
        description="List of files to be excluded from the retrieved files",
        default=[],
    )
    additional_retrieve_list: list = Field(
        description="List of files to be included in the retrieved files",
        default=[],
    )
    retrieve_charge_density: bool = Field(
        description="Flag for including the charge density in the output",
        default=False,
    )


class RelaxOptions(OptionContainer):
    """Options for AbacusRelaxWorkChain"""

    # Basic relaxation control
    perform: bool = Field(
        description="Whether to perform any relaxation. If False, runs SCF calculation only.",
        default=True,
    )
    relax_type: RelaxType = Field(
        description="Type of relaxation to perform",
        default=RelaxType.POSITIONS_CELL,
    )
    relax_method: str = Field(
        description="Algorithm to use for ionic relaxation",
        examples=["cg", "cg_bfgs", "fire"],
        default="cg",
    )
    max_ionic_steps: int = Field(
        description="Maximum number of ionic relaxation steps (relax_nmax)",
        default=50,
    )
    force_cutoff: float = Field(
        description="Force convergence threshold in eV/Å (force_thr_ev)",
        default=0.03,
    )
    stress_cutoff: float = Field(
        description="Stress convergence threshold in kBar (stress_thr)",
        default=1.0,
    )

    # Convergence control
    convergence_max_iterations: int = Field(
        description="Maximum iterations for meta-convergence checking",
        default=5,
    )


class BandOptions(OptionContainer):
    """Options for AbacusBandWorkChain"""

    symprec: float = Field(description="Precision of the symmetry determination", default=0.01)
    band_mode: str = Field(
        description=(
            "Mode for generating the band path. Choose from: bradcrack, pymatgen,seekpath-aiida and latimer-munro."
        ),
        examples=["bradcrack", "pymatgen", "seekpath", "seekpath-aiida", "latimer-munro"],
        default="seekpath-aiida",
    )
    # TODO: enable explicit seekpath passing
    band_kpoints_distance: float = Field(
        description="Spacing for band distances for automatic kpoints generation, used by seekpath-aiida mode.",
        default=0.025,
    )
    line_density: float = Field(
        description="Density of the point along the path, used by the sumo interface.",
        default=20,
    )
    dos_kpoints_distance: float = Field(
        description=("Kpoints for running DOS calculations in A^-1. Will perform non-SCF DOS calculation is supplied."),
        default=0.20,
    )
    run_bands: bool = Field(
        description="Flag for running Band structure calculations",
        default=True,
    )
    run_dos: bool = Field(
        description="Flag for running DOS calculations",
        default=False,
    )
    additional_band_analysis_parameters: dict = Field(
        description="Additional keyword arguments for the seekpath/ interface, available keys are:"
        "  ['with_time_reversal', 'reference_distance', 'recipe', 'threshold', 'symprec', 'angle_tolerance']",
        default={},
    )


def apply_relax_settings_to_abacus_input(
    input_params: dict, relax_settings: Optional[dict] = None, relax_type: RelaxType = RelaxType.POSITIONS_CELL
) -> dict:
    """
    Apply relaxation settings to ABACUS input parameters.

    This standalone function converts high-level relaxation settings and RelaxType
    into specific ABACUS input parameters.

    :param input_params: Dictionary of ABACUS input parameters (will be modified in place)
    :param relax_settings: Dictionary containing RelaxOptions settings
    :param relax_type: Optional RelaxType enum that determines the relaxation type
    :return: Modified input_params dictionary
    """
    relax_settings = {} if relax_settings is None else relax_settings
    # Get relax_type from settings first, then use parameter fallback
    relax_type_from_settings = relax_settings.get("relax_type")
    if relax_type_from_settings is not None:
        # Convert string to RelaxType if needed
        if isinstance(relax_type_from_settings, str):
            try:
                relax_type = RelaxType(relax_type_from_settings)
            except ValueError:
                raise ValueError(f"Invalid relax_type: {relax_type_from_settings}")
        else:
            relax_type = relax_type_from_settings

    # Apply relax_type-specific settings
    if relax_type is not None:
        if relax_type == RelaxType.NONE:
            input_params["calculation"] = "scf"
        elif relax_type == RelaxType.POSITIONS:
            input_params["calculation"] = "relax"
        else:
            # All other types require cell changes, so use cell-relax
            input_params["calculation"] = "cell-relax"

        # Apply relax_type-specific constraints
        if relax_type == RelaxType.VOLUME:
            input_params["fixed_axes"] = "shape"
            input_params["fixed_atoms"] = True
        elif relax_type == RelaxType.SHAPE:
            input_params["fixed_axes"] = "volume"
            input_params["fixed_atoms"] = True
        elif relax_type == RelaxType.CELL:
            input_params["fixed_atoms"] = True
        elif relax_type == RelaxType.POSITIONS_SHAPE:
            input_params["fixed_axes"] = "volume"
        elif relax_type == RelaxType.POSITIONS_VOLUME:
            input_params["fixed_axes"] = "shape"
        # Note: POSITIONS_CELL and POSITIONS don't need additional constraints

    # Apply relax_settings if provided
    # Check if relaxation should be performed
    if not relax_settings.get("perform", True):
        input_params["calculation"] = "scf"

    # Apply basic relaxation parameters
    if relax_settings.get("max_ionic_steps") is not None:
        input_params["relax_nmax"] = relax_settings["max_ionic_steps"]

    if relax_settings.get("relax_method") is not None:
        input_params["relax_method"] = relax_settings["relax_method"]

    # Apply force convergence threshold
    if relax_settings.get("force_cutoff") is not None:
        input_params["force_thr_ev"] = relax_settings["force_cutoff"]

    # Apply stress convergence threshold
    if relax_settings.get("stress_cutoff") is not None:
        input_params["stress_thr"] = relax_settings["stress_cutoff"]

    # Apply fixed_axes if specified (but only if not already set by relax_type)
    fixed_axes = relax_settings.get("fixed_axes", "None")
    if fixed_axes != "None" and "fixed_axes" not in input_params:
        input_params["fixed_axes"] = fixed_axes

    # Apply fixed_atoms if specified (but only if not already set by relax_type)
    if relax_settings.get("fixed_atoms", False) and "fixed_atoms" not in input_params:
        input_params["fixed_atoms"] = True

    return input_params
