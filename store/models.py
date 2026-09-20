import json
from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse
from accounts.models import CustomUser
from .fields import EncryptedTextField
from cloudinary_storage.storage import VideoMediaCloudinaryStorage


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_categories'
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']
        base_manager_name = 'all_objects'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('store:category', kwargs={'slug': self.slug})

    def archive(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])


class Product(models.Model):
    SIZE_SMALL = 'S'
    SIZE_MEDIUM = 'M'
    SIZE_LARGE = 'L'
    SIZE_CHOICES = [
        (SIZE_SMALL, 'Small'),
        (SIZE_MEDIUM, 'Medium'),
        (SIZE_LARGE, 'Large'),
    ]

    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    price_min = models.DecimalField(max_digits=10, decimal_places=2)
    price_medium = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    price_max = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    gcash_qr_code = models.ImageField(
        upload_to='products/gcash_qr/', blank=True, null=True,
        help_text="GCash QR code for this product. Set on creation; only an Admin can change it afterward."
    )
    is_active = models.BooleanField(default=True)
    artisan_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_products'
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['-created_at']
        base_manager_name = 'all_objects'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            n = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{n}"
                n += 1
            self.slug = slug
        if self.price_medium is None:
            if self.price_max and self.price_max > self.price_min:
                midpoint = (self.price_min + self.price_max) / 2
                self.price_medium = midpoint.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                self.price_medium = self.price_min
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('store:product_detail', kwargs={'slug': self.slug})

    def archive(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    @property
    def price_display(self):
        return f"₱{self.price_min:.0f}"

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def total_stock(self):
        if self.pk and self.has_variants:
            return sum(s.total_stock for s in self.sizes.filter(is_active=True))
        return self.stock

    def recalculate_stock(self):
        if not self.has_variants:
            return
        total = sum(s.total_stock for s in self.sizes.filter(is_active=True))
        if total != self.stock:
            self.stock = total
            self.save(update_fields=['stock'])

    @property
    def has_size_pricing(self):
        return bool(self.price_max and self.price_max > self.price_min)

    @property
    def price_small(self):
        return self.price_min

    @property
    def price_large(self):
        return self.price_max if self.price_max else self.price_min

    @property
    def images_by_size_json(self):
        data = {'general': [], 'S': [], 'M': [], 'L': []}
        if self.image:
            data['general'].append(self.image.url)
        for extra in self.extra_images.all():
            if extra.image:
                data['general'].append(extra.image.url)
        return json.dumps(data)

    @property
    def has_designs(self):
        if self.has_variants:
            return ProductDesign.objects.filter(
                product_size__product=self,
                product_size__is_active=True,
                is_active=True
            ).exists()
        return False

    @property
    def has_variants(self):
        if not self.pk:
            return False
        return self.sizes.filter(is_active=True).exists()

    @property
    def default_variant_image(self):
        if self.image:
            return self.image.url
        first_size = self.sizes.filter(is_active=True).order_by('order', 'id').first()
        if first_size:
            first_design = first_size.designs.filter(is_active=True).order_by('order', 'id').first()
            if first_design and first_design.image:
                return first_design.image.url
        return ''

    @property
    def variant_json(self):
        sizes = []
        for size in self.sizes.filter(is_active=True).order_by('order', 'id'):
            designs = []
            for d in size.designs.filter(is_active=True).order_by('order', 'id'):
                designs.append({
                    'id': d.id,
                    'title': d.title,
                    'image': d.image.url if d.image else '',
                    'stock': d.stock,
                })
            sizes.append({
                'id': size.id,
                'code': size.code,
                'name': size.get_name_display(),
                'price': str(self.get_price_for_size(size.code)),
                'designs': designs,
            })
        return json.dumps({'sizes': sizes, 'default_image': self.default_variant_image})

    def get_price_for_size(self, size):
        prices = {
            self.SIZE_SMALL: self.price_small,
            self.SIZE_MEDIUM: self.price_medium,
            self.SIZE_LARGE: self.price_large,
        }
        return prices.get((size or '').upper(), self.price_min)


class ProductImage(models.Model):
    SIZE_CHOICES = [
        ('', 'All sizes (general)'),
        (Product.SIZE_SMALL, 'Small'),
        (Product.SIZE_MEDIUM, 'Medium'),
        (Product.SIZE_LARGE, 'Large'),
    ]
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='extra_images')
    image = models.ImageField(upload_to='products/gallery/')
    caption = models.CharField(max_length=200, blank=True)
    size = models.CharField(
        max_length=1, choices=SIZE_CHOICES, blank=True,
        help_text="Leave blank to show for every size. Set to Small/Medium/Large to show only when that size is picked."
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        size_label = dict(self.SIZE_CHOICES).get(self.size, 'All sizes')
        return f"Image for {self.product.name} ({size_label})"


class ProductSize(models.Model):
    SIZE_CHOICES = Product.SIZE_CHOICES

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='sizes')
    name = models.CharField(max_length=1, choices=SIZE_CHOICES, help_text="Small, Medium, or Large")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.product.name} — {self.get_name_display()}"

    @property
    def code(self):
        return self.name

    @property
    def price(self):
        return self.product.get_price_for_size(self.name)

    @property
    def total_stock(self):
        return sum(d.stock for d in self.designs.filter(is_active=True))

    @property
    def in_stock(self):
        return self.total_stock > 0


class ProductDesign(models.Model):
    product_size = models.ForeignKey(ProductSize, on_delete=models.CASCADE, related_name='designs', null=True, blank=True)
    title = models.CharField(max_length=100, default='', blank=True, help_text="e.g. Ocean Blue")
    color = models.CharField(max_length=50, blank=True, default='', help_text="e.g. Blue")
    image = models.ImageField(upload_to='products/designs/', blank=True, null=True)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.product_size} — {self.title}"

    @property
    def product(self):
        return self.product_size.product

    @property
    def name(self):
        return self.title

    @property
    def in_stock(self):
        return self.stock > 0

    def stock_for_size(self, size=None):
        return self.stock

    def deduct_stock(self, qty):
        self.stock = max(0, self.stock - qty)
        self.save(update_fields=['stock'])
        self.product.recalculate_stock()

    def restock(self, qty):
        self.stock = self.stock + qty
        self.save(update_fields=['stock'])
        self.product.recalculate_stock()

    @property
    def image_url(self):
        return self.image.url if self.image else ''


class Personnel(models.Model):
    BADGE_CHOICES = [
        ('Command', 'Command'),
        ('Administration', 'Administration'),
        ('Operations', 'Operations'),
        ('Livelihood', 'Livelihood'),
        ('Programs', 'Programs'),
        ('Security', 'Security'),
    ]
    rank = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    title = models.CharField(max_length=200)
    department_badge = models.CharField(max_length=50, choices=BADGE_CHOICES, default='Command')
    emoji = models.CharField(max_length=10, default='👮')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name_plural = 'Personnel'

    def __str__(self):
        return f"{self.rank} {self.name}"


class ContactMessage(models.Model):
    INQUIRY_GENERAL = 'general'
    INQUIRY_PRODUCT_INQUIRY = 'product_inquiry'
    INQUIRY_PRODUCT_REQUEST = 'product_request'
    INQUIRY_CUSTOM_ORDER = 'custom_order'
    INQUIRY_BULK_ORDER = 'bulk_order'
    INQUIRY_DONATE_MATERIALS = 'donate_materials'
    INQUIRY_PARTNERSHIP = 'partnership'
    INQUIRY_FEEDBACK = 'feedback'
    INQUIRY_OTHER = 'other'

    INQUIRY_CHOICES = [
        (INQUIRY_GENERAL, 'General Inquiry'),
        (INQUIRY_PRODUCT_INQUIRY, 'Product Inquiry'),
        (INQUIRY_PRODUCT_REQUEST, 'Product Request'),
        (INQUIRY_CUSTOM_ORDER, 'Custom Order Request'),
        (INQUIRY_BULK_ORDER, 'Bulk / Wholesale Order'),
        (INQUIRY_DONATE_MATERIALS, 'Donation of Raw Materials'),
        (INQUIRY_PARTNERSHIP, 'Partnership or Collaboration'),
        (INQUIRY_FEEDBACK, 'Feedback or Suggestions'),
        (INQUIRY_OTHER, 'Other Concerns'),
    ]

    MATERIALS_NEW = 'new'
    MATERIALS_GOOD = 'good'
    MATERIALS_USED_USABLE = 'used_usable'
    MATERIALS_NEEDS_CLEANING = 'needs_cleaning'
    MATERIALS_OTHER = 'other'
    MATERIALS_CONDITION_CHOICES = [
        (MATERIALS_NEW, 'New'),
        (MATERIALS_GOOD, 'Good Condition'),
        (MATERIALS_USED_USABLE, 'Used but Usable'),
        (MATERIALS_NEEDS_CLEANING, 'Needs Cleaning'),
        (MATERIALS_OTHER, 'Other'),
    ]

    PARTNERSHIP_TYPE_CHOICES = [
        ('organization', 'Organization Partnership'),
        ('community', 'Community Partnership'),
        ('educational', 'Educational Partnership'),
        ('business', 'Business Partnership'),
        ('event_program', 'Event / Program Collaboration'),
        ('donation', 'Donation Partnership'),
        ('other', 'Other'),
    ]

    FEEDBACK_TYPE_CHOICES = [
        ('product_feedback', 'Product Feedback'),
        ('website_feedback', 'Website Feedback'),
        ('service_feedback', 'Service Feedback'),
        ('suggestion', 'Suggestion'),
        ('positive_feedback', 'Positive Feedback'),
        ('other', 'Other'),
    ]

    CONCERN_TYPE_CHOICES = [
        ('order_concern', 'Order Concern'),
        ('payment_concern', 'Payment Concern'),
        ('delivery_concern', 'Delivery Concern'),
        ('product_concern', 'Product Concern'),
        ('account_concern', 'Account Concern'),
        ('website_problem', 'Website Problem'),
        ('other', 'Other'),
    ]

    STATUS_NEW = 'new'
    STATUS_UNDER_REVIEW = 'under_review'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_RESOLVED = 'resolved'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_NEW, 'New'),
        (STATUS_UNDER_REVIEW, 'Under Review'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_CLOSED, 'Closed'),
    ]

    inquiry_type = models.CharField(max_length=30, choices=INQUIRY_CHOICES, default=INQUIRY_GENERAL)
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=200)
    message = EncryptedTextField()

    customer = models.ForeignKey(
        CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='contact_messages'
    )

    product = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.SET_NULL, related_name='contact_messages',
        help_text="Auto-populated when the request is opened from a product page."
    )

    order = models.ForeignKey(
        'orders.Order', null=True, blank=True, on_delete=models.SET_NULL, related_name='contact_messages'
    )
    order_number_ref = models.CharField(max_length=30, blank=True)

    item_name = models.CharField(max_length=200, blank=True)
    quantity = models.CharField(max_length=100, blank=True)

    customization_request = models.TextField(blank=True)
    preferred_materials = models.CharField(max_length=200, blank=True)
    target_budget = models.CharField(max_length=100, blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    reference_image = models.ImageField(upload_to='contact_references/%Y/%m/', blank=True, null=True)

    organization_name = models.CharField(max_length=200, blank=True)

    materials_condition = models.CharField(max_length=30, choices=MATERIALS_CONDITION_CHOICES, blank=True)

    partnership_type = models.CharField(max_length=30, choices=PARTNERSHIP_TYPE_CHOICES, blank=True)
    partnership_details = models.TextField(blank=True)

    feedback_type = models.CharField(max_length=30, choices=FEEDBACK_TYPE_CHOICES, blank=True)
    related_product = models.CharField(max_length=200, blank=True)

    concern_type = models.CharField(max_length=30, choices=CONCERN_TYPE_CHOICES, blank=True)

    additional_details = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    staff_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_messages'
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['-created_at']
        base_manager_name = 'all_objects'

    def __str__(self):
        return f"{self.subject} - {self.name}"

    def archive(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    @property
    def has_unread_for_customer(self):
        return self.replies.filter(is_staff_reply=True, is_read_by_customer=False).exists()

    @property
    def has_unread_for_staff(self):
        return self.replies.filter(is_staff_reply=False, is_read_by_staff=False).exists()


class MessageReply(models.Model):
    thread = models.ForeignKey(ContactMessage, on_delete=models.CASCADE, related_name='replies')
    staff = models.ForeignKey(
        CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    is_staff_reply = models.BooleanField(default=False)
    body = EncryptedTextField()
    is_read_by_customer = models.BooleanField(default=False)
    is_read_by_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        who = f"staff:{self.staff}" if self.is_staff_reply else "customer"
        return f"Reply on #{self.thread_id} by {who}"


class LivelihoodVideo(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    video_url = models.URLField(blank=True, help_text="YouTube or Facebook video link")
    video_file = models.FileField(
        upload_to='livelihood_videos/',
        storage=VideoMediaCloudinaryStorage(),  # uploads as video resource to cloudinary
        blank=True,
        null=True,
        help_text="Use this only if you don't have a link above"
    )
    thumbnail = models.ImageField(upload_to='livelihood_thumbs/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    show_on_home = models.BooleanField(
        default=False,
        help_text="Feature this video on the Home page (max 2 shown there). "
                  "The About page always shows every active video."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_videos'
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['order', '-created_at']
        base_manager_name = 'all_objects'

    def __str__(self):
        return self.title

    def archive(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    @property
    def embed_url(self):
        url = self.video_url or ''
        if 'youtu.be/' in url:
            vid = url.split('youtu.be/')[-1].split('?')[0]
            return (f'https://www.youtube.com/embed/{vid}'
                     f'?autoplay=1&mute=1&loop=1&playlist={vid}&controls=0&playsinline=1&rel=0')
        if 'watch?v=' in url:
            vid = url.split('watch?v=')[-1].split('&')[0]
            return (f'https://www.youtube.com/embed/{vid}'
                     f'?autoplay=1&mute=1&loop=1&playlist={vid}&controls=0&playsinline=1&rel=0')
        if 'facebook.com' in url:
            from urllib.parse import quote
            return (f'https://www.facebook.com/plugins/video.php?href={quote(url, safe="")}'
                     f'&show_text=false&autoplay=true&mute=1&loop=true')
        return url