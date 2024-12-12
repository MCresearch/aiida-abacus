"""Tests for command line interface."""

from aiida.plugins import DataFactory
from aiida_abacus.cli import export, list_
from click.testing import CliRunner


# pylint: disable=attribute-defined-outside-init
class TestDataCli:
    """Test verdi data cli plugin."""

    def setup_method(self):
        """Prepare nodes for cli tests."""
        diff_parameters = DataFactory("abacus")
        self.parameters = diff_parameters({"ignore-case": True})
        self.parameters.store()
        self.runner = CliRunner()

    def test_data_diff_list(self):
        """Test 'verdi data abacus list'

        Tests that it can be reached and that it lists the node we have set up.
        """
        result = self.runner.invoke(list_, catch_exceptions=False)
        assert str(self.parameters.pk) in result.output

    def test_data_diff_export(self):
        """Test 'verdi data abacus export'

        Tests that it can be reached and that it shows the contents of the node
        we have set up.
        """
        result = self.runner.invoke(export, [str(self.parameters.pk)], catch_exceptions=False)
        assert "ignore-case" in result.output
