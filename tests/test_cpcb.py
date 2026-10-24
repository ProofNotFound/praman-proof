from praman.tools.cpcb import cpcb_lookup, find_codes, normalise_name, split_query


def _sample(fixtures_dir):
    return fixtures_dir / "cpcb_sample.csv"


def test_normalise_drops_company_suffixes():
    assert normalise_name("M/s. Greendot Biopak Pvt. Ltd.") == "greendot biopak"
    assert normalise_name("Sunshield Biotech LLP") == "sunshield biotech"
    assert normalise_name("ABC Private Limited") == "abc"


def test_split_query_reads_cpcb_codes():
    name, state, code = split_query("CPCB: CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443")
    assert (name, state) == ("GREEN DOT BIOPAK", "Gujarat")
    assert code == "CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443"
    name, state, code = split_query("Greendot Biopak Pvt Ltd, Ahmedabad, Gujarat")
    assert (name, state, code) == ("Greendot Biopak Pvt Ltd", "Gujarat", None)


def test_find_codes_exact_and_deduplicated():
    text = (
        "CPCB: CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443\n"
        "CPCB-UPC-II/SUNSHIELD BIOTECH LLP/Gujarat/131 and again "
        "CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443"
    )
    assert find_codes(text) == [
        "CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443",
        "CPCB-UPC-II/SUNSHIELD BIOTECH LLP/Gujarat/131",
    ]


def test_trd_examples_match(fixtures_dir):
    r = cpcb_lookup("Greendot Biopak Pvt Ltd, Ahmedabad, Gujarat", _sample(fixtures_dir))
    assert r.match and r.match.s_no == 32 and r.score >= 90
    r = cpcb_lookup("Sunshield Biotech LLP", _sample(fixtures_dir))
    assert r.match and r.match.s_no == 2
    r = cpcb_lookup("CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443", _sample(fixtures_dir))
    assert r.match and r.match.s_no == 32  # spaced code name vs joined list name
    assert r.rows_scanned == 4 and r.rows_uncertified == 1 and r.list_date == "2023-10-26"


def test_unrelated_maker_does_not_match(fixtures_dir):
    r = cpcb_lookup("Shrianand Poly, Gurugram, Haryana", _sample(fixtures_dir))
    assert r.match is None
    assert r.score < 80


def test_state_lowers_threshold_only_when_it_matches(fixtures_dir):
    # "Synthetic Green Packing" ~ "Synthetic Green Packaging": between 80 and 90
    r = cpcb_lookup("Synthetic Grean Packing Co, Surat, Gujarat", _sample(fixtures_dir))
    assert 80 <= r.score < 90
    assert r.match is not None and r.match.s_no == 91
    r = cpcb_lookup("Synthetic Grean Packing Co, Pune, Maharashtra", _sample(fixtures_dir))
    assert r.match is None


def test_table_two_rows_are_returned_with_their_table(fixtures_dir):
    r = cpcb_lookup("Synthetic Uncertified Bags", _sample(fixtures_dir))
    assert r.match and r.match.table == 2


def _builder():
    import importlib.util

    from praman.config import ROOT

    spec = importlib.util.spec_from_file_location(
        "build_cpcb_csv", ROOT / "scripts" / "build_cpcb_csv.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_details_cell_parsing_drops_contact_data():
    b = _builder()
    cell = (
        "M/s Sunshield Biotech Llp,\n(Manufacturer),\nOffice Address:Shop No. 14,\nGround Floor\n"
        "Mumbai, Maharashtra – 400002\nPlant Address: Akshar Industrial\nPark, Sanand, Gujarat – 382213\n"
        "Contact Details: Tel:\n09920807654\nEmail:\nFinance@Sunshieldbiotechllp.C\nom"
    )
    d = b.parse_details(cell)
    assert d["name"] == "Sunshield Biotech Llp" and d["type"] == "Manufacturer"
    assert d["office_address"].startswith("Shop No. 14") and "Gujarat" in d["plant_address"]
    flat = " ".join(d.values()).lower()
    assert "@" not in flat and "09920807654" not in flat and "finance" not in flat


def test_join_lines_rejoins_broken_words_only():
    b = _builder()
    assert b.join_lines("Maharashtr\na", narrow=True) == "Maharashtra"
    assert b.join_lines("one time\ncertificate", narrow=True) == "one time certificate"
    assert b.join_lines("05.03.202\n4", narrow=True) == "05.03.2024"
    assert b.find_state("Bhimpore, Nani Daman 396210") == "Dadra and Nagar Haveli and Daman and Diu"
    assert b.find_state("Port Blair, South Andaman- 744105") == "Andaman and Nicobar Islands"
    assert b.state_from_pin("Thane (Dist.), Mh – 421302") == "Maharashtra"


def test_built_registry_has_no_contact_data():
    import csv
    import re

    from praman.config import CPCB_PATH

    rows = list(csv.DictReader(CPCB_PATH.open()))
    t1 = [r for r in rows if r["table"] == "1"]
    assert len(t1) >= 170 and {"source"} <= set(rows[0]) and all(r["source"] == "pdf" for r in rows)
    assert any(r["s_no"] == "32" and r["name_norm"] == "greendotbiopak" for r in t1)
    text = CPCB_PATH.read_text()
    assert not re.search(r"\S+@\S+\.\w+", text)
    assert not re.search(r"(?<!\d)\d{10,}(?!\d)|\d{3,5}[- ]\d{6,8}", text)
