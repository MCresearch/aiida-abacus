from typing import List, Union

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
