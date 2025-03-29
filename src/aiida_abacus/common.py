import enum
import pathlib
from typing import List, Optional, Union

import yaml
from aiida import orm

DEFAULT_RETRIEVE_FILES = ("INPUT", "kpoints", "STRU.cif", "device.log", "warning.log", "istate.info")


def make_retrieve_list(
    parameters: Union[dict, orm.Dict],
    settings: Union[dict, orm.Dict],
    folder_suffix="AIIDA",
    full_specification=False,
) -> List[str]:
    """
    Generate the list of file to be retrieved depending out the calculation type
    and folder suffix this because the exact file names depends on the calculation
    type and suffix defined by the user
    """
    calc_type = parameters["input"].get("calculation", "scf")  # Abacus default to SCF file
    excluded = settings.get("excluded_retrieve_list", [])
    additional = settings.get("additional_retrieve_list", [])
    add_density = settings.get("retrieve_charge_density", False)

    files = []
    for name in DEFAULT_RETRIEVE_FILES:
        if name in excluded:
            continue
        files.append(f"OUT.{folder_suffix}/{name}")

    for name in additional:
        if name in excluded:
            continue
        files.append(f"OUT.{folder_suffix}/{name}")

    files.append(f"OUT.{folder_suffix}/running_{calc_type}.log")
    if add_density:
        files.append(f"OUT.{folder_suffix}/{folder_suffix}-CHARGE-DENSITY.restart")

    if full_specification:
        output = []
        for filename in files:
            if "/" in filename:
                output.append([filename, ".", 2])
            else:
                output.append([filename, ".", 0])
    else:
        output = files
    return output


## For predefine protocols
## The class and function below is based on aiida-quantumespresso
class ProtocolMixin:
    """Utility class for processes to build input mappings for a given protocol based on a YAML configuration file."""

    @classmethod
    def get_protocol_filepath(cls) -> pathlib.Path:
        """Return the ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        raise NotImplementedError

    @classmethod
    def get_default_protocol(cls) -> str:
        """Return the default protocol for a given workflow class.

        :param cls: the workflow class.
        :return: the default protocol.
        """
        return cls._load_protocol_file()["default_protocol"]

    @classmethod
    def get_available_protocols(cls) -> dict:
        """Return the available protocols for a given workflow class.

        :param cls: the workflow class.
        :return: dictionary of available protocols, where each key is a protocol and value is another dictionary that
            contains at least the key `description` and optionally other keys with supplementary information.
        """
        data = cls._load_protocol_file()
        return {protocol: {"description": values["description"]} for protocol, values in data["protocols"].items()}

    @classmethod
    def get_protocol_inputs(
        cls,
        protocol: Optional[dict] = None,
        overrides: Union[dict, pathlib.Path, None] = None,
    ) -> dict:
        """Return the inputs for the given workflow class and protocol.

        :param cls: the workflow class.
        :param protocol: optional specific protocol, if not specified, the default will be used
        :param overrides: dictionary of inputs that should override those specified by the protocol. The mapping should
            maintain the exact same nesting structure as the input port namespace of the corresponding workflow class.
        :return: mapping of inputs to be used for the workflow class.
        """
        data = cls._load_protocol_file()
        protocol = protocol or data["default_protocol"]

        try:
            protocol_inputs = data["protocols"][protocol]
        except KeyError as exception:
            alias_protocol = cls._check_if_alias(protocol)
            if alias_protocol is not None:
                protocol_inputs = data["protocols"][alias_protocol]
            else:
                raise ValueError(
                    f"`{protocol}` is not a valid protocol. Call ``get_available_protocols`` to show available "
                    "protocols."
                ) from exception
        inputs = recursive_merge(data["default_inputs"], protocol_inputs)
        inputs.pop("description")

        if isinstance(overrides, pathlib.Path):
            with overrides.open() as file:
                overrides = yaml.safe_load(file)

        if overrides:
            return recursive_merge(inputs, overrides)

        return inputs

    @classmethod
    def _load_protocol_file(cls) -> dict:
        """Return the contents of the protocol file for workflow class."""
        with cls.get_protocol_filepath().open() as file:
            return yaml.safe_load(file)

    @staticmethod
    def _check_if_alias(alias: str):
        """Check if a given alias corresponds to a valid protocol."""
        aliases_dict = {
            "moderate": "balanced",
            "precise": "stringent",
        }
        return aliases_dict.get(alias, None)


def recursive_merge(left: dict, right: dict) -> dict:
    """Recursively merge two dictionaries into a single dictionary.

    If any key is present in both ``left`` and ``right`` dictionaries, the value from the ``right`` dictionary is
    assigned to the key.

    :param left: first dictionary
    :param right: second dictionary
    :return: the recursively merged dictionary
    """
    import collections

    # Note that a deepcopy is not necessary, since this function is called recusively.
    right = right.copy()

    for key, value in left.items():
        if key in right:
            if isinstance(value, collections.abc.Mapping) and isinstance(right[key], collections.abc.Mapping):
                right[key] = recursive_merge(value, right[key])

    merged = left.copy()
    merged.update(right)

    return merged


class ElectronicType(enum.Enum):
    """Enumeration to indicate the electronic type of a system."""

    METAL = "metal"
    INSULATOR = "insulator"
    AUTOMATIC = "automatic"


class RelaxType(enum.Enum):
    """Enumeration of known relax types."""

    NONE = "none"  # All degrees of freedom are fixed, essentially performs single point SCF calculation
    POSITIONS = "positions"  # Only the atomic positions are relaxed, cell is fixed
    VOLUME = "volume"  # Only the cell volume is optimized, cell shape and atoms are fixed
    SHAPE = "shape"  # Only the cell shape is optimized at a fixed volume and fixed atomic positions
    CELL = "cell"  # Only the cell is optimized, both shape and volume, while atomic positions are fixed
    POSITIONS_VOLUME = "positions_volume"  # Same as `VOLUME` but atomic positions are relaxed as well
    POSITIONS_SHAPE = "positions_shape"  # Same as `SHAPE`  but atomic positions are relaxed as well
    POSITIONS_CELL = "positions_cell"  # Same as `CELL`  but atomic positions are relaxed as well


class SpinType(enum.Enum):
    """Enumeration to indicate the spin polarization type of a system."""

    NONE = "none"
    COLLINEAR = "collinear"
    NON_COLLINEAR = "non_collinear"
    SPIN_ORBIT = "spin_orbit"
