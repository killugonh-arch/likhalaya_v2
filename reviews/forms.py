from django import forms


class ReviewForm(forms.Form):
    rating = forms.IntegerField(
        min_value=1, max_value=5,
        error_messages={
            'required': 'Please pick a star rating.',
            'invalid': 'Please pick a star rating.',
            'min_value': 'Please pick a star rating.',
            'max_value': 'Please pick a star rating.',
        },
    )
    comment = forms.CharField(required=False, max_length=1000, strip=True)


class ReviewReplyForm(forms.Form):
    staff_reply = forms.CharField(required=False, max_length=1000, strip=True)