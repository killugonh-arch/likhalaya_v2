from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from .forms import RegisterForm, LoginForm, ProfileUpdateForm, OTPVerifyForm, NoReuseSetPasswordForm, NoReusePasswordChangeForm
from .models import CustomUser, EmailOTP
from likhalaya_project.rate_limit import get_client_ip, check_hourly_limit

# Minimum time a user must wait between "Resend Code" clicks. Without this,
# resend is an email-bombing vector: anyone can register using someone
# else's email address, then hammer resend to flood that inbox — each
# resend also does a real synchronous SMTP send, which blocks the request.
OTP_RESEND_COOLDOWN_SECONDS = 30

# Two separate login guards (kept deliberately simple):
#
#   1. ONE account, many tries  -> django-axes (see AXES_* in settings.py):
#      5 failed tries on the same account from the same IP locks it.
#   2. MANY accounts, one IP    -> below: the cache tracks per-IP how many
#      times each account has failed. The first account gets 5 tries before
#      it counts toward the IP block; every subsequent account gets 3 tries.
#      Once 3 DIFFERENT accounts have each crossed their threshold, that IP
#      is blocked for the rest of the hour.
#
# This means your scenario works exactly as expected:
#   - 5 wrong on account A  → A is axes-locked AND A now counts (5 >= 5)
#   - 3 wrong on account B  → B now counts (3 >= 3, not the first account)
#   - 3 wrong on account C  → C now counts → IP blocked (3 accounts hit)
#
# Register: 5/hr per IP is generous for normal use (most real users register
# once) while making account-farm automation impractical.
LOGIN_MAX_FAILED_ACCOUNTS = 3       # distinct accounts needed to block an IP
LOGIN_FAILED_ACCOUNTS_WINDOW = 60 * 60   # seconds
LOGIN_FIRST_ACCOUNT_THRESHOLD = 5   # tries before the 1st account "counts"
LOGIN_OTHER_ACCOUNT_THRESHOLD = 3   # tries before each later account "counts"
REGISTER_MAX_PER_HOUR = 5


def _otp_resend_cooldown_remaining(user):
    """Seconds left before `user` may request another OTP resend, or 0 if
    they're clear to send. Based on the most recently issued OTP, used or not."""
    last_otp = EmailOTP.objects.filter(user=user).order_by('-created_at').first()
    if not last_otp:
        return 0
    elapsed = (timezone.now() - last_otp.created_at).total_seconds()
    remaining = OTP_RESEND_COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining) + (1 if remaining % 1 else 0))


def _send_otp_email(user, otp):
    subject = 'One more step to confirm your account'
    context = {
        'first_name': user.first_name or user.username,
        'full_name': (f"{user.first_name} {user.last_name}".strip() or user.username),
        'code': otp.code,
        'valid_minutes': EmailOTP.OTP_VALID_MINUTES,
    }
    html_body = render_to_string('accounts/emails/otp_email.html', context)
    text_body = strip_tags(html_body)

    email = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [user.email])
    email.attach_alternative(html_body, 'text/html')
    email.send(fail_silently=False)


def register_view(request):
    if request.user.is_authenticated:
        return redirect('store:home')
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if request.method == 'POST':
        # Honeypot — see login_view for why this fakes a normal reload
        # instead of returning any error.
        if request.POST.get('website'):
            form = RegisterForm()
            return render(request, 'accounts/register.html', {'form': form, 'next': next_url})

        # Per-IP registration rate limit: 5 new accounts per IP per hour.
        # Stops automated account-farm scripts. Real users register once.
        ip = get_client_ip(request)
        if not check_hourly_limit(f'register_ip:{ip}', REGISTER_MAX_PER_HOUR):
            messages.error(
                request,
                'Too many registration attempts from your connection. Please try again in an hour.'
            )
            form = RegisterForm()
            return render(request, 'accounts/register.html', {'form': form, 'next': next_url})

        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # locked out until the emailed code is confirmed
            user.save()
            otp = EmailOTP.generate_for_user(user)
            try:
                _send_otp_email(user, otp)
            except Exception:
                messages.error(request, "We couldn't send the verification email. Please try again or contact support.")
                user.delete()
                return render(request, 'accounts/register.html', {'form': form, 'next': next_url})
            request.session['pending_verification_user_id'] = user.id
            request.session['pending_verification_next'] = next_url
            messages.info(request, f"We sent a 6-digit code to {user.email}. Enter it below to finish creating your account.")
            return redirect('accounts:verify_email')
    else:
        form = RegisterForm()
    return render(request, 'accounts/register.html', {'form': form, 'next': next_url})


def verify_email_view(request):
    if request.user.is_authenticated:
        return redirect('store:home')
    user_id = request.session.get('pending_verification_user_id')
    if not user_id:
        messages.error(request, 'Nothing to verify. Please register first.')
        return redirect('accounts:register')
    user = get_object_or_404(CustomUser.all_objects, id=user_id, is_active=False)
    next_url = request.session.get('pending_verification_next', '')

    if request.method == 'POST':
        if 'cancel' in request.POST:
            del request.session['pending_verification_user_id']
            request.session.pop('pending_verification_next', None)
            user.delete()
            messages.info(request, 'Signup cancelled. You can register again with different details.')
            return redirect('accounts:register')

        if 'resend' in request.POST:
            cooldown_remaining = _otp_resend_cooldown_remaining(user)
            if cooldown_remaining > 0:
                messages.error(request, f'Please wait {cooldown_remaining}s before requesting another code.')
                return redirect('accounts:verify_email')
            otp = EmailOTP.generate_for_user(user)
            try:
                _send_otp_email(user, otp)
                messages.success(request, f'A new code was sent to {user.email}.')
            except Exception:
                messages.error(request, "Couldn't resend the email. Please try again shortly.")
            return redirect('accounts:verify_email')

        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            otp = EmailOTP.objects.filter(user=user, is_used=False).order_by('-created_at').first()
            if not otp or not otp.is_valid():
                messages.error(request, 'That code has expired or is no longer valid. Please request a new one.')
            elif otp.code != code:
                otp.attempts += 1
                otp.save(update_fields=['attempts'])
                messages.error(request, 'Incorrect code. Please check your email and try again.')
            else:
                otp.is_used = True
                otp.save(update_fields=['is_used'])
                user.is_active = True
                user.save(update_fields=['is_active'])
                login(request, user, backend='accounts.backends.UsernameOrEmailBackend')
                del request.session['pending_verification_user_id']
                request.session.pop('pending_verification_next', None)
                messages.success(request, f'Welcome to Likhalaya, {user.first_name or user.username}! Your email is verified.')
                if next_url and url_has_allowed_host_and_scheme(
                    url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
                ):
                    return redirect(next_url)
                return redirect('store:home')
    else:
        form = OTPVerifyForm()
    return render(request, 'accounts/verify_email.html', {
        'form': form,
        'email': user.email,
        'resend_cooldown_remaining': _otp_resend_cooldown_remaining(user),
    })


# ── Guard 2 helpers ──────────────────────────────────────────────────────────
#
# Cache structure for a given IP:
#   login_failed_accounts:<ip>  →  {"alice@x": 3, "bob@x": 1, ...}
#
# A dict of {normalised_username: fail_count} lets us give the first
# account 5 tries and all later accounts 3 tries before each one
# "counts" toward the IP block.

def _get_fail_counts(ip):
    """Return the {account: fail_count} dict for this IP, or {}."""
    return cache.get(f'login_failed_accounts:{ip}', {})


def _set_fail_counts(ip, counts):
    cache.set(f'login_failed_accounts:{ip}', counts, LOGIN_FAILED_ACCOUNTS_WINDOW)


def _accounts_over_threshold(counts):
    """Return the list of accounts that have crossed their per-account
    threshold and therefore count toward the IP block.

    The first account to appear in the dict gets LOGIN_FIRST_ACCOUNT_THRESHOLD
    tries; every account after the first gets LOGIN_OTHER_ACCOUNT_THRESHOLD.
    'First' is determined by insertion order (Python 3.7+ dict guarantee).
    """
    over = []
    for i, (account, fails) in enumerate(counts.items()):
        threshold = (
            LOGIN_FIRST_ACCOUNT_THRESHOLD if i == 0
            else LOGIN_OTHER_ACCOUNT_THRESHOLD
        )
        if fails >= threshold:
            over.append(account)
    return over


def _ip_is_blocked(counts):
    return len(_accounts_over_threshold(counts)) >= LOGIN_MAX_FAILED_ACCOUNTS
# ─────────────────────────────────────────────────────────────────────────────


def login_view(request):
    if request.user.is_authenticated:
        return redirect('store:home')
    if request.method == 'POST':
        # Honeypot: a real person never sees or fills this field. A bot that
        # blindly fills every input will trip it. Pretend the login page
        # just reloaded normally — no error, no hint that anything was
        # detected — instead of giving the bot useful feedback to adapt to.
        if request.POST.get('website'):
            form = LoginForm()
            return render(request, 'accounts/login.html', {'form': form})

        ip = get_client_ip(request)
        fail_counts = _get_fail_counts(ip)
        blocked_msg = (
            'Too many failed sign-ins for different accounts from your '
            'connection. Please wait an hour and try again.'
        )

        # Guard 2 pre-check: if this IP already has 3 accounts over their
        # threshold, refuse even before we look at the password.
        if _ip_is_blocked(fail_counts):
            messages.error(request, blocked_msg)
            return render(request, 'accounts/login.html', {'form': LoginForm()})

        # Guard 1 (one account, many tries) is django-axes' job. After
        # AXES_FAILURE_LIMIT failures for the same account from the same IP,
        # Axes refuses to authenticate (even with the right password) and
        # AxesMiddleware swaps this response for accounts/locked.html
        # (HTTP 429) until AXES_COOLOFF_TIME passes.
        attempted = request.POST.get('username', '').strip().lower()[:254]
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            # Successful login: clear this account's failure count from the
            # IP dict so a typo followed by the right password isn't held
            # against future attempts.
            if attempted in fail_counts:
                del fail_counts[attempted]
                _set_fail_counts(ip, fail_counts)
            login(request, user)
            # Explicitly reset axes failure records for this username+IP.
            # AXES_RESET_ON_SUCCESS=True should handle this but calling it
            # directly ensures the DB record is cleared even on older versions.
            from axes.utils import reset as axes_reset_user
            axes_reset_user(username=attempted)
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(
                url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            if user.is_staff_user():
                return redirect('dashboard:home')
            if user.is_courier_user():
                return redirect('dashboard:courier_order_list')
            return redirect('store:home')
        elif attempted:
            # Failed login: increment this account's counter in the IP dict.
            fail_counts[attempted] = fail_counts.get(attempted, 0) + 1
            _set_fail_counts(ip, fail_counts)
            # Show the block immediately on the attempt that tips us over.
            if _ip_is_blocked(fail_counts):
                messages.error(request, blocked_msg)
                return render(request, 'accounts/login.html', {'form': LoginForm()})
    else:
        form = LoginForm()
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('store:home')


@login_required
def profile_view(request):
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if next_url and not url_has_allowed_host_and_scheme(
        url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ''
    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            if next_url:
                return redirect(next_url)
            return redirect('accounts:profile')
    else:
        form = ProfileUpdateForm(instance=request.user)
    from orders.models import Order
    recent_orders = Order.objects.filter(user=request.user).prefetch_related('items')[:5]
    needs_contact_info = not request.user.phone or not request.user.address or not request.user.city or not request.user.province
    force_edit = request.GET.get('edit') == '1'
    show_edit = needs_contact_info or bool(next_url) or force_edit
    return render(request, 'accounts/profile.html', {
        'form': form,
        'recent_orders': recent_orders,
        'next': next_url,
        'needs_contact_info': needs_contact_info,
        'show_edit': show_edit,
    })


@login_required
def change_password_view(request):
    if request.method == 'POST':
        form = NoReusePasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully!')
            return redirect('accounts:profile')
    else:
        form = NoReusePasswordChangeForm(request.user)
    for f in form.fields.values():
        f.widget.attrs.update({'class': 'form-control', 'placeholder': f.label})
    return render(request, 'accounts/change_password.html', {'form': form})


# ── Password reset flow ──────────────────────────────────────────────────────
#
# Standard Django token-based reset, but using our own templates and email
# so it matches the site's look and doesn't expose the raw reset URL in the
# email body (the link itself is the token; we don't show it as plain text).

# Two limits, same cache-based pattern as registration/OTP above:
#   - per IP: stops one connection/script from spamming the form.
#   - per email: stops someone spamming a specific person's inbox even if
#     they spread the requests across several IPs.
PASSWORD_RESET_MAX_PER_IP_PER_HOUR = 5
PASSWORD_RESET_MAX_PER_EMAIL_PER_HOUR = 3
PASSWORD_RESET_CONFIRM_MAX_FAILS_PER_HOUR = 10


def password_reset_request_view(request):
    if request.user.is_authenticated:
        return redirect('store:home')
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)

        ip = get_client_ip(request)
        if not check_hourly_limit(f'pwreset_ip:{ip}', PASSWORD_RESET_MAX_PER_IP_PER_HOUR):
            messages.error(
                request,
                'Too many password reset requests from your connection. Please try again in an hour.'
            )
            return render(request, 'accounts/password_reset.html', {'form': form})

        if form.is_valid():
            email = form.cleaned_data['email'].strip().lower()

            # Only proceed if the email belongs to an active account.
            if not any(True for _ in form.get_users(email)):
                form.add_error('email', 'This email is not registered. Please enter a valid email.')
                return render(request, 'accounts/password_reset.html', {'form': form})

            if not check_hourly_limit(f'pwreset_email:{email}', PASSWORD_RESET_MAX_PER_EMAIL_PER_HOUR):
                messages.error(
                    request,
                    'Too many reset requests for this email. Please try again in an hour.'
                )
                return render(request, 'accounts/password_reset.html', {'form': form})

            form.save(
                request=request,
                use_https=request.is_secure(),
                email_template_name='accounts/emails/password_reset_email.html',
                subject_template_name='accounts/emails/password_reset_subject.txt',
                html_email_template_name='accounts/emails/password_reset_email.html',
                from_email=settings.DEFAULT_FROM_EMAIL,
            )
            return redirect('accounts:password_reset_done')
    else:
        form = PasswordResetForm()
    return render(request, 'accounts/password_reset.html', {'form': form})


def password_reset_done_view(request):
    return render(request, 'accounts/password_reset_done.html')


def password_reset_confirm_view(request, uidb64, token):
    # The token itself is hard to guess, but nothing was stopping a script
    # from hammering this URL with uid/token combinations to brute-force it.
    # Cap failed attempts per IP, same cache-based pattern as the rest of
    # this file. Only failures count against the limit, so a legitimate
    # user with a correct link is never blocked by this.
    ip = get_client_ip(request)
    fail_key = f'pwreset_confirm_fail:{ip}'
    if cache.get(fail_key, 0) >= PASSWORD_RESET_CONFIRM_MAX_FAILS_PER_HOUR:
        return render(request, 'accounts/password_reset_confirm.html', {'invalid': True})

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    token_valid = user is not None and default_token_generator.check_token(user, token)
    if not token_valid:
        cache.set(fail_key, cache.get(fail_key, 0) + 1, 60 * 60)
        return render(request, 'accounts/password_reset_confirm.html', {'invalid': True})

    if request.method == 'POST':
        form = NoReuseSetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            return redirect('accounts:password_reset_complete')
    else:
        form = NoReuseSetPasswordForm(user)
    for f in form.fields.values():
        f.widget.attrs.update({'class': 'form-control auth-input'})
    return render(request, 'accounts/password_reset_confirm.html', {
        'form': form,
        'uidb64': uidb64,
        'token': token,
    })


def password_reset_complete_view(request):
    return render(request, 'accounts/password_reset_complete.html')