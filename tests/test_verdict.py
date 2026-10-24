"""The TRD §9 decision table, row by row, and both guards."""

from helpers import claim, ev

from praman.models import VerdictLabel as V
from praman.verdict import ClaimState, decide_verdict, label_check_claim, label_verdict

COMPOSTABLE = claim("100% compostable garbage bags", rule_ids=["R02", "R07", "R08"])


def decide(c, evidence=(), searched=("text",), open_sources=(), exhausted=False):
    st = ClaimState(
        claim=c,
        rule_ids=c.rule_ids,
        evidence=list(evidence),
        searched=list(searched),
        open_sources=list(open_sources),
        budget_exhausted=exhausted,
    )
    return decide_verdict(st)


def test_row1_not_a_claim():
    d = decide(
        claim("Building Blocks of Sustainability", "vague", is_claim=False, rule_ids=["R11"])
    )
    assert d.verdict.label == V.NOT_A_CLAIM and d.verdict.rule_ids == ["R11"]


def test_row2_contradiction_wins_over_registry_match():
    reg = ev(source="registry", kind="registry_match", covers_claim="yes", certifier="CPCB")
    con = ev(
        source="photo", covers_claim="contradicts", note="Pack says PE Virgin Grade.", rule_id="R09"
    )
    d = decide(COMPOSTABLE, [reg, con])
    assert d.verdict.label == V.CONTRADICTED
    assert d.verdict.evidence_ids == [con.id]
    assert "R09" in d.verdict.rule_ids


def test_row3_registry_match_backs_compostable_plastic():
    lead = ev(source="photo", kind="registry_match", covers_claim="partly", certifier="CPCB")
    reg = ev(
        source="registry",
        kind="registry_match",
        covers_claim="yes",
        certifier="CPCB",
        detail="CPCB certified list, S.No. 32: Greendotbiopak, Gujarat — matches code",
    )
    d = decide(COMPOSTABLE, [lead, reg], searched=("text", "photos", "registry"))
    assert d.verdict.label == V.BACKED and d.row == 3
    assert set(d.verdict.evidence_ids) == {lead.id, reg.id}
    assert "S.No. 32" in d.verdict.reason
    # Row 6: the industrial-composting label is missing, so a separate item is due
    assert d.label_missing == ["R08"]


def test_row3_needs_every_queried_maker_on_the_list():
    yes = ev(source="registry", kind="registry_match", covers_claim="yes")
    no = ev(source="registry", kind="registry_match", covers_claim="no")
    d = decide(COMPOSTABLE, [yes, no], searched=("text", "photos", "registry"))
    assert d.verdict.label == V.PARTLY


def test_row3_label_found_means_no_label_item():
    reg = ev(source="registry", kind="registry_match", covers_claim="yes")
    lab = ev(source="photo", kind="label_text", covers_claim="yes", rule_id="R08")
    d = decide(COMPOSTABLE, [reg, lab])
    assert d.verdict.label == V.BACKED and d.label_missing == []


def test_photo_code_alone_is_not_proof():
    lead = ev(source="photo", kind="registry_match", covers_claim="partly", certifier="CPCB")
    d = decide(COMPOSTABLE, [lead], searched=("text", "photos"))
    assert d.verdict.label == V.PARTLY


def test_row4_product_certificate_backs_specific_claim():
    c = claim("Certified compostable to EN 13432", rule_ids=["R02", "R10"])
    cert = ev(kind="certification", covers_claim="yes", certifier="EN 13432", cert_scope="material")
    d = decide(c, [cert])
    assert d.verdict.label == V.BACKED and d.row == 4


def test_row4_unclear_scope_is_only_partly_backed():
    c = claim("Certified compostable", scope="unclear", rule_ids=["R02", "R04"])
    cert = ev(kind="certification", covers_claim="yes", certifier="EN 13432", cert_scope="material")
    assert decide(c, [cert]).verdict.label == V.PARTLY


def test_row5_company_certificate_is_partly_backed():
    c = claim("Compostable bamboo handle", scope="part", rule_ids=["R02"])
    bcorp = ev(
        source="photo",
        kind="certification",
        covers_claim="partly",
        certifier="B Corp",
        cert_scope="company",
    )
    d = decide(c, [bcorp], searched=("text", "photos"))
    assert d.verdict.label == V.PARTLY
    assert "covers the company" in d.verdict.reason
    assert "R10" in d.verdict.rule_ids  # a certificate was weighed


def test_row7_budget_exhausted_with_sources_left_needs_review():
    d = decide(COMPOSTABLE, [], searched=("text",), open_sources=("photos",), exhausted=True)
    assert d.verdict.label == V.NEEDS_REVIEW
    assert "product photos" in d.verdict.reason


def test_row8_nothing_found_is_not_backed_and_lists_sources():
    d = decide(COMPOSTABLE, [], searched=("text", "photos"))
    v = d.verdict
    assert v.label == V.NOT_BACKED
    assert v.sources_searched == ["text", "photos"]
    assert "page text and product photos" in v.reason
    assert v.missing and "CPCB" in v.missing
    assert "R03" in v.rule_ids  # no details link: the disclosure rule applies


def test_false_backed_guard_qualifier_and_link_are_not_proof():
    c = claim("eco-friendly", "vague", rule_ids=["R01"])
    q = ev(kind="qualifier", covers_claim="yes")
    link = ev(kind="disclosure_link", covers_claim="yes")
    d = decide(c, [q, link])
    assert d.verdict.label == V.PARTLY
    assert "no certificate" in d.verdict.reason


def test_citation_guard_without_rules_needs_review():
    c = claim("Something green", rule_ids=[])
    cert = ev(kind="certification", covers_claim="yes", cert_scope="product")
    assert decide(c, [cert]).verdict.label == V.NEEDS_REVIEW


def test_label_check_item():
    lc = label_check_claim(COMPOSTABLE, "R08", "C7")
    assert lc.derived_from == "C1" and lc.location == "n/a" and lc.rule_ids == ["R08"]
    assert "compostable only under industrial composting" in lc.quote
    v = label_verdict(lc, ["text", "photos", "registry"])
    assert v.label == V.NEEDS_REVIEW
    assert v.sources_searched == ["text", "photos"]
    assert "physical product" in v.reason
