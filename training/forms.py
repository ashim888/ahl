from django import forms
from django.forms import inlineformset_factory

from .models import CourseModule, TrainingCourse


class TrainingCourseForm(forms.ModelForm):
    """Editorial course form. Modules are edited alongside it through
    CourseModuleFormSet (see CourseFormMixin in views.py).
    """

    class Meta:
        model = TrainingCourse
        fields = [
            'title', 'subtitle', 'category', 'description', 'cover_image',
            'level', 'mode', 'language', 'duration', 'effort', 'start_date', 'offers_certificate',
            'price', 'max_enrollments', 'is_active', 'is_featured',
            'learning_outcomes', 'audience', 'prerequisites', 'faqs',
            'instructor', 'instructor_title', 'instructor_bio', 'instructor_photo',
            'syllabus',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5}),
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'learning_outcomes': forms.Textarea(attrs={'rows': 5}),
            'audience': forms.Textarea(attrs={'rows': 3}),
            'prerequisites': forms.Textarea(attrs={'rows': 3}),
            'faqs': forms.Textarea(attrs={'rows': 6}),
            'instructor_bio': forms.Textarea(attrs={'rows': 4}),
            'syllabus': forms.Textarea(attrs={'rows': 4}),
        }


class CourseModuleForm(forms.ModelForm):
    class Meta:
        model = CourseModule
        fields = ['order', 'title', 'duration', 'summary']
        widgets = {'summary': forms.Textarea(attrs={'rows': 2})}


CourseModuleFormSet = inlineformset_factory(
    TrainingCourse, CourseModule, form=CourseModuleForm, extra=3, can_delete=True,
)
