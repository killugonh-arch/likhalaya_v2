from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, SetPasswordForm, PasswordChangeForm
from .models import CustomUser

AVATAR_MAX_SIZE = 2 * 1024 * 1024  # 2 MB


class NoReuseSetPasswordForm(SetPasswordForm):
    """
    Same as Django's SetPasswordForm (used on the password-reset-confirm
    page), but rejects a new password that's identical to the account's
    current password.
    """

    def clean_new_password2(self):
        password = super().clean_new_password2()
        if password and self.user.check_password(password):
            raise forms.ValidationError(
                'New password can\'t be the same as your old password. Please choose a different one.',
                code='password_same_as_old',
            )
        return password


class NoReusePasswordChangeForm(PasswordChangeForm):
    """
    Same as Django's PasswordChangeForm (used on the logged-in "Change
    Password" page), but rejects a new password that's identical to the
    account's current password — mirrors NoReuseSetPasswordForm above so
    both password-change paths enforce the same rule.
    """

    def clean_new_password2(self):
        password = super().clean_new_password2()
        if password and self.user.check_password(password):
            raise forms.ValidationError(
                'New password can\'t be the same as your old password. Please choose a different one.',
                code='password_same_as_old',
            )
        return password


def validate_avatar_size(value):
    if value and value.size > AVATAR_MAX_SIZE:
        raise forms.ValidationError('Profile picture must be under 2 MB.')


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=50)
    last_name = forms.CharField(max_length=50)
    agree_terms = forms.BooleanField(
        required=True,
        error_messages={'required': 'You must agree to the Terms of Service.'}
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The template only collects name/email/password — there's no
        # username field on the page. Auto-derive it from the email instead
        # of requiring input the user never sees (that mismatch was making
        # every signup fail Django's built-in "this field is required"
        # check for username, silently, since the template never rendered
        # that error either).
        self.fields['username'].required = False
        self.fields['username'].widget = forms.HiddenInput()
        for name, field in self.fields.items():
            if name == 'agree_terms':
                field.widget.attrs.update({'class': 'form-check-input'})
            elif name != 'username':
                field.widget.attrs.update({'class': 'form-control'})
        placeholders = {
            'first_name': 'Enter your first name',
            'last_name': 'Enter your last name',
            'email': 'Enter your email address',
            'password1': 'Enter your password',
            'password2': 'Confirm your password',
        }
        for fname, text in placeholders.items():
            if fname in self.fields:
                self.fields[fname].widget.attrs['placeholder'] = text

    def clean_username(self):
        email = self.data.get('email', '').strip()
        username = self.cleaned_data.get('username') or email
        # If a previous signup attempt used this username but never verified
        # its email (is_active=False), it was abandoned — clear it out so
        # the person isn't permanently blocked from using their own username.
        CustomUser.all_objects.filter(username=username, is_active=False).delete()
        if CustomUser.all_objects.filter(username=username, is_active=True).exists():
            raise forms.ValidationError('A user with that username already exists.')
        return username

    def clean_password1(self):
        # Server-side twin of the strength check on the register page, so a
        # weak password is rejected even if the browser check is bypassed.
        pw = self.cleaned_data.get('password1') or ''
        score = 0
        if len(pw) >= 8:
            score += 1
        if len(pw) >= 12:
            score += 1
        if any(c.isupper() for c in pw):
            score += 1
        if any(c.isdigit() for c in pw):
            score += 1
        if any(not c.isalnum() for c in pw):
            score += 1
        if score < 2:
            raise forms.ValidationError('Password is weak. Please choose another one.')
        return pw

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # Clear out any abandoned, never-verified signup that used this email
        # (e.g. someone who registered, saw the OTP page, then hit Back).
        CustomUser.all_objects.filter(email=email, is_active=False).delete()
        if CustomUser.all_objects.filter(email=email, is_active=True).exists():
            raise forms.ValidationError('An account with that email already exists.')
        return email

class OTPVerifyForm(forms.Form):
    code = forms.CharField(
        max_length=6, min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control text-center',
            'style': 'letter-spacing:8px;font-size:24px;font-weight:700;',
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'placeholder': '------',
        })
    )


class LoginForm(AuthenticationForm):
    # The field is still named "username" because that's what Django's auth
    # system (and AuthenticationForm) expects internally — but since every
    # account's username is auto-set to its email on signup, we only ever
    # want to show/label this as "Email" so it's not confused with the
    # person's first/last name.
    username = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email'}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Please enter a correct email and password. Note that both fields may be case-sensitive.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        # 'email' intentionally excluded: it was verified via OTP at signup,
        # so letting it be silently changed here would let someone redirect
        # password-reset/OTP emails to an address they don't actually own
        # without re-proving anything.
        fields = ['first_name', 'last_name', 'phone', 'address', 'barangay', 'city', 'province', 'zip_code', 'avatar']
        widgets = {
            'address': forms.TextInput(attrs={'placeholder': 'House #, Street'}),
            'avatar': forms.FileInput(),
            'province': forms.HiddenInput(),
            'city': forms.HiddenInput(),
            'barangay': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        validate_avatar_size(avatar)
        return avatar