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
    PBandsParser,
    PDosParser,
    StruParser,
    WarningLogParser,
)


def test_eigenvalues(data_folder):
    parser = AbacusRawParser(data_folder / "band_Al_pw/running_scf.log")
    eigen, _occ, _kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 18, 15)

    parser = AbacusRawParser(data_folder / "band_Al_pw/running_nscf.log")
    eigen, _occ, _kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 61, 15)
    # The ``band_Al_pw`` fixture only emits the merged ``nks(nspin=2)``
    # ``K-POINTS DIRECT COORDINATES`` block, not a per-spin one; the
    # ``parse_kpoints`` helper therefore refuses to parse it. The
    # dedicated regression tests below cover the per-spin case on real
    # and synthetic logs.


def test_parse_kpoints_nspin():
    """The ``parse_kpoints`` helper must return the per-spin k-point block.

    ABACUS writes the ``K-POINTS DIRECT/CARTESIAN COORDINATES`` block once per
    spin channel and, for ``nspin == 2`` runs, also appends a combined block
    that lists the k-points once for every spin (i.e. ``2 * nkstot_per_spin``
    entries). Earlier revisions of the parser blindly picked the last block
    and therefore returned ``2 * nkstot_per_spin`` coordinates, which broke the
    bands parser with ``Inconsistent number of kpoints reported``.

    The parser now selects the first ``K-POINTS DIRECT`` block (which ABACUS
    always writes first) and validates its size against the per-spin k-point
    count read from the eigenvalue header.
    """
    per_spin_log = "\n".join(
        [
            "NSPIN == 2",
            " 1/3 kpoint (Cartesian) = 0.0 0.0 0.0",
            " 2/3 kpoint (Cartesian) = 0.25 0.0 0.0",
            " 3/3 kpoint (Cartesian) = 0.5 0.0 0.0",
            "",
            "K-POINTS DIRECT COORDINATES",
            " KPOINTS    DIRECT_X    DIRECT_Y    DIRECT_Z  WEIGHT",
            "       1  0.00000000  0.00000000  0.00000000  0.5",
            "       2  0.25000000  0.00000000  0.00000000  0.5",
            "       3  0.50000000  0.00000000  0.00000000  0.5",
            "",
            "K-POINTS CARTESIAN COORDINATES",
            " KPOINTS    X    Y    Z  WEIGHT",
            "       1  0.0  0.0  0.0  0.5",
            "       2  0.25  0.0  0.0  0.5",
            "       3  0.5  0.0  0.0  0.5",
            "",
        ]
    )

    parser = AbacusRawParser(StringIO(per_spin_log))
    kfrac, kcart = parser.parse_kpoints()

    assert kfrac.shape == (3, 4)
    assert kcart is not None and kcart.shape == (3, 4)


def test_parse_kpoints_first_block_size_mismatch_raises():
    """If the first ``K-POINTS DIRECT`` block is not per-spin, fail loudly."""
    log = "\n".join(
        [
            "NSPIN == 2",
            " 1/3 kpoint (Cartesian) = 0.0 0.0 0.0",
            " 2/3 kpoint (Cartesian) = 0.25 0.0 0.0",
            " 3/3 kpoint (Cartesian) = 0.5 0.0 0.0",
            "",
            "K-POINTS DIRECT COORDINATES",
            " KPOINTS    DIRECT_X    DIRECT_Y    DIRECT_Z  WEIGHT",
            "       1  0.00000000  0.00000000  0.00000000  0.5",
            "       2  0.25000000  0.00000000  0.00000000  0.5",
            "       3  0.50000000  0.00000000  0.00000000  0.5",
            "       4  0.00000000  0.00000000  0.00000000  0.5",
            "       5  0.25000000  0.00000000  0.00000000  0.5",
            "       6  0.50000000  0.00000000  0.00000000  0.5",
            "",
        ]
    )

    parser = AbacusRawParser(StringIO(log))
    with pytest.raises(ValueError, match="K-POINTS DIRECT block size does not match"):
        parser.parse_kpoints()


def test_parse_kpoints_nspin2_collinear_real_log(data_folder):
    """Regression test using the on-disk NSPIN=2 collinear ABACUS fixture.

    The log ships with two ``K-POINTS DIRECT COORDINATES`` blocks: the first
    lists 8 k-points for a single spin channel and the second lists the
    combined 16 k-points (i.e. ``nks(nspin=2)``). The parser must return the
    per-spin coordinates so they line up with ``eigenvalues.shape[1]``.
    """
    parser = AbacusRawParser(data_folder / "mag_Si_lcao/nspin2_running_scf.log")
    eigen, _occ, _kpt_cart = parser.parse_eigenvalues()
    assert eigen.shape == (2, 8, 15)

    kfrac, kcart = parser.parse_kpoints()
    assert kfrac.shape == (8, 4)
    assert kfrac.shape[0] == eigen.shape[1]
    np.testing.assert_allclose(kfrac[0], [0.0, 0.0, 0.0, 0.0156])
    np.testing.assert_allclose(kfrac[1], [0.25, 0.25, 0.25, 0.1250])
    # The fixture only carries the merged all-spin ``K-POINTS CARTESIAN``
    # block; the helper therefore returns it verbatim.
    assert kcart is not None
    assert kcart.shape[0] == 16


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


def test_parse_total_time_returns_none_when_no_total_time_line():
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

    parser.parse_total_time()

    assert parser.results["total_time"] is None
    assert parser.results["total_time_unit"] is None


def test_parse_total_time_converts_to_seconds():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " Start  Time  : Sat Mar 22 15:22:30 2025",
                    " Finish Time  : Sat Mar 22 15:22:32 2025",
                    " Total  Time  : 0 h 0 mins 2 secs ",
                ]
            )
        )
    )

    parser.parse_total_time()

    assert parser.results["total_time"] == 2.0
    assert parser.results["total_time_unit"] == "s"


def test_pdos_parser(data_folder):
    result = PDosParser(data_folder / "pband_synth" / "pdos.xml").parse()
    assert result["nspin"] == 1
    assert result["norbitals"] == 2
    assert result["energy"].shape == (5,)
    assert len(result["orbitals"]) == 2
    for orbital in result["orbitals"]:
        assert orbital["pdos"].shape == (5, 1)
        assert orbital["attrs"]["species"] == "Si"


def test_pdos_parser_on_real_si_lcao_fixture(data_folder):
    """Regression test against the real PDOS produced by a Si LCAO run.

    The fixture has 36848 energy grid points, 1 band (nspin=1), and 13
    orbitals.
    """
    result = PDosParser(data_folder / "pband_Si_lcao" / "PDOS").parse()
    assert result["nspin"] == 1
    assert result["norbitals"] == 13
    assert result["energy"].shape == (36848,)
    assert len(result["orbitals"]) == 13
    for orbital in result["orbitals"]:
        assert orbital["pdos"].shape == (36848, 1)
        assert orbital["attrs"]["species"] == "Si"
    # The first orbital should be atom 1, l=0, m=0 (s-orbital on Si).
    assert result["orbitals"][0]["attrs"] == {
        "index": "1",
        "atom_index": "1",
        "species": "Si",
        "l": "0",
        "m": "0",
        "z": "1",
    }
    # The last orbital should be index 13.
    assert result["orbitals"][-1]["attrs"]["index"] == "13"


def test_pdos_parser_rejects_wrong_root_tag():
    parser = PDosParser(StringIO("<pband><nspin>1</nspin></pband>"))
    with pytest.raises(ValueError, match="Expected <pdos> root tag"):
        parser.parse()


def test_parse_total_time_handles_hours_and_minutes():
    parser = AbacusRawParser(StringIO("Total  Time  : 1 h 2 mins 3 secs \n"))

    parser.parse_total_time()

    # 1*3600 + 2*60 + 3 = 3723
    assert parser.results["total_time"] == 3723.0
    assert parser.results["total_time_unit"] == "s"


def test_parse_total_time_picks_first_match_in_tail_window():
    parser = AbacusRawParser(
        StringIO(
            "\n".join(
                [
                    " ...intermediate log lines...",
                    " Total  Time  : 0 h 0 mins 1 secs ",
                    " Total  Time  : 0 h 0 mins 27 secs ",
                ]
            )
        )
    )

    parser.parse_total_time()

    # The parser only scans the last 100 lines and returns the first match
    # it finds there; the second occurrence is irrelevant.
    assert parser.results["total_time"] == 1.0


def test_parse_total_time_on_pw_si2_log(data_folder):
    """The pw_Si2 fixture (lines 683-685) reports `0 h 0 mins 2 secs` -> 2 s."""
    parser = AbacusRawParser(data_folder / "pw_Si2/OUT.aiida/running_scf.log")
    parser.parse_total_time()

    assert parser.results["total_time"] == 2.0
    assert parser.results["total_time_unit"] == "s"


def test_pbands_parser(data_folder):
    result = PBandsParser(data_folder / "pband_synth" / "pband.xml").parse()
    assert result["nspin"] == 1
    assert result["norbitals"] == 2
    assert result["band_structure"].shape == (4, 3)
    assert len(result["orbitals"]) == 2
    for orbital in result["orbitals"]:
        assert orbital["weights"].shape == (4, 3)
        assert orbital["attrs"]["species"] == "Si"
    assert result["orbitals"][0]["attrs"]["index"] == "1"
    assert result["orbitals"][1]["attrs"]["index"] == "2"


def test_pdos_parser(data_folder):
    result = PDosParser(data_folder / "pband_synth" / "pdos.xml").parse()
    assert result["nspin"] == 1
    assert result["norbitals"] == 2
    assert result["energy"].shape == (5,)
    assert len(result["orbitals"]) == 2
    for orbital in result["orbitals"]:
        assert orbital["pdos"].shape == (5, 1)
        assert orbital["attrs"]["species"] == "Si"


def test_pbands_parser_on_real_si_lcao_fixture(data_folder):
    """Regression test against the real PBANDS_1 produced by a Si LCAO run.

    The fixture has 358 k-points, 12 bands, and 13 orbitals (one per
    ``(atom, l, m, z)`` combination). The parser must handle the ABACUS
    multi-line opening-tag format (``<orbital\n attr=... >``) and produce
    arrays with the expected shapes.
    """
    result = PBandsParser(data_folder / "pband_Si_lcao" / "PBANDS_1").parse()
    assert result["nspin"] == 1
    assert result["norbitals"] == 13
    assert result["band_structure"].shape == (358, 12)
    assert len(result["orbitals"]) == 13
    for orbital in result["orbitals"]:
        assert orbital["weights"].shape == (358, 12)
        assert orbital["attrs"]["species"] == "Si"
    # Spot-check a few representative k-points / bands.
    assert result["band_structure"][0, 0] == pytest.approx(-3.68842)
    assert result["band_structure"][-1, -1] == pytest.approx(60.4052)
    # The first orbital corresponds to atom 1, l=0, m=0 (s-orbital on Si).
    assert result["orbitals"][0]["attrs"] == {
        "index": "1",
        "atom_index": "1",
        "species": "Si",
        "l": "0",
        "m": "0",
        "z": "1",
    }
    # The last orbital should be index 13.
    assert result["orbitals"][-1]["attrs"]["index"] == "13"


def test_pdos_parser_on_real_si_lcao_fixture(data_folder):
    """Regression test against the real PDOS produced by a Si LCAO run.

    The fixture has 36848 energy grid points, 1 band (nspin=1), and 13
    orbitals.
    """
    result = PDosParser(data_folder / "pband_Si_lcao" / "PDOS").parse()
    assert result["nspin"] == 1
    assert result["norbitals"] == 13
    assert result["energy"].shape == (36848,)
    assert len(result["orbitals"]) == 13
    for orbital in result["orbitals"]:
        assert orbital["pdos"].shape == (36848, 1)
        assert orbital["attrs"]["species"] == "Si"
    # The first orbital should be atom 1, l=0, m=0 (s-orbital on Si).
    assert result["orbitals"][0]["attrs"] == {
        "index": "1",
        "atom_index": "1",
        "species": "Si",
        "l": "0",
        "m": "0",
        "z": "1",
    }
    # The last orbital should be index 13.
    assert result["orbitals"][-1]["attrs"]["index"] == "13"


def test_pbands_parser_rejects_wrong_root_tag():
    parser = PBandsParser(StringIO("<pdos><nspin>1</nspin></pdos>"))
    with pytest.raises(ValueError, match="Expected <pband> root tag"):
        parser.parse()


def test_pdos_parser_rejects_wrong_root_tag():
    parser = PDosParser(StringIO("<pband><nspin>1</nspin></pband>"))
    with pytest.raises(ValueError, match="Expected <pdos> root tag"):
        parser.parse()
