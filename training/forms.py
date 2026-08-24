from django import forms

from .models import TrainingCourse


class TrainingCourseForm(forms.ModelForm):
    class Meta:
        model = TrainingCourse
        fields = ['title', 'description', 'instructor', 'price', 'duration', 'syllabus', 'max_enrollments', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'syllabus': forms.Textarea(attrs={'rows': 6}),
        }
