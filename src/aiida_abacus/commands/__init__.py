"""
AiiDA-abacus command line interface.

This module provides the main entry point for the aiida-abacus CLI commands.
"""

import click
from aiida.cmdline.groups import VerdiCommandGroup
from aiida.cmdline.params.options import PROFILE
from aiida.cmdline.params.types.profile import ProfileParamType


@click.group(
    "aiida-abacus",
    cls=VerdiCommandGroup,
    help="AiiDA ABACUS command line tools",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@PROFILE(type=ProfileParamType(load_profile=True), expose_value=False)
def cmd_aiida_abacus() -> None:
    """AiiDA ABACUS command line tools."""
    pass


# Import subcommands
from . import pseudos  # noqa: E402

_ = pseudos
