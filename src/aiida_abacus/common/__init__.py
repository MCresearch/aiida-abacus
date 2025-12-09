import enum
import pathlib
from typing import List, Union

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


class ProtocolMixin:
    """Utility class for processes to build input mappings for a given protocol based on a YAML configuration file."""

    _protocol_tag: str = "NULL"
    _load_root: str = "~/.aiida-abacus/protocols"

    @staticmethod
    def _split_protocol_file_name(name):
        """
        Split the protocol name into its components.
        For example, "balance@my_protocol" becomes ("balance", "my_protocol").
        This allow the protocol to be loaded from a user define file, e.g ~/.aiida-abacus/relax/my_protocol.yaml
        """
        parts = name.split("@", maxsplit=1)
        if len(parts) == 1:
            return name, None
        return parts

    @classmethod
    def list_protocol_files(cls, protocol_tag=None) -> list[tuple[str | None, str, pathlib.Path]]:
        """List avaliable protocols"""

        protocol_tag = protocol_tag or "*"
        user_path = pathlib.Path(f"{cls._load_root}/{protocol_tag}").expanduser()
        system_path = pathlib.Path(__file__).parent.parent / "protocols"

        user_files = []
        system_files = []
        for user_file in user_path.glob("*.yaml"):
            alias = user_file.stem
            tag = user_file.parent.stem
            user_files.append((alias, tag, user_file))

        for system_file in system_path.glob(f"{protocol_tag}.yaml"):
            alias = None
            tag = system_file.stem
            system_files.append((alias, tag, system_file))

        return user_files + system_files

    @classmethod
    def get_protocol_filepath(cls, file_alias: str | None = None) -> pathlib.Path:
        """Return the ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        # If user has custom defined protocols, use them as default
        assert cls._protocol_tag != "NULL", "Protocol tag must be set before calling this method."
        # Use the default name
        if file_alias is None:
            file_alias = cls._protocol_tag
            # Load the default protocol
            default_path = pathlib.Path(__file__).parent.parent / f"protocols/{cls._protocol_tag}.yaml"
            if not default_path.exists():
                raise FileNotFoundError(f"Protocol file not found at {default_path}. Please ensure it exists.")
            return default_path
        else:
            file_alias = str(file_alias)
        # Return the path if it points to a file
        if (file_alias.endswith(".yaml") or file_alias.endswith(".yml")) and pathlib.Path(file_alias).is_file():
            return pathlib.Path(file_alias).absolute()
        # Check if the alias refers to a custom defined protocol file
        user_path = pathlib.Path(f"{cls._load_root}/{cls._protocol_tag}/{file_alias}.yaml").expanduser()
        if user_path.is_file():
            return user_path
        raise FileNotFoundError(f"Cannot resolve {file_alias} to a valid protocol file.")

    @classmethod
    def get_default_protocol(cls) -> str:
        """Return the default protocol for a given workflow class.

        :param cls: the workflow class.
        :return: the default protocol.
        """
        return cls._load_protocol_file()["default_protocol"]

    @classmethod
    def get_available_protocols(cls, file_alias=None) -> dict:
        """Return the available protocols for a given workflow class.

        :param cls: the workflow class.
        :return: dictionary of available protocols, where each key is a protocol and value is another dictionary that
            contains at least the key `description` and optionally other keys with supplementary information.
        """
        data = cls._load_protocol_file(file_alias)
        return {protocol: {"description": values["description"]} for protocol, values in data["protocols"].items()}

    @classmethod
    def get_protocol_inputs(
        cls,
        protocol: str | None = None,
        overrides: dict | pathlib.Path | None = None,
    ) -> dict:
        """Return the inputs for the given workflow class and protocol.

        :param cls: the workflow class.
        :param protocol: optional specific protocol, if not specified, the default will be used. An '@' symbol can be
          added to indicate which file to load the protocol from. For example, 'balanced@phonon' will load the protocol
          from '~/.aiida-abacus/cls._protocol_tag/phonon.yaml'
        :param overrides: dictionary of inputs that should override those specified by the protocol. The mapping should
            maintain the exact same nesting structure as the input port namespace of the corresponding workflow class.
        :return: mapping of inputs to be used for the workflow class.
        """
        if protocol is None:
            data = cls._load_protocol_file()
            protocol = data["default_protocol"]
        else:
            protocol_name, file_alias = cls._split_protocol_file_name(protocol)
            data = cls._load_protocol_file(file_alias)
            protocol = protocol_name or data["default_protocol"]

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
        inputs.pop("description", None)

        if isinstance(overrides, pathlib.Path):
            with overrides.open() as file:
                overrides = yaml.safe_load(file)

        if overrides:
            return recursive_merge(inputs, overrides)

        return inputs

    @classmethod
    def _load_protocol_file(cls, file_alias=None) -> dict:
        """Return the contents of the protocol file for workflow class."""
        with cls.get_protocol_filepath(file_alias).open() as file:
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
