import enum
import pathlib
from typing import List, Optional, Union

import yaml
from aiida import orm
from aiida.common import AttributeDict

DEFAULT_RETRIEVE_FILES = ("INPUT", "kpoints", "device.log", "warning.log", "istate.info", "STRU_ION_D", "STRU_ION*_D")


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


class CONSTANTS(enum.Enum):
    """Constants used in the code."""

    bohr_to_ang = 1.8897259886e-11
    ry_to_ev = 0.530423239
    ev_to_j = 1.602_176_634e-19
    ev_ang3_to_kbar = 1 / ev_to_j / 1e30 * 10
    ry_bohr3_ev_ang3 = ry_to_ev / bohr_to_ang**3
    ry_bohr3_to_kbar = ry_bohr3_ev_ang3 * ev_ang3_to_kbar


def prepare_process_inputs(process, inputs):
    """Prepare the inputs for submission for the given process, according to its spec.

    That is to say that when an input is found in the inputs that corresponds to an input port in the spec of the
    process that expects a `Dict`, yet the value in the inputs is a plain dictionary, the value will be wrapped in by
    the `Dict` class to create a valid input.

    :param process: sub class of `Process` for which to prepare the inputs dictionary
    :param inputs: a dictionary of inputs intended for submission of the process
    :return: a dictionary with all bare dictionaries wrapped in `Dict` if dictated by the process spec
    """
    prepared_inputs = wrap_bare_dict_inputs(process.spec().inputs, inputs)
    return AttributeDict(prepared_inputs)


def wrap_bare_dict_inputs(port_namespace, inputs):
    """Wrap bare dictionaries in `inputs` in a `Dict` node if dictated by the corresponding port in given namespace.

    :param port_namespace: a `PortNamespace`
    :param inputs: a dictionary of inputs intended for submission of the process
    :return: a dictionary with all bare dictionaries wrapped in `Dict` if dictated by the port namespace
    """
    from aiida.engine.processes import PortNamespace

    wrapped = {}

    for key, value in inputs.items():
        if key not in port_namespace:
            wrapped[key] = value
            continue

        port = port_namespace[key]
        valid_types = port.valid_type if isinstance(port.valid_type, (list, tuple)) else (port.valid_type,)

        if isinstance(port, PortNamespace):
            wrapped[key] = wrap_bare_dict_inputs(port, value)
        elif orm.Dict in valid_types and isinstance(value, dict):
            wrapped[key] = orm.Dict(value)
        else:
            wrapped[key] = value

    return wrapped
