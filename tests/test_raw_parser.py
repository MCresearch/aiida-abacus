"""
Tests for the parsers
"""

import numpy as np
import pytest
from aiida_abacus.parsers.raw_parsers import AbacusRawParser, BandsParser, InternalParametersParser, KpointsParser


def test_eigenvalues(data_folder):
    parser = AbacusRawParser(data_folder / "band_Al_pw/running_scf.log")
    eigen, occ, kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 18, 15)

    parser = AbacusRawParser(data_folder / "band_Al_pw/running_nscf.log")
    eigen, occ, kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 61, 15)

    kpt_frac, kpt_cart = parser.parse_kpoints()
    assert kpt_frac.shape == (122, 4)
    assert kpt_cart.shape == (122, 4)
    weights = kpt_frac[:, 3]
    np.testing.assert_allclose(kpt_frac[0], [0.0, 0.0, 0.0, 0.0082])
    np.testing.assert_allclose(kpt_frac[1], [0.025, -0.025, 0.025, 0.0082])
    assert weights.shape == (122,)
    assert sum(weights) == pytest.approx(1.0, abs=1e-3)  # Too few number of decimals TODO: raise issue


def test_kpoints_parser(data_folder):
    parser = KpointsParser(data_folder / "pw_Si2/OUT.aiida/kpoints")
    points, weights = parser.parse()
    assert len(points) == 8
    assert len(weights) == 8
    assert abs(sum(weights) - 1.0) <= 1e-4
    assert weights[0] == 0.0156
    assert points[0] == [0, 0, 0]


def test_internal_parameters_parser(data_folder):
    parser = InternalParametersParser(data_folder / "pw_Si2/OUT.aiida/INPUT")
    params = parser.parse()
    assert params["nspin"] == "1"
    assert params["lj_rcut"] == "None"
    assert params["kspacing"] == "0 0 0"


def test_bands_parser(data_folder):
    parser = BandsParser(data_folder / "band_Al_pw/BANDS_1.dat")
    kdist, eigenvalues = parser.parse()
    assert len(kdist) == 122
    assert eigenvalues.shape == (122, 15)
