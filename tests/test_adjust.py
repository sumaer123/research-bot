from eqr.spine.adjust import factor_from_subject


def test_factor_parsing():
    assert factor_from_subject("Bonus 1:1") == (0.5, "bonus 1:1")
    assert factor_from_subject(" Bonus 3:2")[0] == 0.4
    f, k = factor_from_subject("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share")
    assert abs(f - 0.2) < 1e-9 and k.startswith("split")
    f, k = factor_from_subject("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share")
    assert abs(f - 0.1) < 1e-9
    f, k = factor_from_subject("Consolidation of Shares - From Re 1/- Per Share To Rs 10/- Per Share")
    assert f == 10.0 and k.startswith("consolidation")
    assert factor_from_subject("Interim Dividend - Rs 3 Per Share") is None
    assert factor_from_subject("Rights 1:4 @ Premium Rs 100") is None
