# A starting-point body_html skeleton for a new issue — same idea as
# articles/content_templates.py's per-article-type skeletons, but just one:
# newsletter issues don't have a "type" to key off of, and most editorial
# newsletters follow this same "roundup" shape regardless.
WEEKLY_DIGEST_TEMPLATE = """
<p>[A short intro line — what's in this issue, or why it's worth reading this week.]</p>

<h2>Top Story</h2>
<p>[One or two sentences on the lead story, with a link to the full article.]</p>

<h2>Also This Week</h2>
<p>[A short list or a few sentences on other recent articles worth calling out.]</p>

<h2>From the Editors</h2>
<p>[Optional — a note, an upcoming issue theme, or a call for reader pitches.]</p>
""".strip()
