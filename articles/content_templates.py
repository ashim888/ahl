from .models import Article

# Starting-point html_content skeletons, keyed by article_type. Not every type
# has one — types without an obvious universal structure (News & Commentary,
# Letter to Editor) are left out; the "Insert template" control in the article
# form simply won't appear for those.
CASE_REPORT_TEMPLATE = """
<h2>Introduction</h2>
<p>[Briefly introduce the condition and why this case is clinically notable.]</p>

<h2>Case Presentation</h2>
<p>[Patient age, sex, relevant history, presenting complaint, and examination findings.]</p>

<h2>Investigations</h2>
<p>[Relevant investigations and findings. Embed a chart or figure if useful —
see the demo case report for a worked D3.js example.]</p>

<h2>Discussion</h2>
<p>[Differential diagnosis, relevant literature<sup><a href="#ref-1">1</a></sup>,
and the reasoning behind the management approach taken.]</p>

<h2>Conclusion</h2>
<p>[The key clinical takeaway for readers.]</p>
""".strip()

ORIGINAL_RESEARCH_TEMPLATE = """
<h2>Introduction</h2>
<p>[Background, existing literature gap, and study objective.]</p>

<h2>Methods</h2>
<p>[Study design, setting, participants, and analysis approach.]</p>

<h2>Results</h2>
<p>[Key findings. Embed a chart or table if useful.]</p>

<h2>Discussion</h2>
<p>[Interpretation, comparison with prior work, limitations.]</p>

<h2>Conclusion</h2>
<p>[Summary and implications.]</p>
""".strip()

REVIEW_ARTICLE_TEMPLATE = """
<h2>Introduction</h2>
<p>[Scope of the review and why it matters now.]</p>

<h2>Methods</h2>
<p>[Search strategy and inclusion criteria, if systematic.]</p>

<h2>Discussion</h2>
<p>[Synthesis of the reviewed literature, organized thematically.]</p>

<h2>Conclusion</h2>
<p>[Key takeaways and open questions for future research.]</p>
""".strip()

EDITORIAL_TEMPLATE = """
<h2>Introduction</h2>
<p>[The issue or development this editorial responds to.]</p>

<h2>Discussion</h2>
<p>[The editorial board's perspective and reasoning.]</p>

<h2>Conclusion</h2>
<p>[Call to action or closing thought.]</p>
""".strip()

METHODOLOGY_PAPER_TEMPLATE = """
<h2>Introduction</h2>
<p>[The methodological gap this paper addresses.]</p>

<h2>Proposed Method</h2>
<p>[Describe the method, protocol, or study design being proposed.]</p>

<h2>Discussion</h2>
<p>[Strengths, limitations, and applicability.]</p>

<h2>Conclusion</h2>
<p>[Summary and recommended use cases.]</p>
""".strip()

SHORT_COMMUNICATION_TEMPLATE = """
<h2>Introduction</h2>
<p>[Brief context — short communications are preliminary, not exhaustive.]</p>

<h2>Findings</h2>
<p>[The preliminary finding(s) being reported.]</p>

<h2>Conclusion</h2>
<p>[Why this matters and what follow-up work is planned.]</p>
""".strip()

# Claim, verdict and the one-line reason go in the form's "Fact check" box;
# the text explains the reasoning so readers can follow and check it.
FACT_CHECK_TEMPLATE = """
<h2>What is being shared</h2>
<p>[Describe the claim as people meet it: where it appeared, how widely it spread, and why people may believe it.]</p>

<h2>What the evidence says</h2>
<p>[What reliable sources (WHO, NHRC, MoHP, peer-reviewed studies) actually show, cited with [1], [2]. Quote experts by name and role.]</p>

<h2>Why the claim is wrong, misleading or right</h2>
<p>[Walk through the reasoning step by step. If part of the claim is true, say which part.]</p>

<h2>What to do instead</h2>
<p>[Practical, safe advice for readers, and where to get help.]</p>
""".strip()

ARTICLE_TYPE_CONTENT_TEMPLATES = {
    Article.ArticleType.FACT_CHECK: FACT_CHECK_TEMPLATE,
    Article.ArticleType.CASE_REPORT: CASE_REPORT_TEMPLATE,
    Article.ArticleType.ORIGINAL_RESEARCH: ORIGINAL_RESEARCH_TEMPLATE,
    Article.ArticleType.REVIEW_ARTICLE: REVIEW_ARTICLE_TEMPLATE,
    Article.ArticleType.EDITORIAL: EDITORIAL_TEMPLATE,
    Article.ArticleType.METHODOLOGY_PAPER: METHODOLOGY_PAPER_TEMPLATE,
    Article.ArticleType.SHORT_COMMUNICATION: SHORT_COMMUNICATION_TEMPLATE,
}
