"""Every rule gets at least one positive and one negative example (TRD §6.3)."""

import pytest
from helpers import claim, listing, photo_print

from praman.rules import load_rules, match_rules, plastic_context, rule_lookup, term_in

BAGS = listing(title="Compostable Garbage Bags - Medium", tags=["garbage_bags"])
BRUSH = listing(title="Bamboo Toothbrush", body="A bamboo handle with nylon bristles.")


def ids(quote, type_="specific", scope="product", lst=BRUSH, pp=None, is_claim=True):
    return match_rules(claim(quote, type_, scope, is_claim=is_claim), lst, pp)


def test_every_rule_loads_with_summary_and_clause():
    rules = load_rules()
    assert sorted(rules) == [f"R{i:02d}" for i in range(1, 15)]
    for r in rules.values():
        assert r.summary and r.clause and r.name


@pytest.mark.parametrize(
    "rule_id, positive, negative",
    [
        # (rule, (quote, type, scope, listing), (quote, type, scope, listing))
        (
            "R01",
            ("Eco-friendly bags", "vague", "product", BRUSH),
            ("Compostable", "specific", "product", BRUSH),
        ),
        (
            "R02",
            ("100% plastic-free", "specific", "product", BRUSH),
            ("Plastic free vibes", "vague", "product", BRUSH),
        ),
        (
            "R04",
            ("Eco-friendly", "vague", "unclear", BRUSH),
            ("Eco-friendly", "vague", "product", BRUSH),
        ),
        (
            "R05",
            ("44% lower emissions", "comparative", "process", BRUSH),
            ("lower emissions", "specific", "process", BRUSH),
        ),
        (
            "R06",
            ("Net zero by 2030", "future", "brand", BRUSH),
            ("Net zero by 2030", "specific", "brand", BRUSH),
        ),
        (
            "R07",
            ("100% compostable garbage bags", "specific", "product", BAGS),
            ("Compostable bamboo handle", "specific", "part", BRUSH),
        ),
        (
            "R08",
            ("100% compostable garbage bags", "specific", "product", BAGS),
            ("Compostable bamboo handle", "specific", "part", BRUSH),
        ),
        (
            "R09",
            ("Oxo-biodegradable bags", "specific", "product", BAGS),
            ("Biodegradable envelopes", "specific", "product", BRUSH),
        ),
        (
            "R10",
            ("Certified compostable", "specific", "product", BRUSH),
            ("Compostable", "specific", "product", BRUSH),
        ),
        (
            "R12",
            ("Cuts greenhouse gas emissions by half", "specific", "process", BRUSH),
            ("Cuts emissions by half", "specific", "process", BRUSH),
        ),
        (
            "R13",
            ("Gentle on nature", "vague", "product", BRUSH),
            ("Gentle on skin", "vague", "product", BRUSH),
        ),
        (
            "R14",
            ("Lab tested to biodegrade in 90 days", "specific", "product", BRUSH),
            ("Biodegrades in 90 days", "specific", "product", BRUSH),
        ),
    ],
)
def test_rule_positive_and_negative(rule_id, positive, negative):
    q, t, s, lst = positive
    assert rule_id in ids(q, t, s, lst), f"{rule_id} should match {q!r}"
    q, t, s, lst = negative
    assert rule_id not in ids(q, t, s, lst), f"{rule_id} should not match {q!r}"


def test_r11_only_for_not_a_claim():
    assert ids("Building Blocks of Sustainability", "vague", is_claim=False) == ["R11"]
    assert "R11" not in ids("Eco-friendly", "vague")


def test_r03_is_attached_by_the_verdict_not_by_matching():
    assert "R03" not in ids("Eco-friendly", "vague")


def test_type_fallback_when_no_term_matches():
    assert ids("Breaks down naturally in the environment", "specific", "disposal") == ["R02"]
    assert ids("Kind to the oceans", "vague") == ["R01"]


def test_term_edges():
    assert term_in("natural", "100% natural ingredients")
    assert not term_in("natural", "breaks down naturally")
    assert term_in("0% plastic", "100% ecofriendly, 0% plastic.")
    assert not term_in("0% plastic", "100% plastic")
    assert term_in("by 20", "net zero by 2030")
    assert term_in("first ", "first 3 blade razor")
    assert not term_in("green", "greenery")


def test_plastic_context():
    assert plastic_context(BAGS)
    assert not plastic_context(BRUSH)  # "nylon bristles" is a part, not a plastic product
    assert not plastic_context(listing(title="Plastic-free kit"))
    pp = photo_print((3, "composition", "Carrier Resin- PE Virgin Grade"))
    assert plastic_context(listing(title="Disposal sachet refill"))
    assert plastic_context(listing(title="Refill"), pp)


def test_rule_lookup_tool():
    info = rule_lookup("R07")
    assert info["id"] == "R07" and "CPCB" in info["summary"]
    assert info["clause"].startswith("Rule 4")


def test_rule_packs_load_through_the_same_loader():
    from praman.rules import list_packs, load_pack, matched_terms

    packs = {p["name"]: p for p in list_packs()}
    assert set(packs) >= {"green_claims", "food_labels"}
    assert packs["green_claims"]["status"] == "active" and len(packs["green_claims"]["rules"]) == 14
    _, food = load_pack("food_labels")
    assert sorted(food) == ["F01", "F02", "F03", "F04"]
    for r in food.values():
        assert r.summary and r.name and r.triggers.terms and r.clause_text
    # The same trigger matching works on another rulebook's terms
    assert matched_terms(food["F01"], "Certified organic jaggery")
    assert matched_terms(food["F03"], "High protein, no added sugar")
    assert not matched_terms(food["F04"], "A crunchy breakfast cereal")
    # The agent's own rulebook is unchanged
    assert load_pack("green_claims")[1] is load_rules()


@pytest.mark.parametrize(
    "quote, ctype, rule_id",
    [
        # Words the CCPA guidelines name (24 Oct 2026 additions), each mapped to its clause's rule
        ("Plastic positive brand", "specific", "R02"),  # clause 6(5)
        ("Refillable bottle", "specific", "R02"),  # clause 6(5)
        ("100% natural", "specific", "R02"),  # clause 6(5)
        ("Chemical-free cleaning", "vague", "R01"),  # Annexure 1 para 3
        ("Certified organic cotton", "specific", "R10"),  # Annexure 1 para 6
        ("Recommended by environmental experts", "vague", "R10"),  # Annexure 1 para 6
        ("30% lighter compared to our old pack", "comparative", "R05"),  # clause 6(4)
        ("We pledge to go plastic-free", "future", "R06"),  # clause 7
        ("A lower carbon footprint", "comparative", "R12"),  # clause 5(b)
        ("Gentle on skin and Mother Earth", "vague", "R13"),  # Annexure 1 para 5
        ("Independently tested to compost at home", "specific", "R14"),  # clause 6(2)
    ],
)
def test_ccpa_words_reach_their_rule(quote, ctype, rule_id):
    assert rule_id in ids(quote, ctype), f"{quote!r} should reach {rule_id}"


def test_new_words_do_not_catch_plain_product_features():
    from praman.rules import matched_terms

    # "Reusable" is a product feature: no rule lists it as a trigger word
    assert not any(matched_terms(r, "Reusable lunch box") for r in load_rules().values())
    # A bare "greener" slogan is not a comparison (the L14 pack prints "LIVE GREENER")
    assert "R05" not in ids("Live greener", "vague")
    # nor a slogan that only mentions less plastic (L08: "one less plastic one in the ocean")
    assert "R05" not in ids("One less plastic one in the ocean", "vague")
