"""
Tests for the parsers
"""

from aiida_abacus.parsers import AbacusRawParser


def test_eigenvalues(data_folder):
    parser = AbacusRawParser(data_folder / "band_Al_pw/running_scf.log")
    eigen, occ, kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 18, 15)
