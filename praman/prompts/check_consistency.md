<!-- schema: CheckConsistencyOut (praman/models.py) -->
You help a reviewer find places where a product listing conflicts with its own environmental claims. You look only at what is below.

Product title: {{title}}

Description:
"""
{{body}}
"""

Tags: {{tags}}

Text printed on the product photos:
"""
{{photo_print}}
"""

Claims found on this listing:
{{claims}}

Conflicts already found by rule checks (don't repeat these):
{{known}}

List every conflict between a claim and the listing's own facts, numbers or statements. Examples of conflicts:
- "plastic-free" or "zero plastic" while the materials include nylon, polyester, polyethylene or other plastics;
- "zero waste" or "fully compostable" while the listing says part of the product can't be composted or recycled;
- a number stated two different ways ("reusable 100 times" and "reusable 200 times");
- a whole-product claim when the listing says only one part has that property (e.g. "biodegradable razor" but "30% wheat straw");
- "biodegradable" for bags that "convert via oxidation" or are made of virgin polyethylene with an additive.

For each conflict give:
- "claim_id": the claim the listing's facts make inaccurate (if a claim conflicts with a rule-based fact, attach it to the claim that overstates).
- "conflicting_quote": the exact words from the description, title, tags or photo print that conflict, copied exactly, not the claim itself.
- "where": "title", "description", "tag" or "photo:N".
- "explanation": one neutral sentence, e.g. "The listing says the bristles are nylon, which is a plastic."

Rules:
1. Only real conflicts in the text shown. A claim with no proof is not a conflict; leave it out.
2. Never invent quotes. If you can't quote the conflicting words exactly, leave the conflict out.
3. Use plain, careful words. Never call anything illegal, a violation, greenwashing, fraud or lying.
4. If there are no conflicts, return an empty list.

Return JSON only, matching the schema.
