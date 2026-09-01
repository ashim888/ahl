# Seeds the primary nav from the "menu-items" proposal (Journal, Policy &
# Economy, Health Tech, Service Delivery, Opinions, each with their given
# sub-categories), plus Training and Issues as two more top-level entries
# that link straight to their existing pages instead of a Section landing
# page (see Section.link_url_name).
#
# Nepali names are seeded ONLY where the source document actually gave one —
# the 5 subject headers have both languages in the proposal's nav table, but
# none of the sub-category names do, and Training/Issues aren't in the
# proposal at all. Leaving those name_ne blank isn't a bug: modeltranslation
# falls back to name_en automatically when name_ne is empty (verified via
# shell), so the nav still renders correctly in Nepali — just in English for
# the not-yet-translated entries — until an editor fills in a real
# translation, rather than guessing at Nepali medical terminology here.
from django.db import migrations

TOP_LEVEL_SECTIONS = [
    {
        'slug': 'journal', 'name_en': 'Journal', 'name_ne': 'जर्नल',
        'children': [
            {'slug': 'clinical-practice', 'name_en': 'Clinical Practice'},
            {'slug': 'public-health', 'name_en': 'Public Health'},
            {'slug': 'medical-education', 'name_en': 'Medical Education'},
            {'slug': 'traditional-medicine', 'name_en': 'Traditional Medicine'},
        ],
    },
    {
        'slug': 'policy-economy', 'name_en': 'Policy & Economy', 'name_ne': 'नीति र अर्थराजनीति',
        'children': [
            {'slug': 'federal-governance', 'name_en': 'Federal Governance'},
            {'slug': 'health-insurance-nhip', 'name_en': 'Health Insurance (NHIP)'},
            {'slug': 'uhc-financing', 'name_en': 'UHC & Financing'},
        ],
    },
    {
        'slug': 'health-tech', 'name_en': 'Health Tech', 'name_ne': 'प्रविधि तथा नवप्रवर्तन',
        'children': [
            {'slug': 'ai-in-health', 'name_en': 'AI in Health'},
            {'slug': 'emr-telemedicine', 'name_en': 'EMR & Telemedicine'},
            {'slug': 'pharma-devices', 'name_en': 'Pharma & Devices'},
        ],
    },
    {
        'slug': 'service-delivery', 'name_en': 'Service Delivery', 'name_ne': 'सेवा प्रवाह र प्रणाली',
        'children': [
            {'slug': 'quality-standards', 'name_en': 'Quality Standards'},
            {'slug': 'tertiary-primary-care', 'name_en': 'Tertiary & Primary Care'},
            {'slug': 'disaster-emergency', 'name_en': 'Disaster & Emergency'},
        ],
    },
    {
        'slug': 'opinions', 'name_en': 'Opinions', 'name_ne': 'विचार र विश्लेषण',
        'children': [
            {'slug': 'editorials', 'name_en': 'Editorials'},
            {'slug': 'expert-columns', 'name_en': 'Expert Columns'},
            {'slug': 'case-studies', 'name_en': 'Case Studies'},
        ],
    },
    {
        'slug': 'training', 'name_en': 'Training', 'name_ne': '',
        'link_url_name': 'training:course_list', 'children': [],
    },
    {
        'slug': 'issues', 'name_en': 'Issues', 'name_ne': '',
        'link_url_name': 'issues:issue_list', 'children': [],
    },
]

ALL_SLUGS = [top['slug'] for top in TOP_LEVEL_SECTIONS] + [
    child['slug'] for top in TOP_LEVEL_SECTIONS for child in top['children']
]


def seed_sections(apps, schema_editor):
    Section = apps.get_model('sections', 'Section')
    for top_order, top in enumerate(TOP_LEVEL_SECTIONS):
        top_section = Section.objects.create(
            slug=top['slug'], name_en=top['name_en'], name_ne=top['name_ne'],
            name=top['name_en'], order=top_order, link_url_name=top.get('link_url_name', ''),
        )
        for child_order, child in enumerate(top['children']):
            Section.objects.create(
                slug=child['slug'], name_en=child['name_en'], name_ne=child.get('name_ne', ''),
                name=child['name_en'], order=child_order, parent=top_section,
            )


def remove_seeded_sections(apps, schema_editor):
    Section = apps.get_model('sections', 'Section')
    Section.objects.filter(slug__in=ALL_SLUGS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sections', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_sections, remove_seeded_sections),
    ]
