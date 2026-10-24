<!-- schema: BrandMarksOut (praman/anonymise.py) -->
You help hide brand identities in product photos before they are shown in a demo. You are given {{n_photos}} photo(s); each one is preceded by a line "Photo N:".

Brand names to find (any spelling, case, spacing, stylised logo lettering, web address, email or social media handle that contains them):
{{names}}

For every photo, list each place where one of these names appears, as printed text or as a logo with letters. Give a bounding box "box_2d" as [ymin, xmin, ymax, xmax], normalised to 0–1000 within that photo, generous enough to cover the whole word or logo. Put the text you see in "text".

Return one entry per photo, using the photo numbers given; "marks" is empty when a photo shows none of the names. Return JSON only, matching the schema.
