from django import template

register = template.Library()


def _mask_word(word):
    """First 2 letters + asterisks + last letter, uppercased.
    "Deniel" -> "DE***L", "Bryan" -> "BR**N"."""
    w = word.upper()
    n = len(w)
    if n <= 2:
        return w
    if n == 3:
        return w[0] + '*' + w[-1]
    return w[:2] + '*' * (n - 3) + w[-1]


@register.filter
def mask_gcash_name(value):
    """Masks a GCash account name for customer display. Every word except the
    last is masked (first 2 letters, asterisks, last letter); the last name is
    reduced to its initial + a period.

    "Deniel Bryan Perea" -> "DE***L BR**N P."
    "Pedro Penduko"      -> "PE**O P."
    "Cher"               -> "CH*R"
    """
    if not value:
        return ''

    words = [w for w in value.split() if w]
    if not words:
        return ''
    if len(words) == 1:
        return _mask_word(words[0])

    masked = [_mask_word(w) for w in words[:-1]]
    masked.append(words[-1][0].upper() + '.')
    return ' '.join(masked)


@register.filter
def mask_gcash_number(value):
    """Masks a GCash number: keeps the first 4 and last 2 digits, hides the
    rest. Spaces/dashes/+ are left in place.

    "09751548542" -> "0975*****42"
    """
    if not value:
        return ''

    value = str(value).strip()
    total = sum(c.isdigit() for c in value)
    if total <= 6:
        return value

    out, seen = [], 0
    for c in value:
        if c.isdigit():
            seen += 1
            out.append(c if seen <= 4 or seen > total - 2 else '*')
        else:
            out.append(c)
    return ''.join(out)