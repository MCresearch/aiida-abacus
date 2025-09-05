"""
Workflow for performing band structure calculation
"""

import numpy as np
from aiida import orm
from aiida.common.extendeddicts import AttributeDict
from aiida.engine import ToContext, WorkChain, calcfunction, if_

from aiida_abacus.common import prepare_process_inputs
from aiida_abacus.common.opthold import BandOptions

from .base import AbacusBaseWorkChain
from .relax import AbacusRelaxWorkChain


class AbacusBandWorkChain(WorkChain):
    """
    Workflow for performing band structure calculation"""

    @classmethod
    def define(cls, spec):
        """Define the inputs"""
        super().define(spec)
        spec.expose_inputs(
            AbacusBaseWorkChain,
            namespace="base",
            exclude=("clean_workdir", "abacus.structure", "abacus.parent_folder"),
            namespace_options={"help": "Inputs for the `AbacusBaseWorkChain` for the SCF calculation."},
        )
        spec.expose_inputs(
            AbacusRelaxWorkChain,
            namespace="relax",
            exclude=("structure",),
            namespace_options={
                "help": "Inputs for the `AbacusRelaxWorkChain` for geometry optimization.",
                "required": False,
                "populate_defaults": False,
            },
        )
        spec.input("structure", valid_type=orm.StructureData, help="The inputs structure.")
        spec.input(
            "kpoints_band",
            help="Explicit kpoints for the bands. Will not generate kpoints if supplied.",
            valid_type=orm.KpointsData,
            required=False,
        )
        spec.input(
            "band_settings",
            help=BandOptions.aiida_description(),
            valid_type=orm.Dict,
            validator=BandOptions.aiida_validate,
            serializer=BandOptions.aiida_serialize,
        )
        spec.outline(
            cls.setup,
            if_(cls.should_do_relax)(
                cls.run_relax,
                cls.verify_relax,
            ),
            if_(cls.should_generate_path)(cls.generate_path),
            if_(cls.should_run_scf)(
                cls.run_scf,
                cls.verify_scf,
            ),
            cls.run_bands_dos,
            cls.verify_bands_dos,
        )
        spec.output("band_structure", valid_type=orm.BandsData, help="Output band structure data.")
        spec.output(
            "primitive_structure",
            valid_type=orm.StructureData,
            help="Primitive structure for which the band structure is calculated for.",
        )
        spec.output("seekpath_parameters", valid_type=orm.Dict, help="Parameters used for the kpath generation.")

    def setup(self):
        """Setup the workchain"""
        self.ctx.scf_inputs = AttributeDict(self.exposed_inputs(AbacusBaseWorkChain, "base"))
        if "relax" in self.inputs:
            self.ctx.relax_inputs = AttributeDict(self.exposed_inputs(AbacusRelaxWorkChain, "relax"))
        else:
            self.ctx.relax_inputs = None
        self.ctx.structure = self.inputs.structure
        self.ctx.kpoints_band = self.inputs.get("kpoints_band")
        self.ctx.band_settings = self.inputs.band_settings
        self.ctx.restart_folder = self.inputs.get("restart_folder")

    def should_do_relax(self):
        """Check if we need to run the relax workflow"""
        return "relax" in self.inputs

    def run_relax(self):
        """Run the relax workflow"""

        self.ctx.relax_inputs.structure = self.ctx.structure
        self.ctx.relax_inputs.metadata.call_link_label = "relax"
        input = prepare_process_inputs(AbacusRelaxWorkChain, self.ctx.relax_inputs)
        running = self.submit(AbacusRelaxWorkChain, **input)
        self.report("launching AbacusRelaxWorkChain<{running,.pk}>")
        return ToContext(relax_workchain=running)

    def verify_relax(self):
        """Verify the relax workflow"""
        if self.ctx.relax_workchain.is_excepted:
            return self.exit_codes.ERROR_RELAX_PROCESS_FAILED
        # Set the current structure to the relaxed structure
        self.ctx.structure = self.ctx.relax_workchain.outputs.structure

    def should_generate_path(self):
        """Check if we need to generate the path"""
        return self.ctx.kpoints_band is None and self.ctx.band_settings["run_bands"]

    def generate_path(self):
        """
        Run seekpath to obtain the primitive structure and bands
        """

        current_structure_backup = self.ctx.structure
        mode = self.inputs.band_settings["band_mode"]

        if mode == "seekpath-aiida":
            inputs = {
                "band_settings": orm.Dict(
                    {
                        "reference_distance": self.inputs.band_settings["band_kpoints_distance"],
                        "symprec": self.inputs.band_settings["symprec"],
                        **self.inputs.band_settings["additional_band_analysis_parameters"],
                    }
                ),
                "metadata": {"call_link_label": "seekpath"},
            }
            func = seekpath_structure_analysis
        else:
            # Using sumo interface
            try:
                from aiida_abacus.common.sumo_kpath import kpath_from_sumo_v2
            except ImportError:
                raise ImportError("Sumo is not installed, please install it to use this feature.")

            inputs = {
                "band_settings": orm.Dict(
                    {
                        "line_density": self.inputs.band_settings["line_density"],
                        "symprec": self.inputs.band_settings["symprec"],
                        "mode": mode,
                        **self.inputs.band_settings["additional_band_analysis_parameters"],
                    }
                ),
                "metadata": {"call_link_label": "sumo_kpath"},
            }
            func = kpath_from_sumo_v2

        # Run the kpath generation and replace the current structure as the primitive structure
        kpath_results = func(self.ctx.structure, **inputs)
        self.ctx.structure = kpath_results["primitive_structure"]

        if not np.allclose(self.ctx.structure.cell, current_structure_backup.cell):
            self.report(
                "The primitive structure is not the same as the input structure - using the former for all calculations"
                " from now."
            )
        self.ctx.kpoints_band = kpath_results["explicit_kpoints"]
        self.out("primitive_structure", self.ctx.structure)
        if "parameters" in kpath_results:
            self.out("seekpath_parameters", kpath_results["parameters"])

    def should_run_scf(self):
        """Check if we need to run the scf workflow"""
        return not self.ctx.restart_folder

    def run_scf(self):
        """Perform the SCF calculation"""
        inputs = self.ctx.scf_inputs
        # Make the structure is the updated structure
        inputs.abacus.structure = self.ctx.structure
        # Configure the pseudopotentials
        paramdict = inputs.abacus.parameters.get_dict()
        # Make sure the calculation saves the charge
        paramdict["input"]["out_chg"] = 1
        if inputs.abacus.parameters.get_dict() != paramdict:
            inputs.abacus.parameters = orm.Dict(paramdict)
        inputs = prepare_process_inputs(AbacusBaseWorkChain, inputs)
        running = self.submit(AbacusBaseWorkChain, **inputs)
        self.report(f"launching AbacusBaseWorkChain<{running.pk}> for SCF")
        return ToContext(scf_workchain=running)

    def verify_scf(self):
        if self.ctx.scf_workchain.is_excepted:
            return self.exit_codes.ERROR_SCF_PROCESS_FAILED
        self.ctx.restart_folder = self.ctx.scf_workchain.outputs.remote_folder

    def run_bands_dos(self):
        """Launch band and/or DOS calculation"""
        inputs = self.ctx.scf_inputs
        inputs.abacus.structure = self.ctx.structure
        inputs.abacus.parameters = inputs.abacus.parameters.get_dict()
        inputs.abacus.parameters["input"]["out_chg"] = 0
        inputs.abacus.parameters["input"]["init_chg"] = "file"
        inputs.abacus.parameters["input"]["calculation"] = "nscf"
        # Configure the restart folder
        inputs.abacus.restart_folder = self.ctx.restart_folder
        running = {}
        if self.ctx.band_settings.get("run_band", True):
            # Set the kpoints to be that of the band path
            inputs.kpoints = self.ctx.kpoints_band
            if "kpoints_distance" in inputs:
                del inputs["kpoints_distance"]
            inputs.abacus.settings = inputs.abacus.settings.get_dict() if "settings" in inputs.abacus else {}
            inputs.abacus.settings["include_bands"] = True
            band_input = prepare_process_inputs(AbacusBaseWorkChain, inputs)
            running["band_workchain"] = self.submit(AbacusBaseWorkChain, **band_input)
        if self.ctx.band_settings.get("run_dos", False):
            if "kpoints" in inputs:
                del inputs["kpoints"]
            # Use spacing to define DOS kpoints
            inputs.kpoints_distance = self.ctx.band_settings["dos_kpoints_distance"]
            dos_input = prepare_process_inputs(AbacusBaseWorkChain, inputs)
            running["dos_workchain"] = self.submit(AbacusBaseWorkChain, **dos_input)

        return ToContext(**running)

    def verify_bands_dos(self):
        """Inspect the bands and dos calculations"""

        exit_code = None

        if "band_workchain" in self.ctx:
            band_workchain = self.ctx.band_workchain
            if not band_workchain.is_finished_ok:
                self.report(f"Bands calculation finished with error, exit_status: {band_workchain}")
                exit_code = self.exit_codes.ERROR_SUB_PROC_BANDS_FAILED
            else:
                # Set the fermi level for the output band structure based on previous SCF calculation
                if band_workchain.outputs.bands.attributes.get("fermi_level") is None:
                    out_bands = add_fermi_level(band_workchain.outputs.bands, self.ctx.scf_workchain.outputs.misc)
                else:
                    out_bands = band_workchain.outputs.bands
                self.out("band_structure", out_bands)

        if "dos_workchain" in self.ctx:
            dos_workchain = self.ctx.dos_workchain
            if not dos_workchain.is_finished_ok:
                self.report(f"DOS calculation finished with error, exit_status: {dos_workchain.exit_status}")
                exit_code = self.exit_codes.ERROR_SUB_PROC_DOS_FAILED

        return exit_code


@calcfunction
def seekpath_structure_analysis(structure, band_settings):
    """Primitivize the structure with SeeKpath and generate the high symmetry k-point path through its Brillouin zone.
    This calcfunction will take a structure and pass it through SeeKpath to get the normalized primitive cell and the
    path of high symmetry k-points through its Brillouin zone. Note that the returned primitive cell may differ from the
    original structure in which case the k-points are only congruent with the primitive cell.
    The keyword arguments can be used to specify various Seekpath parameters, such as:

    - with_time_reversal: True
    - reference_distance: 0.025
    - recipe: 'hpkot'
    - threshold: 1e-07
    - symprec: 1e-05
    - angle_tolerance: -1.0

    Note that exact parameters that are available and their defaults will depend on your Seekpath version.
    """
    from aiida.tools import get_explicit_kpoints_path

    # All keyword arugments should be `Data` node instances of base type and so should have the `.value` attribute
    return get_explicit_kpoints_path(structure, **band_settings.get_dict())


@calcfunction
def add_fermi_level(bands: orm.BandsData, misc: orm.Dict):
    """Add fermi level to the bands"""
    new_bands = bands.clone()
    new_bands.base.attributes.set("fermi_level", misc.get("fermi_level"))
    return new_bands
