"""Structured-data helper for CourseDetailView — mirrors articles/seo.py's
pattern (kept out of views.py, reuses articles.seo.ld_json for the shared
JSON-LD escaping) rather than duplicating that escaping logic here.
"""
from articles.seo import ld_json

# No CURRENCY_CODE setting exists anywhere in the project, and the two
# money-handling apps actually disagree: billing's templates render "₹"
# (INR) throughout, but training/course_list.html and course_detail.html
# both render "$" for TrainingCourse.price specifically — a pre-existing
# inconsistency this function isn't the place to silently resolve. Matches
# what a reader actually sees on *this* course page, not billing's currency.
CURRENCY_CODE = 'USD'


def course_structured_data(course, journal_name):
    """schema.org Course — powers rich results (price, provider) for a
    training program listing.
    """
    return ld_json({
        '@context': 'https://schema.org',
        '@type': 'Course',
        'name': course.title,
        'description': course.description,
        'provider': {'@type': 'Organization', 'name': journal_name},
        'hasCourseInstance': {
            '@type': 'CourseInstance',
            'courseMode': 'online',
            'instructor': {'@type': 'Person', 'name': course.instructor},
        },
        'offers': {
            '@type': 'Offer',
            'price': str(course.price),
            'priceCurrency': CURRENCY_CODE,
        },
    })
