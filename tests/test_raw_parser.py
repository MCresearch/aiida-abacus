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


def test_parse_magnetism_returns_none_when_no_magnetism_lines():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " some unrelated log line",
                    " E_KohnSham     -1989.2618545111     -27065.2960353985",
                ]
            )
        )
    )

    parser.parse_magnetism()

    assert parser.results["magnetism"] is None
    assert parser.results["final_magnetism"] is None


def test_parse_magnetism_collects_per_step_values():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " LCAO ALGORITHM --------------- ION=   1  ELEC=  21--------------------------------",
                    "          total magnetism (Bohr mag/cell) = 0.933056",
                    "       absolute magnetism (Bohr mag/cell) = 0.933056",
                    " LCAO ALGORITHM --------------- ION=   1  ELEC=  22--------------------------------",
                    "          total magnetism (Bohr mag/cell) = -3.13515e-06",
                    "       absolute magnetism (Bohr mag/cell) = 8.57839e-06",
                ]
            )
        )
    )

    parser.parse_magnetism()

    assert parser.results["magnetism"] == {
        "total_magnetism": [0.933056, -3.13515e-06],
        "absolute_magnetism": [0.933056, 8.57839e-06],
    }
    assert parser.results["final_magnetism"] == {
        "total_magnetism": -3.13515e-06,
        "absolute_magnetism": 8.57839e-06,
    }


def test_parse_magnetism_on_mag_si_lcao_log(data_folder):
    parser = AbacusRawParser(data_folder / "mag_Si_lcao/nspin2_running_scf.log")
    parser.parse_magnetism()

    magnetism = parser.results["magnetism"]
    final_magnetism = parser.results["final_magnetism"]

    # The fixture has 13 electronic steps reporting magnetism.
    assert magnetism is not None
    assert set(magnetism) == {"total_magnetism", "absolute_magnetism"}
    assert len(magnetism["total_magnetism"]) == 13
    assert len(magnetism["absolute_magnetism"]) == 13
    for value in magnetism["total_magnetism"]:
        assert isinstance(value, float)
    for value in magnetism["absolute_magnetism"]:
        assert isinstance(value, float)

    # Final step of the nspin=2 fixture.
    assert final_magnetism == {
        "total_magnetism": 5.08369e-17,
        "absolute_magnetism": 3.36813e-09,
    }
    # First electronic step is a clearly non-zero magnetic moment.
    assert magnetism["total_magnetism"][0] == pytest.approx(-9.60176e-11)
    assert magnetism["absolute_magnetism"][0] == pytest.approx(0.361711)


def test_parse_magnetism_on_nspin2_collinear_log(data_folder):
    """The nspin=2 fixture uses the `... = <scalar>` form for total magnetism."""
    parser = AbacusRawParser(data_folder / "mag_Si_lcao/nspin2_running_scf.log")
    parser.parse_magnetism()

    magnetism = parser.results["magnetism"]
    assert magnetism is not None
    assert len(magnetism["total_magnetism"]) == 13
    assert len(magnetism["absolute_magnetism"]) == 13
    for value in magnetism["total_magnetism"]:
        assert isinstance(value, float)
    for value in magnetism["absolute_magnetism"]:
        assert isinstance(value, float)

    final = parser.results["final_magnetism"]
    assert isinstance(final["total_magnetism"], float)
    assert isinstance(final["absolute_magnetism"], float)


def test_parse_magnetism_on_nspin4_noncollinear_log(data_folder):
    """The nspin=4 fixture emits total magnetism as three tab-separated components."""
    parser = AbacusRawParser(data_folder / "mag_Si_lcao/nspin4_running_scf.log")
    parser.parse_magnetism()

    magnetism = parser.results["magnetism"]
    final_magnetism = parser.results["final_magnetism"]

    assert magnetism is not None
    # nspin=4 fixture has 14 electronic steps.
    assert len(magnetism["total_magnetism"]) == 14
    assert len(magnetism["absolute_magnetism"]) == 14
    for component in magnetism["total_magnetism"]:
        # Each total-magnetism entry is a 3-vector [mx, my, mz].
        assert isinstance(component, list)
        assert len(component) == 3
        for value in component:
            assert isinstance(value, float)
    for value in magnetism["absolute_magnetism"]:
        # absolute_magnetism stays a scalar.
        assert isinstance(value, float)

    # The last entry is on lines 706-707 of the fixture.
    assert final_magnetism["total_magnetism"] == [
        pytest.approx(-1.51861e-16),
        pytest.approx(-2.1343e-16),
        pytest.approx(-2.54856e-09),
    ]
    assert final_magnetism["absolute_magnetism"] == pytest.approx(2.98079e-08)
    # First nspin=4 step has a clearly non-zero mz component.
    assert magnetism["total_magnetism"][0][2] == pytest.approx(0.212635)
    assert magnetism["absolute_magnetism"][0] == pytest.approx(0.212659)
