from django import forms

from .models import AdSlot


class AdSlotForm(forms.ModelForm):
    class Meta:
        model = AdSlot
        fields = ['sponsor_name', 'zone', 'image', 'link_url', 'start_date', 'end_date', 'is_active']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
