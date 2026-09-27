"""Structured-data helper for CourseDetailView — mirrors articles/seo.py's
pattern (kept out of views.py, reuses articles.seo.ld_json for the shared
JSON-LD escaping) rather than duplicating that escaping logic here.
"""
from django.conf import settings

from articles.seo import ld_json

# schema.org CourseInstance.courseMode values for TrainingCourse.Mode.
COURSE_MODE_SCHEMA = {'online': 'online', 'in_person': 'onsite', 'hybrid': 'blended'}


def course_structured_data(course, journal_name, image_url=None):
    """schema.org Course — powers rich results (price, provider) for a
    training program listing.
    """
    return ld_json({
        '@context': 'https://schema.org',
        '@type': 'Course',
        'name': course.title,
        'description': course.subtitle or course.description,
        'image': image_url,
        'provider': {'@type': 'Organization', 'name': journal_name},
        'educationalLevel': course.get_level_display() if course.level != course.Level.ALL_LEVELS else None,
        'inLanguage': course.language or None,
        'teaches': course.learning_outcome_list or None,
        'hasCourseInstance': {
            '@type': 'CourseInstance',
            'courseMode': COURSE_MODE_SCHEMA.get(course.mode, 'online'),
            'instructor': {'@type': 'Person', 'name': course.instructor},
            **({'startDate': course.start_date.isoformat()} if course.start_date else {}),
        },
        'offers': {
            '@type': 'Offer',
            'price': str(course.price),
            'priceCurrency': settings.CURRENCY_CODE,
            'category': 'Paid' if course.price else 'Free',
        },
    })
