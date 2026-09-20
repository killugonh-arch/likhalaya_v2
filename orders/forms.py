from django import forms
from .models import Order

class CheckoutForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['full_name', 'email', 'phone', 'address', 'city', 'province', 'zip_code', 'payment_method', 'notes']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Special instructions (optional)'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.EmailInput, forms.Textarea)):
                field.widget.attrs.update({'class': 'form-control'})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({'class': 'form-select'})
        if user and user.is_authenticated:
            self.fields['full_name'].initial = user.get_full_name()
            self.fields['email'].initial = user.email
            self.fields['phone'].initial = user.phone
            self.fields['address'].initial = user.address
