"""Tests for the install-sg15, install-dojo, and install-apns commands."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from aiida_abacus.commands.pseudos import (
    SOURCE_CONFIGS,
    SourceConfig,
    _extract_rcut_from_orb_name,
    _make_label,
    _reorganize_github_orbitals,
    _select_orbital_by_rcut,
    _set_group_extras,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestMakeLabel:
    """Tests for the _make_label function."""

    def test_basic(self):
        assert _make_label("SG15", "v1.0", "PBE", "dzp") == "SG15-v1.0-PBE-dzp"

    def test_with_relativistic(self):
        assert _make_label("DOJO", "v0.4", "PBE-SR", "dzp") == "DOJO-v0.4-PBE-SR-dzp"

    def test_apns(self):
        assert _make_label("APNS", "v1", "PBE", "efficiency") == "APNS-v1-PBE-efficiency"


class TestExtractRcut:
    """Tests for _extract_rcut_from_orb_name."""

    def test_standard_name(self):
        assert _extract_rcut_from_orb_name("Si_gga_7au_100Ry_2s2p1d.orb") == 7.0

    def test_different_rcut(self):
        assert _extract_rcut_from_orb_name("Ag_gga_10au_100Ry_6s3p3d2f.orb") == 10.0

    def test_no_rcut(self):
        assert _extract_rcut_from_orb_name("Si.orb") == 0.0


class TestSelectOrbitalByRcut:
    """Tests for _select_orbital_by_rcut."""

    def test_exact_match(self, tmp_path):
        files = [
            tmp_path / "Si_gga_7au_100Ry_2s2p1d.orb",
            tmp_path / "Si_gga_8au_100Ry_2s2p1d.orb",
            tmp_path / "Si_gga_9au_100Ry_2s2p1d.orb",
        ]
        for f in files:
            f.touch()

        result = _select_orbital_by_rcut(files, 7.0)
        assert result.name == "Si_gga_7au_100Ry_2s2p1d.orb"

    def test_closest_match(self, tmp_path):
        files = [
            tmp_path / "Si_gga_7au_100Ry_2s2p1d.orb",
            tmp_path / "Si_gga_10au_100Ry_2s2p1d.orb",
        ]
        for f in files:
            f.touch()

        result = _select_orbital_by_rcut(files, 9.0)
        assert result.name == "Si_gga_10au_100Ry_2s2p1d.orb"


class TestSourceConfigs:
    """Tests for the SOURCE_CONFIGS dataclass."""

    def test_sg15_config_exists(self):
        assert "sg15" in SOURCE_CONFIGS
        config = SOURCE_CONFIGS["sg15"]
        assert config.name == "SG15"
        assert config.version == "v1.0"

    def test_dojo_sr_config_exists(self):
        assert "dojo-sr" in SOURCE_CONFIGS
        config = SOURCE_CONFIGS["dojo-sr"]
        assert config.name == "DOJO"

    def test_dojo_fr_config_exists(self):
        assert "dojo-fr" in SOURCE_CONFIGS

    def test_apns_config_exists(self):
        assert "apns" in SOURCE_CONFIGS
        config = SOURCE_CONFIGS["apns"]
        assert config.name == "APNS"
        assert config.md5  # APNS has a known MD5


class TestSetGroupExtras:
    """Tests for _set_group_extras."""

    def test_sets_extras(self, aiida_profile):
        from aiida.orm import QueryBuilder

        from aiida_abacus.group.orb_group import AtomicOrbitalCollection

        config = SOURCE_CONFIGS["sg15"]
        group = AtomicOrbitalCollection(label="test-extras-group")
        group.store()

        _set_group_extras(group, config, "dzp", "https://example.com/test.zip")

        assert group.base.extras.get("source") == "SG15"
        assert group.base.extras.get("version") == "v1.0"
        assert group.base.extras.get("functional") == "PBE"
        assert group.base.extras.get("tag") == "dzp"
        assert group.base.extras.get("download_url") == "https://example.com/test.zip"
        assert group.base.extras.get("commit") == config.commit
        assert group.base.extras.get("install_date") is not None


# ---------------------------------------------------------------------------
# Unit tests for _reorganize_github_orbitals
# ---------------------------------------------------------------------------


class TestReorganizeGithubOrbitals:
    """Tests for the reorganization of per-element dirs to flat structure."""

    @pytest.fixture
    def github_style_dir(self, tmp_path, data_folder):
        """Create a directory mimicking the SG15_v1.0 structure."""
        source = tmp_path / "SG15_v1.0"

        # Pseudopotential dir
        pp_dir = source / "Pseudopotential"
        pp_dir.mkdir(parents=True)
        shutil.copy(data_folder / "pseudos" / "Si.upf", pp_dir / "Si.upf")

        # Orbitals_v2.0 with per-element subdirs
        orb_dir = source / "Orbitals_v2.0"
        si_dzp = orb_dir / "Si_DZP"
        si_dzp.mkdir(parents=True)
        shutil.copy(data_folder / "orbitals" / "Si_gga_7au_100Ry_2s2p1d.orb", si_dzp)

        # Standard rcut JSON
        rcut_json = source / "Orbitals_v2.0_DZP_E100_StandardRcut.json"
        rcut_json.write_text(json.dumps({"Si": 8}))

        return source

    def test_reorganize_creates_flat_dirs(self, tmp_path, github_style_dir):
        target = tmp_path / "reorganized"
        rcut_json = github_style_dir / "Orbitals_v2.0_DZP_E100_StandardRcut.json"

        _reorganize_github_orbitals(github_style_dir, "dzp", rcut_json, target)

        pp_files = list((target / "Pseudopotential").glob("*.upf"))
        orb_files = list((target / "Orbitals").glob("*.orb"))

        assert len(pp_files) == 1
        assert pp_files[0].name == "Si.upf"
        assert len(orb_files) == 1

    def test_reorganize_selects_closest_rcut(self, tmp_path, data_folder):
        """Test that reorganize picks the orbital closest to standard rcut."""
        source = tmp_path / "source"
        pp_dir = source / "Pseudopotential"
        pp_dir.mkdir(parents=True)
        shutil.copy(data_folder / "pseudos" / "Si.upf", pp_dir / "Si.upf")

        orb_dir = source / "Orbitals_v2.0" / "Si_DZP"
        orb_dir.mkdir(parents=True)
        # Create multiple orbital files with different rcuts
        for rcut in [7, 8, 9, 10]:
            src_orb = data_folder / "orbitals" / "Si_gga_7au_100Ry_2s2p1d.orb"
            shutil.copy(src_orb, orb_dir / f"Si_gga_{rcut}au_100Ry_2s2p1d.orb")

        rcut_json = source / "Orbitals_v2.0_DZP_E100_StandardRcut.json"
        rcut_json.write_text(json.dumps({"Si": 9}))
        target = tmp_path / "reorganized"

        _reorganize_github_orbitals(source, "dzp", rcut_json, target)

        orb_files = list((target / "Orbitals").glob("*.orb"))
        assert len(orb_files) == 1
        assert "9au" in orb_files[0].name

    def test_reorganize_no_matching_tag(self, tmp_path, github_style_dir):
        """Test that a non-existent tag raises an error."""
        import click

        target = tmp_path / "reorganized"
        with pytest.raises(click.Abort, match="No orbital directories found"):
            _reorganize_github_orbitals(github_style_dir, "tzdp", None, target)


# ---------------------------------------------------------------------------
# Integration tests using local ABACUS-orbitals data
# ---------------------------------------------------------------------------


class TestInstallSg15FromLocal:
    """Integration tests for install-sg15 using local data."""

    @pytest.fixture
    def abacus_orbitals_zip(self, tmp_path):
        """Create a minimal zip that mimics the ABACUS-orbitals repo structure."""
        local_repo = Path("/home/bonan/appdir/ABACUS-orbitals")
        if not local_repo.exists():
            pytest.skip("Local ABACUS-orbitals repo not available")

        # Create a zip with just the SG15_v1.0 directory
        zip_path = tmp_path / "ABACUS-orbitals-test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            sg15 = local_repo / "SG15_v1.0"
            for f in sg15.rglob("*"):
                if f.is_file() and f.suffix in (".upf", ".UPF", ".orb", ".json"):
                    arcname = f"ABACUS-orbitals-{local_repo.name}/{f.relative_to(local_repo)}"
                    zf.write(f, arcname)
        return zip_path

    def test_dry_run(self, aiida_profile):
        """Test that dry-run works without database changes."""
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_sg15

        runner = CliRunner()
        result = runner.invoke(install_sg15, ["--dry-run"])
        assert result.exit_code == 0
        assert "SG15" in result.output
        assert "dzp" in result.output

    def test_dry_run_with_tag(self, aiida_profile):
        """Test dry-run with a non-default tag."""
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_sg15

        runner = CliRunner()
        result = runner.invoke(install_sg15, ["--dry-run", "--tag", "tzdp"])
        assert result.exit_code == 0
        assert "tzdp" in result.output


class TestInstallDojoDryRun:
    """Tests for install-dojo command."""

    def test_dry_run_sr(self, aiida_profile):
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_dojo

        runner = CliRunner()
        result = runner.invoke(install_dojo, ["--dry-run"])
        assert result.exit_code == 0
        assert "DOJO" in result.output
        assert "SR" in result.output

    def test_dry_run_fr(self, aiida_profile):
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_dojo

        runner = CliRunner()
        result = runner.invoke(install_dojo, ["--dry-run", "--relativistic", "FR"])
        assert result.exit_code == 0
        assert "FR" in result.output

    def test_dry_run_with_lanthanides(self, aiida_profile):
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_dojo

        runner = CliRunner()
        result = runner.invoke(install_dojo, ["--dry-run", "--include-lanthanides"])
        assert result.exit_code == 0


class TestInstallApnsDryRun:
    """Tests for install-apns command."""

    def test_dry_run(self, aiida_profile):
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_apns

        runner = CliRunner()
        result = runner.invoke(install_apns, ["--dry-run"])
        assert result.exit_code == 0
        assert "APNS" in result.output
        assert "efficiency" in result.output

    def test_dry_run_precision(self, aiida_profile):
        from click.testing import CliRunner

        from aiida_abacus.commands.pseudos import install_apns

        runner = CliRunner()
        result = runner.invoke(install_apns, ["--dry-run", "--tag", "precision"])
        assert result.exit_code == 0
        assert "precision" in result.output
