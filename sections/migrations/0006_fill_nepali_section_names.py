# Fills Section.name_ne for the seeded navigation sections (0002_seed_primary_nav)
# that still have no Nepali name, so the Nepali-language nav isn't mostly
# English. Only blank name_ne values are touched — anything an editor has
# already typed in is left as is — and sections are matched by their English
# name, so renamed or new sections are skipped.
from django.db import migrations

NEPALI_NAMES = {
    'AI in Health': 'स्वास्थ्यमा एआई',
    'Case Studies': 'केस अध्ययन',
    'Clinical Practice': 'क्लिनिकल अभ्यास',
    'Disaster & Emergency': 'विपद् तथा आपतकाल',
    'EMR & Telemedicine': 'इएमआर तथा टेलिमेडिसिन',
    'Editorials': 'सम्पादकीय',
    'Expert Columns': 'विज्ञ स्तम्भ',
    'Federal Governance': 'संघीय शासन',
    'Health Insurance (NHIP)': 'स्वास्थ्य बीमा (NHIP)',
    'Issues': 'अंकहरू',
    'Medical Education': 'चिकित्सा शिक्षा',
    'Pharma & Devices': 'औषधि तथा उपकरण',
    'Public Health': 'जनस्वास्थ्य',
    'Quality Standards': 'गुणस्तर मापदण्ड',
    'Tertiary & Primary Care': 'तृतीयक तथा प्राथमिक सेवा',
    'Traditional Medicine': 'परम्परागत चिकित्सा',
    'Training': 'तालिम',
    'UHC & Financing': 'सर्वव्यापी स्वास्थ्य सेवा तथा वित्त',
}


def fill_names(apps, schema_editor):
    Section = apps.get_model('sections', 'Section')
    for section in Section.objects.filter(name_en__in=NEPALI_NAMES):
        if not section.name_ne:
            section.name_ne = NEPALI_NAMES[section.name_en]
            section.save(update_fields=['name_ne'])


class Migration(migrations.Migration):

    dependencies = [
        ('sections', '0005_convert_database_to_utf8mb4'),
    ]

    operations = [
        migrations.RunPython(fill_names, migrations.RunPython.noop),
    ]
