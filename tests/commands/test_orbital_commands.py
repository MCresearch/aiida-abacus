"""Tests for orbital-related CLI commands."""

from click.testing import CliRunner


class TestOrbitalCommands:
    """Test the orbital-related CLI commands."""

    def test_list_families_command(self, aiida_profile_clean, si_orbital_family):
        """Test pseudos list-families command output."""
        from aiida_abacus.commands.pseudos import list_families

        runner = CliRunner()
        result = runner.invoke(list_families, [])

        # Command should execute successfully
        assert result.exit_code == 0

        # Should contain the family we created
        assert si_orbital_family.label in result.output

    def test_show_family_command(self, aiida_profile_clean, si_orbital_family):
        """Test pseudos show-family command functionality."""
        from aiida_abacus.commands.pseudos import show_family

        runner = CliRunner()
        result = runner.invoke(show_family, [si_orbital_family.label])

        # Command should execute successfully
        assert result.exit_code == 0

        # Should contain family information
        assert si_orbital_family.label in result.output

    def test_show_family_nonexistent(self, aiida_profile_clean):
        """Test show-family command with non-existent family."""
        from aiida_abacus.commands.pseudos import show_family

        runner = CliRunner()
        result = runner.invoke(show_family, ["nonexistent-family"])

        # Should fail with non-existent family
        assert result.exit_code != 0

    def test_list_sets_command(self):
        """Test pseudos list-sets command."""
        from aiida_abacus.commands.pseudos import list_sets

        runner = CliRunner()
        result = runner.invoke(list_sets, [])

        # Command should execute successfully (may show empty list)
        assert result.exit_code == 0

    def test_list_families_empty_filter(self, aiida_profile_clean):
        """Test list-families with empty result."""
        from aiida_abacus.commands.pseudos import list_families

        runner = CliRunner()
        result = runner.invoke(list_families, [])

        # Command should execute successfully even with no families
        assert result.exit_code == 0
