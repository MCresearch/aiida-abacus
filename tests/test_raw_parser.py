"""
Tests for the parsers
"""

from io import StringIO

import numpy as np
import pytest

from aiida_abacus.parsers.raw_parsers import (
    AbacusRawParser,
    BandsParser,
    InternalParametersParser,
    KpointsParser,
    StruParser,
    WarningLogParser,
)


def test_eigenvalues(data_folder):
    parser = AbacusRawParser(data_folder / "band_Al_pw/running_scf.log")
    eigen, _occ, kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 18, 15)

    parser = AbacusRawParser(data_folder / "band_Al_pw/running_nscf.log")
    eigen, _occ, kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 61, 15)

    kpt_frac, kpt_cart = parser.parse_kpoints()
    assert kpt_frac.shape == (122, 4)
    assert kpt_cart.shape == (122, 4)
    weights = kpt_frac[:, 3]
    np.testing.assert_allclose(kpt_frac[0], [0.0, 0.0, 0.0, 0.0082])
    np.testing.assert_allclose(kpt_frac[1], [0.025, -0.025, 0.025, 0.0082])
    assert weights.shape == (122,)
    assert sum(weights) == pytest.approx(1.0, abs=1e-3)  # Allow tolerance for floating point precision


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


def test_stru_parser(data_folder):
    parser = StruParser(data_folder / "pw_Si2/STRU")
    cell, positions, species = parser.parse()
    assert species == ["Si", "Si"]
    a = 10.2 * 0.5 / 1.8897261255
    np.testing.assert_allclose(cell, np.array([[a, a, 0], [a, 0, a], [0, a, a]]))
    np.testing.assert_allclose(positions, np.array([[0, 0, 0], [0.5 * a, 0.5 * a, 0.5 * a]]))
    parser = StruParser(data_folder / "STRU_ION_D")
    cell, positions, species = parser.parse()
    assert species == ["Cd", "Cd", "Cd", "Cd", "Sn", "Sn", "Sn", "Sn"]
    a = 10.2 * 0.5 / 1.8897261255
    np.testing.assert_allclose(
        cell,
        np.array(
            [
                [6.6539429744, 0.0000000000, 0.0000000000],
                [0.0000000000, 6.6539429744, 0.0000000000],
                [0.0000000000, 0.0000000000, 13.1571816610],
            ]
        ),
    )
    np.testing.assert_allclose(positions[0], [0.0, 0.0, 13.1571816610])


def test_parse_notifications():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " #SCF IS CONVERGED#",
                    " !!SCF IS NOT CONVERGED!!",
                    " Relaxation is not converged",
                    " Relaxation is converged!",
                    " Relaxation is converged, but the SCF is unconverged",
                ]
            )
        )
    )

    notifications = parser.parse_notifications()

    assert [entry["name"] for entry in notifications] == [
        "scf_converged",
        "scf_not_converged",
        "ionic_not_converged",
        "ionic_converged",
        "relax_scf_not_converged",
    ]


def test_parse_notifications_preserves_repeated_order():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " !!SCF IS NOT CONVERGED!!",
                    " #SCF IS CONVERGED#",
                    " !!SCF IS NOT CONVERGED!!",
                ]
            )
        )
    )

    notifications = parser.parse_notifications()

    assert [entry["name"] for entry in notifications] == [
        "scf_not_converged",
        "scf_converged",
        "scf_not_converged",
    ]


def test_parse_notifications_supports_lts_scf_markers():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " charge density convergence is achieved",
                    " !! convergence has not been achieved @_@",
                ]
            )
        )
    )

    notifications = parser.parse_notifications()

    assert [entry["name"] for entry in notifications] == [
        "scf_converged",
        "scf_not_converged",
    ]


def test_warning_log_parser():
    parser = WarningLogParser(
        StringIO(
            "\n".join(
                [
                    " scf  warning : Threshold on eigenvalues was too large.",
                    " ignored line",
                    " driver warning : Calculation will restart",
                ]
            )
        )
    )

    notifications = parser.parse()

    assert notifications == [
        {"source": "scf", "message": "Threshold on eigenvalues was too large."},
        {"source": "driver", "message": "Calculation will restart"},
    ]


def test_parse_runtime_warnings():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " random line",
                    " Notice: Threshold on eigenvalues was too large.",
                    " Warning: Falling back to a slower path",
                    " Notice: Threshold on eigenvalues was too large.",
                ]
            )
        )
    )

    notifications = parser.parse_runtime_warnings()

    assert notifications == [
        {"source": "running_log", "message": "Threshold on eigenvalues was too large."},
        {"source": "running_log", "message": "Falling back to a slower path"},
    ]
