from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.utils.safestring import mark_safe
from .models import Product, Category, ContactMessage, LivelihoodVideo, ProductImage, ProductDesign, ProductSize


class ProductImageWidget(forms.ClearableFileInput):
    """A cleaner image upload widget: drag-and-drop style, live preview,
    no 'Clear' checkbox — uploading a new file simply replaces the old one."""
    template_name = None  # we render manually below

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        input_id = attrs.get('id', f'id_{name}')
        has_image = bool(value and hasattr(value, 'url'))
        image_url = value.url if has_image else ''

        return mark_safe(f"""
<div class="product-image-upload" id="wrap_{input_id}">
  <label for="{input_id}" class="image-dropzone{' has-image' if has_image else ''}" id="dropzone_{input_id}">
    <img src="{image_url}" alt="" class="image-dropzone-preview" id="preview_{input_id}" style="{'' if has_image else 'display:none;'}">
    <div class="image-dropzone-placeholder" id="placeholder_{input_id}" style="{'display:none;' if has_image else ''}">
      <i class="fas fa-cloud-upload-alt"></i>
      <div class="fw-semibold small mt-2">Click to upload or drag and drop</div>
      <div class="text-muted" style="font-size:11px;">JPG, PNG, WebP — Max 5MB</div>
    </div>
    <div class="image-dropzone-overlay">
      <i class="fas fa-camera me-1"></i>Change Photo
    </div>
  </label>
  <input type="file" name="{name}" id="{input_id}" class="d-none" accept="image/*"
         onchange="likhalayaPreviewImage(this, '{input_id}')">
</div>
<script>
if (typeof likhalayaPreviewImage !== 'function') {{
  function likhalayaPreviewImage(input, id) {{
    const preview = document.getElementById('preview_' + id);
    const placeholder = document.getElementById('placeholder_' + id);
    const dropzone = document.getElementById('dropzone_' + id);
    if (input.files && input.files[0]) {{
      const reader = new FileReader();
      reader.onload = e => {{
        preview.src = e.target.result;
        preview.style.display = 'block';
        placeholder.style.display = 'none';
        dropzone.classList.add('has-image');
      }};
      reader.readAsDataURL(input.files[0]);
    }}
  }}
}}
</script>
""")

    def value_omitted_from_data(self, data, files, name):
        return name not in files


class ProductSearchForm(forms.Form):
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'form-control', 'placeholder': 'Search products…'
    }))
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False, empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    sort = forms.ChoiceField(choices=[
        ('newest', 'Newest First'),
        ('price_asc', 'Price: Low to High'),
        ('price_desc', 'Price: High to Low'),
        ('name', 'Name A-Z'),
    ], required=False, widget=forms.Select(attrs={'class': 'form-select'}))

class ContactForm(forms.ModelForm):
    """Smart inquiry form for the Contact page. All fields are declared here;
    which ones are shown/required for a given inquiry type is driven client-side
    by JS (data-show-for attributes in the template) and re-checked server-side
    in clean() below so a bypassed/JS-less submission still gets validated.

    The visible UI is simplified into 5 top-level categories (General Inquiry,
    Product & Custom Orders, Bulk Orders, Partnerships & Donations, Feedback),
    each showing only the handful of fields it actually needs. The underlying
    inquiry_type values and model fields are unchanged so nothing already
    stored, reported on, or relied on server-side is removed."""

    class Meta:
        model = ContactMessage
        fields = [
            'inquiry_type', 'name', 'email', 'phone', 'location', 'subject', 'message',
            'product', 'order_number_ref',
            'item_name', 'quantity', 'customization_request', 'preferred_materials',
            'target_budget', 'preferred_date', 'reference_image', 'organization_name',
            'materials_condition', 'partnership_type', 'partnership_details', 'feedback_type',
            'related_product', 'concern_type', 'additional_details',
        ]
        widgets = {
            'inquiry_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_inquiry_type'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '', 'readonly': True}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': '', 'readonly': True}),
            # phone / location are optional and editable by default. They only
            # become read-only when the customer already has them saved in
            # their profile (see __init__ below).
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City / Barangay / Province'}),
            # Subject is still auto-filled from the selected category (see
            # contact.html JS) but is no longer shown as a field the customer
            # has to look at/edit — it's a hidden input now.
            'subject': forms.HiddenInput(),
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Tell us more…'}),
            'product': forms.HiddenInput(),
            'order_number_ref': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. LKL-00042'}),
            'item_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Woven Rattan Bag'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 2', 'min': '1', 'step': '1'}),
            'customization_request': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'Please describe your preferred size, color, material, design, engraving, or other customization…',
            }),
            'preferred_materials': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Natural abaca fiber, navy blue'}),
            'target_budget': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional — e.g. ₱1,500'}),
            'preferred_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reference_image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/jpeg,image/jpg,image/png,image/webp'}),
            'organization_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company / Organization name'}),
            'materials_condition': forms.Select(attrs={'class': 'form-select'}),
            'partnership_type': forms.Select(attrs={'class': 'form-select'}),
            'partnership_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Describe your proposed partnership…'}),
            'feedback_type': forms.Select(attrs={'class': 'form-select'}),
            'related_product': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional — product name or link'}),
            'concern_type': forms.Select(attrs={'class': 'form-select'}),
            'additional_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Anything else we should know?'}),
        }

    # Fields that are never required by Django's default field definition,
    # since which ones apply depends on the selected inquiry_type. `message`
    # is included because the simplified UI only shows a generic Message box
    # for categories that don't already have their own dedicated details
    # field (see clean() below, which backfills it for the others).
    OPTIONAL_FIELDS = [
        'phone', 'location', 'product', 'order_number_ref', 'item_name', 'quantity', 'customization_request',
        'preferred_materials', 'target_budget', 'preferred_date', 'reference_image', 'organization_name',
        'materials_condition', 'partnership_type', 'partnership_details', 'feedback_type', 'related_product',
        'concern_type', 'additional_details', 'message',
    ]

    # Fields that must be a positive whole number when required for a given type.
    QUANTITY_REQUIRED_TYPES = {
        ContactMessage.INQUIRY_PRODUCT_REQUEST,
        ContactMessage.INQUIRY_CUSTOM_ORDER,
        ContactMessage.INQUIRY_BULK_ORDER,
        ContactMessage.INQUIRY_DONATE_MATERIALS,
    }

    # inquiry_type -> list of field names that become required for that type.
    # Reflects the simplified, 5-category contact form:
    #   General Inquiry            -> general
    #   Product & Custom Orders    -> custom_order (merges the old Product
    #                                 Inquiry / Product Request / Custom Order)
    #   Bulk Orders                -> bulk_order
    #   Partnerships & Donations   -> partnership / donate_materials (sub-choice)
    #   Feedback                   -> feedback
    # product_inquiry / product_request / other are kept for backward
    # compatibility (existing records, direct API/admin use) but no longer
    # have a top-level card of their own.
    REQUIRED_BY_TYPE = {
        ContactMessage.INQUIRY_GENERAL: ['message'],
        ContactMessage.INQUIRY_PRODUCT_REQUEST: ['item_name', 'quantity'],
        ContactMessage.INQUIRY_CUSTOM_ORDER: ['item_name', 'quantity', 'customization_request'],
        ContactMessage.INQUIRY_BULK_ORDER: ['item_name', 'quantity'],
        ContactMessage.INQUIRY_DONATE_MATERIALS: ['item_name', 'quantity', 'materials_condition', 'message'],
        ContactMessage.INQUIRY_PARTNERSHIP: ['organization_name', 'partnership_type', 'partnership_details'],
        ContactMessage.INQUIRY_FEEDBACK: ['feedback_type', 'message'],
        ContactMessage.INQUIRY_OTHER: ['concern_type'],
    }

    @staticmethod
    def profile_location(user):
        """Location string built from the customer's saved profile address."""
        parts = [
            getattr(user, 'address', ''),
            getattr(user, 'barangay', ''),
            getattr(user, 'city', ''),
            getattr(user, 'province', ''),
            getattr(user, 'zip_code', ''),
        ]
        return ', '.join(p.strip() for p in parts if p and p.strip())

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.OPTIONAL_FIELDS:
            self.fields[name].required = False

        # Contact number / location: if the profile already has them, show
        # them locked (read-only). If not, the customer can leave them blank
        # or type them in for this message.
        self._profile_phone = (getattr(user, 'phone', '') or '').strip() if user else ''
        self._profile_location = self.profile_location(user) if user else ''
        self.phone_locked = bool(self._profile_phone)
        self.location_locked = bool(self._profile_location)
        if self.phone_locked:
            self.fields['phone'].widget.attrs['readonly'] = True
            self.fields['phone'].widget.attrs['placeholder'] = ''
        if self.location_locked:
            self.fields['location'].widget.attrs['readonly'] = True
        self.fields['inquiry_type'].required = True
        self.fields['materials_condition'].choices = [('', 'Select condition')] + list(ContactMessage.MATERIALS_CONDITION_CHOICES)
        self.fields['partnership_type'].choices = [('', 'Select type')] + list(ContactMessage.PARTNERSHIP_TYPE_CHOICES)
        self.fields['feedback_type'].choices = [('', 'Select feedback type')] + list(ContactMessage.FEEDBACK_TYPE_CHOICES)
        self.fields['concern_type'].choices = [('', 'Select concern type')] + list(ContactMessage.CONCERN_TYPE_CHOICES)

    def clean_phone(self):
        # Locked -> always the profile value, whatever the POST body says.
        if self.phone_locked:
            return self._profile_phone
        return (self.cleaned_data.get('phone') or '').strip()

    def clean_location(self):
        if self.location_locked:
            return self._profile_location
        return (self.cleaned_data.get('location') or '').strip()

    def clean_quantity(self):
        raw = (self.data.get('quantity') or '').strip()
        if not raw:
            return ''
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise forms.ValidationError('Quantity must be a whole number.')
        if value <= 0:
            raise forms.ValidationError('Quantity must be greater than zero.')
        if value > 100000:
            raise forms.ValidationError('Quantity is too large. Please contact us directly for orders this size.')
        return str(value)

    def clean_reference_image(self):
        image = self.cleaned_data.get('reference_image')
        if not image:
            return image
        # Only proceed with real, uploaded files (skip already-saved instance values).
        content_type = getattr(image, 'content_type', None)
        if content_type is not None:
            allowed_types = {'image/jpeg', 'image/jpg', 'image/png', 'image/webp'}
            if content_type not in allowed_types:
                raise forms.ValidationError('Reference image must be a JPG, PNG, or WEBP file.')
            max_size = 5 * 1024 * 1024  # 5 MB
            if image.size > max_size:
                raise forms.ValidationError('Reference image must be smaller than 5MB.')
            # Verify the file is actually a valid image, not just a renamed/spoofed file.
            try:
                from PIL import Image
                image.seek(0)
                Image.open(image).verify()
                image.seek(0)
            except Exception:
                raise forms.ValidationError('The uploaded file is not a valid image.')
        return image

    def clean(self):
        cleaned = super().clean()
        inquiry_type = cleaned.get('inquiry_type')
        for field_name in self.REQUIRED_BY_TYPE.get(inquiry_type, []):
            if not cleaned.get(field_name):
                self.add_error(field_name, 'This field is required for this inquiry type.')

        # The simplified form only shows a generic "Message" box for
        # categories that don't already have their own dedicated details
        # field. For the others, mirror that field's content into `message`
        # so the dashboard message list/detail views still have a body to
        # display, without asking the customer to type the same thing twice.
        if not cleaned.get('message'):
            fallback_field = {
                ContactMessage.INQUIRY_CUSTOM_ORDER: 'customization_request',
                ContactMessage.INQUIRY_BULK_ORDER: 'additional_details',
                ContactMessage.INQUIRY_PARTNERSHIP: 'partnership_details',
            }.get(inquiry_type)
            if fallback_field and cleaned.get(fallback_field):
                cleaned['message'] = cleaned[fallback_field]
        return cleaned


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        # NOTE: 'stock' is intentionally NOT a form field. Total stock is
        # always calculated automatically from each design's own quantity
        # (see Product.total_stock / Product.recalculate_stock) — the admin
        # can never type a product-level stock number directly.
        fields = ['name', 'category', 'description', 'price_min', 'price_medium', 'price_max',
                  'image', 'gcash_qr_code', 'is_active']
        labels = {
            'price_min': 'Small Price',
            'price_medium': 'Medium Price',
            'price_max': 'Large Price',
            'gcash_qr_code': 'GCash QR Code',
        }
        widgets = {
            'description': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'Describe the product...\n• Materials used\n• Size\n• Production time\n• Other details'
            }),
            'price_min': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Small (lowest price)'}),
            'price_medium': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Medium (optional)'}),
            'price_max': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Large (optional)'}),
            'image': ProductImageWidget(),
            'gcash_qr_code': ProductImageWidget(),
        }

    def __init__(self, *args, **kwargs):
        # `user` is passed in from the dashboard views so this form can enforce,
        # server-side, who is allowed to touch the GCash QR code field. This is
        # the actual security boundary — removing the field from self.fields
        # means it is dropped from cleaned_data and never reaches .save(),
        # regardless of what a crafted POST body contains.
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        editing_existing = bool(self.instance and self.instance.pk)
        is_admin = bool(self.user and self.user.is_admin_user())
        if editing_existing and not is_admin:
            self.fields.pop('gcash_qr_code', None)

        self.fields['price_medium'].required = False
        self.fields['price_medium'].help_text = (
            "Leave blank to auto-set as the midpoint between Small and Large."
        )
        self.fields['price_max'].required = False
        self.fields['price_max'].help_text = (
            "Leave blank to sell at a single price. "
            "If set, buyers choose Small (lowest), Medium (middle) or Large (highest)."
        )
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.NumberInput,
                                         forms.EmailInput, forms.Textarea, forms.Select)):
                field.widget.attrs.update({'class': 'form-control'})
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input', 'role': 'switch'})
            elif isinstance(field.widget, forms.ClearableFileInput):
                field.widget.attrs.update({'class': 'form-control'})


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ['image', 'caption', 'order']
        widgets = {
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'caption': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Caption (optional)'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'style': 'display:none;'}),
        }


class BaseProductImageFormSet(BaseInlineFormSet):
    """Enforces a max of 3 extra product photos — server-side backstop for
    the same cap the dashboard JS enforces live."""
    MAX_IMAGES = 3

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        count = 0
        for form in self.forms:
            cleaned = getattr(form, 'cleaned_data', None)
            if not cleaned or cleaned.get('DELETE'):
                continue
            # Skip untouched blank extra rows (no new image, no existing instance)
            if not cleaned.get('image') and not form.instance.pk:
                continue
            count += 1
        if count > self.MAX_IMAGES:
            raise forms.ValidationError(f'You can only add up to {self.MAX_IMAGES} photos.')


ProductImageFormSet = inlineformset_factory(
    Product, ProductImage,
    form=ProductImageForm,
    formset=BaseProductImageFormSet,
    extra=3,
    max_num=3,
    validate_max=True,
    can_delete=True,
)


class ProductSizeForm(forms.ModelForm):
    class Meta:
        model = ProductSize
        fields = ['name', 'is_active', 'order']
        widgets = {
            'name': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'style': 'display:none;'}),
        }


ProductSizeFormSet = inlineformset_factory(
    Product, ProductSize,
    form=ProductSizeForm,
    extra=1,
    can_delete=True,
)


class ProductDesignForm(forms.ModelForm):
    """A design is a photo + title, plus its OWN stock quantity. Each
    design's quantity is entered here directly and is the single source of
    truth for that design's availability — the product's overall stock is
    always just the sum of these (see Product.recalculate_stock)."""
    class Meta:
        model = ProductDesign
        fields = ['image', 'title', 'is_active', 'order', 'stock']
        labels = {'stock': 'Quantity'}
        widgets = {
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Ocean Blue'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'style': 'display:none;'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1', 'placeholder': '0'}),
        }


# Used per-ProductSize instance in the dashboard product form view, e.g.:
#   ProductDesignFormSet(instance=some_product_size, prefix=f'size-{some_product_size.pk}-design')
ProductDesignFormSet = inlineformset_factory(
    ProductSize, ProductDesign,
    form=ProductDesignForm,
    extra=1,
    can_delete=True,
)


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 100, 'placeholder': 'e.g. Embroidery'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'maxlength': 500, 'placeholder': "Short description shown to customers browsing this category..."}),
        }


class LivelihoodVideoForm(forms.ModelForm):
    class Meta:
        model = LivelihoodVideo
        fields = ['title', 'description', 'video_url', 'video_file', 'thumbnail', 'order', 'is_active', 'show_on_home']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Livelihood Skills Training'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Short description of this program...'}),
            'video_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.youtube.com/watch?v=...'}),
            'video_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'thumbnail': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['video_url'].required = False
        self.fields['video_file'].required = False
        self.fields['thumbnail'].required = False
        self.fields['is_active'].widget.attrs.update({'class': 'form-check-input', 'role': 'switch'})
        self.fields['show_on_home'].widget.attrs.update({'class': 'form-check-input', 'role': 'switch'})

    def clean_show_on_home(self):
        show_on_home = self.cleaned_data.get('show_on_home')
        if show_on_home:
            qs = LivelihoodVideo.objects.filter(show_on_home=True)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.count() >= 2:
                raise forms.ValidationError(
                    'Only 2 videos can be featured on the Home page at a time. '
                    'Turn off "Show on Home" on another video first.'
                )
        return show_on_home