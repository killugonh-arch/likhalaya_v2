"""Shipping fee = distance-based fee + item-count surcharge.

Origin is the workshop in Carigara, Leyte. The customer's province (and
city, for nearby Leyte towns) is turned into an approximate distance in km,
which picks a fee band. Each extra item beyond the first adds a small
surcharge (capped), so bigger orders cost more to ship.

All numbers are tunable in DISTANCE_BANDS / PER_EXTRA_ITEM / MAX_ITEM_SURCHARGE.
"""
from decimal import Decimal
from math import radians, sin, cos, asin, sqrt

# Workshop location: Carigara, Leyte
ORIGIN = (11.2993, 124.6866)

# Straight-line distance undercounts real road/sea routes.
ROUTE_FACTOR = Decimal('1.3')

# (max_km, base_fee, label) - first band whose max_km >= distance wins.
DISTANCE_BANDS = [
    (10,    Decimal('15'),  'Near Carigara'),
    (60,    Decimal('35'),  'Within Leyte (near)'),
    (150,   Decimal('55'),  'Leyte / Biliran / Samar area'),
    (350,   Decimal('85'),  'Eastern & Central Visayas'),
    (700,   Decimal('125'), 'Western Visayas / Northern Mindanao / Bicol'),
    (1000,  Decimal('165'), 'Far Mindanao / Southern Luzon / Metro Manila'),
    (10**6, Decimal('205'), 'Far Luzon / Palawan / Sulu'),
]

# Used when the customer's province can't be recognised.
FALLBACK_BAND_INDEX = 4

# Inside Leyte the fee follows the town's distance instead of a coarse band:
# LEYTE_BASE_FEE + LEYTE_PER_KM * km, rounded to the nearest 5.
# Carigara itself is always free (no base fee, no item surcharge).
LEYTE_BASE_FEE = Decimal('5')
LEYTE_PER_KM = Decimal('0.5')

PER_EXTRA_ITEM = Decimal('10')        # each item after the first
MAX_ITEM_SURCHARGE = Decimal('100')   # cap on the item surcharge

# Province centroids (lat, lng), approximate.
PROVINCE_COORDS = {
    # Luzon
    'abra': (17.59, 120.74), 'albay': (13.18, 123.60), 'apayao': (18.0, 121.2),
    'aurora': (15.9, 121.6), 'bataan': (14.65, 120.45), 'batanes': (20.45, 121.97),
    'batangas': (13.95, 121.05), 'benguet': (16.55, 120.75), 'bulacan': (14.9, 120.9),
    'cagayan': (17.9, 121.8), 'camarines norte': (14.15, 122.7),
    'camarines sur': (13.6, 123.3), 'catanduanes': (13.8, 124.3),
    'cavite': (14.3, 120.9), 'ifugao': (16.8, 121.2), 'ilocos norte': (18.2, 120.6),
    'ilocos sur': (17.3, 120.5), 'isabela': (17.0, 121.9), 'kalinga': (17.45, 121.3),
    'la union': (16.55, 120.35), 'laguna': (14.2, 121.35), 'marinduque': (13.4, 122.0),
    'masbate': (12.35, 123.55), 'mountain province': (17.05, 121.1),
    'nueva ecija': (15.5, 121.0), 'nueva vizcaya': (16.3, 121.15),
    'occidental mindoro': (13.1, 120.8), 'oriental mindoro': (13.0, 121.3),
    'palawan': (9.8, 118.7), 'pampanga': (15.05, 120.65), 'pangasinan': (16.05, 120.35),
    'quezon': (14.0, 121.9), 'quirino': (16.3, 121.55), 'rizal': (14.6, 121.3),
    'romblon': (12.55, 122.3), 'sorsogon': (12.95, 124.0), 'tarlac': (15.5, 120.55),
    'zambales': (15.3, 120.1),
    'national capital region': (14.6, 121.0), 'metro manila': (14.6, 121.0),
    'ncr': (14.6, 121.0),
    # Visayas
    'aklan': (11.7, 122.35), 'antique': (11.2, 122.0), 'biliran': (11.55, 124.45),
    'bohol': (9.85, 124.2), 'capiz': (11.5, 122.7), 'cebu': (10.3, 123.9),
    'eastern samar': (11.5, 125.4), 'guimaras': (10.6, 122.6), 'iloilo': (10.9, 122.55),
    'leyte': (10.8, 124.9), 'negros occidental': (10.4, 123.0),
    'negros oriental': (9.6, 123.0), 'northern samar': (12.4, 124.6),
    'samar': (11.9, 125.0), 'western samar': (11.9, 125.0), 'siquijor': (9.2, 123.55),
    'southern leyte': (10.3, 125.0),
    # Mindanao
    'agusan del norte': (9.0, 125.5), 'agusan del sur': (8.5, 126.0),
    'basilan': (6.5, 122.0), 'bukidnon': (8.1, 125.1), 'camiguin': (9.17, 124.72),
    'cotabato': (7.2, 124.6), 'north cotabato': (7.2, 124.6),
    'davao de oro': (7.5, 126.1), 'compostela valley': (7.5, 126.1),
    'davao del norte': (7.5, 125.7), 'davao del sur': (6.7, 125.35),
    'davao occidental': (6.1, 125.6), 'davao oriental': (7.2, 126.4),
    'dinagat islands': (10.1, 125.6), 'lanao del norte': (8.0, 123.9),
    'lanao del sur': (7.9, 124.3), 'maguindanao': (7.0, 124.4),
    'misamis occidental': (8.4, 123.7), 'misamis oriental': (8.5, 124.7),
    'sarangani': (5.9, 125.2), 'south cotabato': (6.3, 125.0),
    'sultan kudarat': (6.5, 124.4), 'sulu': (6.0, 121.0),
    'surigao del norte': (9.6, 125.6), 'surigao del sur': (8.8, 126.1),
    'tawi-tawi': (5.0, 119.9), 'zamboanga del norte': (8.2, 123.0),
    'zamboanga del sur': (7.8, 123.4), 'zamboanga sibugay': (7.7, 122.6),
}
_PROVINCE_KEYS = sorted(PROVINCE_COORDS, key=len, reverse=True)

# Leyte towns near the workshop (approx. km from Carigara), so a Leyte
# address isn't just one flat province-wide distance.
LEYTE_TOWN_KM = {
    'carigara': 0, 'barugo': 6, 'capoocan': 12, 'tunga': 12, 'jaro': 15,
    'san miguel': 20, 'leyte': 22, 'alangalang': 25, 'calubian': 28,
    'tabango': 30, 'san isidro': 45, 'santa fe': 40, 'babatngon': 40,
    'palo': 38, 'tacloban': 45, 'dagami': 45, 'pastrana': 45,
    'tabontabon': 45, 'tanauan': 55, 'dulag': 55, 'kananga': 50,
    'villaba': 60, 'palompon': 60, 'matag-ob': 65, 'ormoc': 70,
    'burauen': 70, 'merida': 70, 'albuera': 80, 'isabel': 85,
    'abuyog': 85, 'baybay': 100, 'hilongos': 105,
}


def _clean(text):
    text = (text or '').lower().strip()
    if text.startswith('mountain province'):
        return 'mountain province'
    for junk in ('city of ', ' city', ' (capital)', ' province', '(', ')'):
        text = text.replace(junk, ' ')
    return ' '.join(text.split())


def _haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(h))


def _match_province(province):
    name = _clean(province)
    if not name:
        return None
    if name in PROVINCE_COORDS:
        return name
    for key in _PROVINCE_KEYS:
        if key in name:
            return key
    return None


def estimate_distance_km(province, city=''):
    """Approximate route distance (km) from Carigara, or None if unknown."""
    key = _match_province(province)
    if key is None:
        return None
    if key == 'leyte':
        town = _clean(city)
        if town in LEYTE_TOWN_KM:
            return Decimal(LEYTE_TOWN_KM[town])
    km = _haversine_km(ORIGIN, PROVINCE_COORDS[key]) * float(ROUTE_FACTOR)
    return Decimal(str(round(km)))


def _band_for(km):
    if km is None:
        return DISTANCE_BANDS[FALLBACK_BAND_INDEX]
    for max_km, fee, label in DISTANCE_BANDS:
        if km <= max_km:
            return max_km, fee, label
    return DISTANCE_BANDS[-1]


def item_surcharge(quantity):
    extra = max(0, int(quantity or 0) - 1)
    return min(PER_EXTRA_ITEM * extra, MAX_ITEM_SURCHARGE)


def _round5(value):
    return (value / 5).quantize(Decimal('1'), rounding='ROUND_HALF_UP') * 5


def get_shipping_quote(quantity=1, province='', city=''):
    """Full breakdown, used by views/templates.
    Returns dict: fee, base_fee, item_fee, distance_km, zone, estimated, free."""
    km = estimate_distance_km(province, city)
    result = {
        'per_item': PER_EXTRA_ITEM,
        'max_item_fee': MAX_ITEM_SURCHARGE,
        'distance_km': km,
        'estimated': km is None,
        'free': False,
    }

    if _match_province(province) == 'leyte':
        if _clean(city) == 'carigara':
            result.update(fee=Decimal('0'), base_fee=Decimal('0'), item_fee=Decimal('0'),
                          per_item=Decimal('0'), max_item_fee=Decimal('0'),
                          zone='Carigara - free shipping', free=True)
            return result
        base_fee = _round5(LEYTE_BASE_FEE + LEYTE_PER_KM * km)
        item_fee = item_surcharge(quantity)
        result.update(fee=base_fee + item_fee, base_fee=base_fee, item_fee=item_fee,
                      zone='Within Leyte')
        return result

    _, base_fee, label = _band_for(km)
    item_fee = item_surcharge(quantity)
    result.update(fee=base_fee + item_fee, base_fee=base_fee, item_fee=item_fee, zone=label)
    return result


def calculate_shipping_fee(quantity=1, province='', city=''):
    return get_shipping_quote(quantity, province, city)['fee']