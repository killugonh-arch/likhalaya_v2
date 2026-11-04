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

class StaffCreateForm(UserCreationForm):
    """Used by admins in the dashboard to create a Staff account directly
    (no email OTP step — the admin is vouching for this account)."""
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)
    phone = forms.CharField(max_length=20, required=False)

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})
        placeholders = {
            'username': 'Enter a username',
            'first_name': 'Enter first name',
            'last_name': 'Enter last name',
            'email': 'Enter email address',
            'phone': 'Enter phone number (optional)',
            'password1': 'Enter password',
            'password2': 'Confirm password',
        }
        for fname, text in placeholders.items():
            if fname in self.fields:
                self.fields[fname].widget.attrs['placeholder'] = text

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.all_objects.filter(username=username).exists():
            raise forms.ValidationError('A user with that username already exists.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.all_objects.filter(email=email).exists():
            raise forms.ValidationError('An account with that email already exists.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'staff'
        user.is_active = True
        if commit:
            user.save()
        return user


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

# ZIP codes for Leyte's cities/municipalities (PHLPost), keyed by a normalized name.
LEYTE_ZIPS = {
    'abuyog': '6510',
    'alangalang': '6517',
    'albuera': '6542',
    'babatngon': '6520',
    'barugo': '6519',
    'bato': '6525',
    'baybay': '6521',
    'burauen': '6516',
    'calubian': '6534',
    'capoocan': '6530',
    'carigara': '6529',
    'dagami': '6515',
    'dulag': '6505',
    'hilongos': '6524',
    'hindang': '6523',
    'inopacan': '6522',
    'isabel': '6539',
    'jaro': '6527',
    'javier': '6511',
    'julita': '6506',
    'kananga': '6531',
    'lapaz': '6508',
    'leyte': '6533',
    'macarthur': '6509',
    'mahaplag': '6512',
    'matagob': '6532',
    'matalom': '6526',
    'mayorga': '6507',
    'merida': '6540',
    'ormoc': '6541',
    'palo': '6501',
    'palompon': '6538',
    'pastrana': '6514',
    'sanisidro': '6535',
    'sanmiguel': '6518',
    'santafe': '6513',
    'tabango': '6536',
    'tabontabon': '6504',
    'tacloban': '6500',
    'tanauan': '6502',
    'tolosa': '6503',
    'tunga': '6528',
    'villaba': '6537',
}


def _norm_place(name):
    """'City of Ormoc' / 'Ormoc City' / 'Matag-ob' -> comparable key."""
    import re
    n = (name or '').strip().lower()
    n = re.sub(r'^(city of|municipality of)\s+', '', n)
    n = re.sub(r'\s+city$', '', n)
    return re.sub(r'[^a-z]', '', n)


def leyte_zip_for(city):
    """ZIP code for a Leyte city/municipality, or '' if unknown."""
    return LEYTE_ZIPS.get(_norm_place(city), '')


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
    def clean(self):
        cleaned = super().clean()
        # ZIP is derived from the chosen city, never typed by hand.
        zip_code = leyte_zip_for(cleaned.get('city'))
        if zip_code:
            cleaned['zip_code'] = zip_code
        return cleaned

    def clean_province(self):
        # Deliveries are limited to Leyte; the province can't be changed.
        return 'Leyte'
    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        validate_avatar_size(avatar)
        return avatar