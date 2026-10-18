"""Shop-file anonymiser (WP-03 tooling for WP-20 real data)."""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.privacy import shopfiles
from app.privacy.shopfiles import Role, ShopfilesError, column_role, main, run

BKASH = """bKash Merchant Statement
Account Name,Motaleb General Store
Account Number,01712345678
TrxID,Date Time,Transaction Type,From/To,Amount (BDT),Fee,Balance,Reference
9C78BFNDBF,01/04/2025 12:21:40,Payment Received,01339325575,2479.00,0.00,81789.00,Abdul Motaleb baki
0XMYLMUP1C,01/04/2025 15:30:48,Cash Out,01898113289,922.00,5.00,80862.00,
"""
BAKI = """customer,phone,date given,amount,paid date,amount paid,note
Abdul Motaleb,01339325575,2025-03-20,"1,23,456.00",2025-04-01,2479.00,
Shirin Akhter,০১৮৯৮১১৩২৮৯,2025-03-22,922.00,,0.00,owes since Eid; ask Motaleb's son
"""
ORIGINALS = ["Motaleb", "Shirin", "Akhter", "01712345678", "01339325575", "01898113289",
             "০১৮৯৮১১৩২৮৯", "9C78BFNDBF", "0XMYLMUP1C", "Motaleb General Store"]


def _shop(tmp_path: Path, files: dict[str, str]) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, text in files.items():
        (raw / name).write_text(text, encoding="utf-8")
    return raw


def _run(tmp_path: Path, raw: Path, shop: str = "shop01-grocery") -> tuple[dict, Path]:
    out = tmp_path / "out"
    report = run(raw, shop, out, tmp_path / "home", echo=lambda _msg: None)
    return report, out / shop


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_statement_preamble_is_dropped_and_identifiers_are_tokenised(tmp_path: Path) -> None:
    report, out = _run(tmp_path, _shop(tmp_path, {"Motaleb bkash april.csv": BKASH}))

    rows = _rows(out / "file01.csv")
    assert len(rows) == 2
    assert report["files"][0]["preamble_rows_dropped"] == 3
    assert all(re.fullmatch(r"PHONE_[0-9a-f]{10}", r["From/To"]) for r in rows)
    assert all(re.fullmatch(r"TRX_[0-9a-f]{10}", r["TrxID"]) for r in rows)
    # Dates, amounts and plain statement words are kept for the backtests.
    assert [r["Date Time"] for r in rows] == ["01/04/2025 12:21:40", "01/04/2025 15:30:48"]
    assert [r["Amount (BDT)"] for r in rows] == ["2479.00", "922.00"]
    assert [r["Transaction Type"] for r in rows] == ["Payment Received", "Cash Out"]
    assert {r["data_mode"] for r in rows} == {"real_anonymised"}
    roles = {c["header"]: c["role"] for c in report["files"][0]["columns"]}
    assert roles["TrxID"] == "transaction_id" and roles["Balance"] == "kept"


def test_unlisted_names_in_free_text_are_shown_for_review_on_the_console_only(
        tmp_path: Path) -> None:
    # No name column anywhere, so nothing can know "Abdul Motaleb" is a name: a human must look.
    messages: list[str] = []
    report = run(_shop(tmp_path, {"a.csv": BKASH}), "shop01-grocery", tmp_path / "out",
                 tmp_path / "home", echo=messages.append)

    review_line = messages[messages.index(next(m for m in messages if "known_names.txt" in m))
                           + 1]
    assert "Abdul" in review_line and "Motaleb" in review_line
    assert "Payment" not in review_line  # ordinary statement words are not listed
    assert report["words_left_for_review"] == 2
    assert "Motaleb" not in (tmp_path / "out" / "shop01-grocery" / "REPORT.json").read_text(
        encoding="utf-8")


def test_the_same_phone_gets_the_same_token_in_every_file_even_in_bangla_digits(
        tmp_path: Path) -> None:
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": BKASH, "b.csv": BAKI}))

    bkash, baki = _rows(out / "file01.csv"), _rows(out / "file02.csv")
    assert bkash[0]["From/To"] == baki[0]["phone"]  # 01339325575
    assert bkash[1]["From/To"] == baki[1]["phone"]  # 01898113289 vs ০১৮৯৮১১৩২৮৯


def test_names_from_name_columns_are_masked_in_free_text_of_any_file(tmp_path: Path) -> None:
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": BKASH, "b.csv": BAKI}))

    bkash, baki = _rows(out / "file01.csv"), _rows(out / "file02.csv")
    name_token = baki[0]["customer"]
    assert re.fullmatch(r"PERSON_[0-9a-f]{10}", name_token)
    assert bkash[0]["Reference"] == f"{name_token} baki"
    # A first name alone, in another row's note, is caught too.
    assert "Motaleb" not in baki[1]["note"] and baki[1]["note"].startswith("owes since Eid")


def test_no_original_value_survives_in_any_output_or_the_report(tmp_path: Path) -> None:
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": BKASH, "b.csv": BAKI}))

    written = "\n".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    for original in ORIGINALS:
        assert original not in written, original
    assert sorted(p.name for p in out.iterdir()) == ["REPORT.json", "file01.csv", "file02.csv"]


def test_xlsx_sheets_become_csvs_and_workbook_metadata_is_not_carried(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    wb = Workbook()
    wb.properties.creator = "Rokeya Sultana"
    first = wb.active
    first.append(["Customer Name", "Mobile", "Amount"])
    first.append(["Rokeya Sultana", "01711111111", 1500])
    second = wb.create_sheet("Suppliers")
    second.append(["Supplier", "Amount", "Note"])
    second.append(["Green Traders", 2500.5, "rice"])
    wb.save(raw / "ledger.xlsx")

    report, out = _run(tmp_path, raw)

    assert [f["output"] for f in report["files"]] == ["file01.csv", "file01_sheet2.csv"]
    sheet1, sheet2 = _rows(out / "file01.csv"), _rows(out / "file01_sheet2.csv")
    assert sheet1[0]["Amount"] == "1500" and sheet2[0]["Amount"] == "2500.5"
    assert sheet2[0]["Supplier"].startswith("SHOP_") and sheet2[0]["Note"] == "rice"
    written = "\n".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    assert "Rokeya" not in written and "Sultana" not in written and "Green" not in written


def test_generic_labels_in_name_columns_are_kept_and_not_masked_elsewhere(
        tmp_path: Path) -> None:
    cash_book = ("date,party,amount\n2025-04-01,Walk-in customer,2364.00\n"
                 "2025-04-01,Own bank account,5000.00\n")
    bank = "Date,Description,Credit\n01-Apr-2025,OWNER DRAW Owner (personal account),11452.00\n"
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": cash_book, "b.csv": bank}))

    assert [r["party"] for r in _rows(out / "file01.csv")] == ["Walk-in customer",
                                                               "Own bank account"]
    assert _rows(out / "file02.csv")[0]["Description"] == "OWNER DRAW Owner (personal account)"


def test_a_name_in_a_phone_column_is_tokenised_and_a_biller_is_kept(tmp_path: Path) -> None:
    statement = ("TrxID,Date Time,Transaction Type,From/To,Amount\n"
                 "A1,15/04/2025 15:58:32,Send Money,Rokeya Sultana,500.00\n"
                 "A2,15/04/2025 16:00:00,Pay Bill,DESCO / Titas utilities,9710.00\n")
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": statement}))

    rows = _rows(out / "file01.csv")
    assert re.fullmatch(r"PERSON_[0-9a-f]{10}", rows[0]["From/To"])
    assert rows[1]["From/To"] == "DESCO / Titas utilities"


def test_a_shop_gets_one_token_in_name_columns_and_in_free_text(tmp_path: Path) -> None:
    cash_book = "date,party,amount\n2025-04-02,Bhai Bhai Corporation,1579.00\n"
    bank = "Date,Description,Credit\n02-Apr-2025,COLLECTION Bhai Bhai Corporation,1579.00\n"
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": cash_book, "b.csv": bank}))

    token = _rows(out / "file01.csv")[0]["party"]
    assert re.fullmatch(r"SHOP_[0-9a-f]{10}", token)
    assert _rows(out / "file02.csv")[0]["Description"] == f"COLLECTION {token}"


def test_an_existing_data_mode_column_is_overwritten_not_duplicated(tmp_path: Path) -> None:
    _, out = _run(tmp_path, _shop(tmp_path, {"a.csv": "date,amount,Data Mode\n2025-04-01,5,x\n"}))

    lines = (out / "file01.csv").read_text(encoding="utf-8").splitlines()
    assert lines == ["date,amount,Data Mode", "2025-04-01,5,real_anonymised"]


@pytest.mark.parametrize(("header", "values", "role"), [
    ("Amount", ["1,23,456.00", "500", "(1,200.50)"], Role.KEPT),       # lakh grouping, negative
    ("Date Time", ["01/04/2025 12:21:40", "2025-04-01T09:05"], Role.KEPT),
    ("Notes", ["01712345678"], Role.FREE),                             # 11 digits: not an amount
    ("Total", ["1987654321"], Role.FREE),                              # NID-length number
    ("Cancelled", ["yes"], Role.FREE),                                 # not a "cell" column
    ("Item name", ["Rice"], Role.FREE),                                # goods, not a person
    ("গ্রাহকের নাম", ["রহিম"], Role.NAME),
    ("মোবাইল নম্বর", ["০১৭১১১১১১১১"], Role.PHONE),
    ("Account No.", ["1234567890"], Role.ACCOUNT),
    ("Counterpart", ["01747382007"], Role.NAME),                       # Nagad export header
])
def test_column_roles(header: str, values: list[str], role: Role) -> None:
    assert column_role(header, values) is role


def test_a_file_with_anything_left_after_tokenising_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate a tokeniser miss in free text: the final scan must catch it and fail closed.
    monkeypatch.setattr(shopfiles.ShopTokeniser, "free_cell", lambda self, value, counts: value)
    raw = _shop(tmp_path, {"a.csv": "date,note\n2025-04-01,call 01712345678\n"})
    home, out = tmp_path / "home", tmp_path / "out"

    code = main([str(raw), "--shop", "shop02-pharmacy", "--out", str(out), "--home", str(home)])

    report = json.loads((out / "shop02-pharmacy" / "REPORT.json").read_text(encoding="utf-8"))
    assert code == 1
    assert report["refused"] == ["file01.csv"]
    assert report["files"][0]["refused_kinds"] == {"PHONE": 1}
    assert not (out / "shop02-pharmacy" / "file01.csv").exists()
    assert "01712345678" not in json.dumps(report)


def test_raw_files_inside_a_git_repository_are_refused(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    raw = _shop(tmp_path, {"a.csv": BAKI})
    with pytest.raises(ShopfilesError, match="inside a git repository"):
        run(raw, "shop01-grocery", tmp_path / "out", tmp_path.parent / "home-x", echo=print)


def test_shop_id_must_be_a_neutral_slug(tmp_path: Path) -> None:
    raw = _shop(tmp_path, {"a.csv": BAKI})
    with pytest.raises(ShopfilesError, match="--shop"):
        run(raw, "Motaleb Store", tmp_path / "out", tmp_path / "home", echo=print)


def test_tokens_are_stable_across_runs_stale_outputs_go_and_the_key_is_private(
        tmp_path: Path) -> None:
    raw = _shop(tmp_path, {"a.csv": BKASH, "b.csv": BAKI, "c.csv": "date,amount\n2025-04-01,5\n"})
    _, out = _run(tmp_path, raw)
    first = [(out / f"file0{n}.csv").read_text(encoding="utf-8") for n in (1, 2)]

    (raw / "c.csv").unlink()
    _, out = _run(tmp_path, raw)

    assert [(out / f"file0{n}.csv").read_text(encoding="utf-8") for n in (1, 2)] == first
    assert not (out / "file03.csv").exists()
    key_file = tmp_path / "home" / "shopfiles.key"
    assert len(bytes.fromhex(key_file.read_text(encoding="ascii"))) == 32
    if os.name != "nt":
        assert key_file.stat().st_mode & 0o777 == 0o600


def test_photos_are_skipped_and_counted_and_known_names_are_masked(tmp_path: Path) -> None:
    raw = _shop(tmp_path, {"a.csv": "date,note\n2025-04-01,Rokeya apa will pay Friday\n",
                           "known_names.txt": "Rokeya Begum\n"})
    (raw / "baki page 1.jpg").write_bytes(b"\xff\xd8\xff")

    report, out = _run(tmp_path, raw)

    assert report["skipped_files"] == {"image": 1}
    assert report["known_names_listed"] == 1
    note = _rows(out / "file01.csv")[0]["note"]
    assert re.fullmatch(r"PERSON_[0-9a-f]{10} apa will pay Friday", note)
