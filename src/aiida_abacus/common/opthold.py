"""
Module containing the OptionHolder class
"""

from aiida.orm import Dict
from pydantic import BaseModel, Field, ValidationError

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
