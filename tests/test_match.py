import ast
from pathlib import Path

from ingest.load import load
from match.ladder import TOLERANCE_PAISE, Match, run

ROOT = Path(__file__).resolve().parents[1]

HEADERS = {
    "orders.csv": "order_id,created_at,customer_ref,customer_name,pincode,gross_amount_paise,status",
    "payments.csv": "payment_id,order_id,captured_at,amount_paise,method,fee_paise,gst_paise,settlement_id,status",
    "refunds.csv": "refund_id,payment_id,created_at,amount_paise,type,settlement_id,status",
    "settlements.csv": "settlement_id,settled_at,utr,net_amount_paise,fee_paise,gst_paise,refund_paise,adjustment_paise",
    "bank_statement.csv": "txn_date,narration,credit_paise,debit_paise,closing_balance_paise,bank_ref",
}


def ledger_of(tmp_path, settlements, bank, payments=()):
    """Build the smallest five-file set that exercises a matching case."""
    rows = {name: [header] for name, header in HEADERS.items()}
    for sid, settled_at, utr, net in settlements:
        rows["settlements.csv"].append(f"{sid},{settled_at},{utr},{net},0,0,0,0")
    for pid, sid in payments:
        rows["payments.csv"].append(f"{pid},order_1,2026-01-01,1000,upi,0,0,{sid},captured")
    for txn_date, narration, credit, ref in bank:
        rows["bank_statement.csv"].append(f"{txn_date},{narration},{credit},0,{credit},{ref}")
    for name, lines in rows.items():
        tmp_path.joinpath(name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load(tmp_path)


NEFT = "NEFT-RAZORPAY SOFTWARE PRIVA-{utr}-HDFC-XXXXX"


def test_r0_matches_on_verbatim_utr_and_exact_amount(tmp_path):
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("05/01/2026", NEFT.format(utr="207592797549"), 81834, "HDFC1")],
        payments=[("pay_1", "setl_1"), ("pay_2", "setl_1")],
    )
    result = run(ledger)
    assert result.matches == [Match("HDFC1", ("setl_1",), ("pay_1", "pay_2"), "R0", 0)]
    assert result.unmatched_credits == [] and result.unmatched_settlements == []
    assert result.drift_paise == 0


def test_r0_flags_a_match_that_consumes_tolerance(tmp_path):
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("05/01/2026", NEFT.format(utr="207592797549"), 81797, "HDFC1")],
    )
    result = run(ledger)
    assert [m.rung for m in result.matches] == ["R0"]
    assert result.matches[0].delta_paise == -37
    assert result.flagged == result.matches
    assert result.drift_paise == 37
    assert "inside tolerance" in " ".join(result.trail["HDFC1"])


def test_amount_outside_tolerance_is_not_a_match(tmp_path):
    """One paisa past the window is a break, not a rounding difference."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("05/01/2026", NEFT.format(utr="207592797549"),
               81834 - TOLERANCE_PAISE - 1, "HDFC1")],
    )
    result = run(ledger)
    assert result.matches == []
    assert result.unmatched_credits == ["HDFC1"]
    assert result.unmatched_settlements == ["setl_1"]
    assert "outside tolerance" in " ".join(result.trail["HDFC1"])


def test_r1_matches_a_truncated_utr_on_amount_and_date(tmp_path):
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("06/01/2026", NEFT.format(utr="2075927"), 81834, "HDFC1")],
        payments=[("pay_1", "setl_1")],
    )
    result = run(ledger)
    assert [(m.rung, m.settlement_ids) for m in result.matches] == [("R1", ("setl_1",))]
    assert "partial reference" in " ".join(result.trail["HDFC1"])


def test_r1_matches_a_garbled_utr(tmp_path):
    """One character replaced by a lookalike -- 8 for B, O for 0 -- still resolves."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("05/01/2026", NEFT.format(utr="2075927975S9"), 81834, "HDFC1")],
    )
    result = run(ledger)
    assert [m.rung for m in result.matches] == ["R1"]


def test_two_settlements_fitting_one_credit_give_no_match(tmp_path):
    """Precision over recall: a false match hides a real break."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "111111111111", 81834),
                     ("setl_2", "05-Jan-26", "222222222222", 81834)],
        bank=[("05/01/2026", NEFT.format(utr=""), 81834, "HDFC1")],
    )
    result = run(ledger)
    assert result.matches == []
    assert result.unmatched_credits == ["HDFC1"]
    assert sorted(result.unmatched_settlements) == ["setl_1", "setl_2"]
    assert "no match" in " ".join(result.trail["HDFC1"])


def test_a_settlement_is_claimed_once(tmp_path):
    """R0 takes the settlement; R1 must not hand the same one to a second credit."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("05/01/2026", NEFT.format(utr="207592797549"), 81834, "HDFC1"),
              ("05/01/2026", NEFT.format(utr=""), 81834, "HDFC2")],
    )
    result = run(ledger)
    assert [m.bank_ref for m in result.matches] == ["HDFC1"]
    assert result.unmatched_credits == ["HDFC2"]


def test_two_credits_naming_one_settlement_give_no_match(tmp_path):
    """A duplicated narration must not let the first credit win by file order."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("05/01/2026", NEFT.format(utr="207592797549"), 81834, "HDFC1"),
              ("05/01/2026", NEFT.format(utr="207592797549"), 81834, "HDFC2")],
    )
    result = run(ledger)
    assert result.matches == []
    assert sorted(result.unmatched_credits) == ["HDFC1", "HDFC2"]


def test_a_bundled_credit_falls_through_to_r2(tmp_path):
    """Two batches in one credit: the narration names one, the amount ties to neither."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "111111111111", 81834),
                     ("setl_2", "05-Jan-26", "222222222222", 40000)],
        bank=[("05/01/2026", NEFT.format(utr="111111111111"), 121834, "HDFC1")],
    )
    result = run(ledger)
    assert result.matches == []
    assert result.unmatched_credits == ["HDFC1"]


def test_a_date_outside_the_window_is_not_matched_by_r1(tmp_path):
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834)],
        bank=[("20/01/2026", NEFT.format(utr=""), 81834, "HDFC1")],
    )
    result = run(ledger)
    assert result.matches == []
    assert "within a rupee and two days" in " ".join(result.trail["HDFC1"])


def test_identical_input_produces_identical_output(tmp_path):
    """Acceptance criterion 4: re-running creates zero new matches."""
    ledger = ledger_of(
        tmp_path,
        settlements=[("setl_1", "05-Jan-26", "207592797549", 81834),
                     ("setl_2", "06-Jan-26", "222222222222", 40000)],
        bank=[("05/01/2026", NEFT.format(utr="207592797549"), 81834, "HDFC1"),
              ("06/01/2026", NEFT.format(utr="2222222"), 40000, "HDFC2")],
    )
    first, second = run(ledger), run(ledger)
    assert first.matches == second.matches
    assert first.trail == second.trail


def test_the_engine_never_reads_the_ground_truth_file():
    """PRD 8 anti-circularity. The generator writes the answer key; nothing else opens it.

    Static, like the no-float scan: a runtime check would only catch the paths a test
    happened to walk, and this must hold for every path.
    """
    culprits = []
    for path in sorted(ROOT.joinpath("src").rglob("*.py")):
        if path.parts[path.parts.index("src") + 1] == "generate":
            continue
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "ground_truth" in node.value or node.value.strip("/") == "eval":
                    culprits.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.value!r}")
            if isinstance(node, ast.Name) and node.id == "ground_truth":
                culprits.append(f"{path.relative_to(ROOT)}:{node.lineno} name ground_truth")
    assert not culprits, "the engine must never read the answer key: " + "; ".join(culprits)


def test_train_dataset_matches_with_no_false_positives():
    """The engine is scored against the answer key here, never inside src/."""
    import json

    folder = ROOT.joinpath("data", "train")
    key = ROOT.joinpath("eval", "ground_truth", "train.json")
    if not folder.exists() or not key.exists():
        import pytest
        pytest.skip("run: PYTHONPATH=src python -m generate train")

    result = run(load(folder))
    truth = {m["bank_ref"]: set(m["settlement_ids"])
             for m in json.loads(key.read_text(encoding="utf-8"))["matches"]}
    wrong = [m.bank_ref for m in result.matches
             if truth.get(m.bank_ref) != set(m.settlement_ids)]
    assert not wrong, f"{len(wrong)} false matches: {wrong[:5]}"
    assert len(result.matches) >= 30
