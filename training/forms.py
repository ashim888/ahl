from django import forms

from ajna_health_lens.forms import apply_tailwind_widgets

from .models import TrainingCourse


class TrainingCourseForm(forms.ModelForm):
    class Meta:
        model = TrainingCourse
        fields = ['title', 'description', 'instructor', 'price', 'duration', 'syllabus', 'max_enrollments', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'syllabus': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_tailwind_widgets(self, skip=('cv_file', 'file', 'photo', 'is_active'))
