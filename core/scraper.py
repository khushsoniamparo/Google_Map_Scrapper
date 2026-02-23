from playwright.sync_api import sync_playwright
import time
import re
import math
import requests


# ─────────────────────────────────────────────────────────────────
# GEOCODING  (Nominatim – no API key needed)
# ─────────────────────────────────────────────────────────────────

def geocode_location(location: str):
    """Return (lat, lng) for a location string, or None."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "Scrapper/1.0"},
            timeout=8,
        )
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[geocode] error: {e}")
    return None


# ─────────────────────────────────────────────────────────────────
# GRID GENERATION
# ─────────────────────────────────────────────────────────────────

def generate_grid(center_lat: float, center_lng: float, grid_size: int, step_deg: float):
    """
    Generate a list of (lat, lng) grid points around a center.
    """
    half = grid_size // 2
    points = []
    for row in range(-half, half + 1):
        for col in range(-half, half + 1):
            points.append((
                center_lat + row * step_deg,
                center_lng + col * step_deg,
            ))
    return points


def pick_grid_params(location: str):
    """
    Heuristic: choose grid size and step based on the breadth of the location.
    """
    parts = [p.strip() for p in location.split(",")]
    num_parts = len(parts)

    loc_lower = location.lower()
    state_keywords = ["state", "pradesh", "rajasthan", "gujarat", "maharashtra",
                      "karnataka", "kerala", "tamil", "bihar", "odisha", "assam",
                      "punjab", "haryana", "uttarakhand", "jharkhand", "chhattisgarh",
                      "telangana", "andhra", "himachal"]

    if num_parts >= 3:
        return 3, 0.04  # City level
    elif num_parts == 2 or any(k in loc_lower for k in state_keywords):
        return 3, 0.20  # State level (reduced from 5 to 3 for performance)
    else:
        return 3, 0.04  # Default to city level


# ─────────────────────────────────────────────────────────────────
# DEDUPLICATION & UTILS
# ─────────────────────────────────────────────────────────────────

def _dedup_key(place: dict) -> str:
    name    = re.sub(r"\s+", " ", place.get("name",    "")).strip().lower()
    address = re.sub(r"\s+", " ", place.get("address", "")).strip().lower()
    return f"{name}|{address}"


def deduplicate(results: list) -> list:
    seen = set()
    uniq = []
    for r in results:
        key = _dedup_key(r)
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


# ─────────────────────────────────────────────────────────────────
# SCRAPING LOGIC
# ─────────────────────────────────────────────────────────────────

def _extract_place_details(page):
    """Extract details from the current place page."""
    try:
        # Very short timeout for name, as it's the anchor
        page.wait_for_selector("h1", timeout=3000)
        name = page.locator("h1").first.inner_text()
    except:
        return None

    # Website - search multiple possible selectors quickly
    website = "n/a"
    try:
        # Fast lookup for website
        website_el = page.locator('a[data-item-id="authority"], a[aria-label*="Website"]').first
        if website_el.count() > 0:
            href = website_el.get_attribute("href")
            if href:
                # Handle Google redirect URLs
                if "/url?q=" in href:
                    match = re.search(r"q=([^&]+)", href)
                    if match:
                        from urllib.parse import unquote
                        href = unquote(match.group(1))
                
                if "google.com" not in href or "/url?q=" in href: # Fallback if unquote failed
                    website = href
    except: pass

    # Address
    address = "See map"
    try:
        addr_el = page.locator('button[data-item-id="address"]').first
        if addr_el.count() > 0:
            aria = addr_el.get_attribute("aria-label")
            if aria: address = aria.replace("Address: ", "").strip()
    except: pass

    # Phone
    phone = "n/a"
    try:
        phone_el = page.locator('button[data-item-id^="phone"]').first
        if phone_el.count() > 0:
            aria = phone_el.get_attribute("aria-label")
            phone = aria.replace("Phone: ", "").strip() if aria else phone_el.inner_text()
    except: pass

    # Rating & Reviews
    rating, reviews = "N/A", 0
    try:
        # 1. Try the consolidated aria-label on the stars img/span
        star_el = page.locator('span[role="img"][aria-label*="stars"], span[aria-label*="stars"]').first
        if star_el.count() > 0:
            aria = star_el.get_attribute("aria-label")
            if aria:
                # Rating (e.g., "4.5 stars")
                r_match = re.search(r"(\d[\.,]\d)", aria)
                if r_match: rating = r_match.group(1).replace(",", ".")
                
                # Reviews (e.g., "123 reviews", "1,234 reviews", "4.5 stars 1,234 reviews")
                # Look for numbers near the word "review" or "rating"
                rev_match = re.search(r"(\d[\d,]*)\s*(?:reviews|ratings)", aria.lower())
                if rev_match:
                    reviews = int(rev_match.group(1).replace(",", ""))
        
        # 2. If reviews still 0, try finding the specific reviews count element
        if reviews == 0:
            # Often it's a button next to stars
            rev_btn = page.locator('button[aria-label*="reviews"], button[aria-label*="ratings"]').first
            if rev_btn.count() > 0:
                baria = rev_btn.get_attribute("aria-label")
                if baria:
                    rm = re.search(r"(\d[\d,]*)\s*(?:reviews|ratings)", baria.lower())
                    if rm:
                        reviews = int(rm.group(1).replace(",", ""))
        
        # 3. Last ditch: try plain text in parentheses or next to stars
        if reviews == 0:
            text_rev = page.locator('span:has-text("reviews"), span:has-text("ratings")').first
            if text_rev.count() > 0:
                inner = text_rev.inner_text()
                rm = re.search(r"(\d[\d,]*)", inner)
                if rm:
                    reviews = int(rm.group(1).replace(",", ""))

    except Exception as e:
        print(f"[scraper] Rating extraction error: {e}")
        pass

    # Coords from URL
    cur_url = page.url
    lat_m = re.search(r"!3d(-?\d+\.\d+)", cur_url)
    lng_m = re.search(r"!4d(-?\d+\.\d+)", cur_url)
    p_lat = float(lat_m.group(1)) if lat_m else None
    p_lng = float(lng_m.group(1)) if lng_m else None

    if not p_lat or not p_lng: return None

    return {
        "name": name, "lat": p_lat, "lng": p_lng,
        "website": website, "address": address,
        "phone": phone, "rating": rating, "reviews": reviews
    }

def handle_cookies(page):
    """Handle the 'Before you continue' cookie popup if it appears."""
    try:
        # Look for the 'Accept all' button which often appears in Europe/certain IPs
        # Common text: 'Accept all', 'I agree', 'Accept'
        selectors = [
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button[aria-label="Accept all"]',
            'form[action*="consent.google.com"] button'
        ]
        for sel in selectors:
            btn = page.locator(sel)
            if btn.count() > 0:
                btn.first.click()
                page.wait_for_load_state("networkidle", timeout=3000)
                return True
    except: pass
    return False

def scrape_google_maps(query: str, location_str: str, city_name: str = "N/A"):
    print(f"[speed-scraper] START: {query} in {location_str}")
    coords = geocode_location(location_str)
    results = []

    with sync_playwright() as p:
        # Launch with performance args
        browser = p.chromium.launch(headless=True, args=[
            '--disable-http2', 
            '--blink-settings=imagesEnabled=false',
            '--disable-extensions',
            '--disable-notifications',
            '--disable-gpu'
        ])
        
        # Block only images and fonts to keep site logic intact but speed up load
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        context.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,otf,ttf}", lambda route: route.abort())
        
        main_page = context.new_page()

        # Grid logic
        if not coords:
            points = [(None, None)]
            base_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}+in+{location_str.replace(' ', '+')}"
        else:
            lat, lng = coords
            # Grid: size 1 means 1x1, size 3 means 3x3
            # We use 1 for extreme speed if it's just a city search
            grid_size, step = 1, 0.05 
            points = generate_grid(lat, lng, grid_size, step)
            print(f"[speed-scraper] Points: {len(points)} | Center: {lat},{lng}")

        for p_lat, p_lng in points:
            if p_lat is None:
                url = base_url
            else:
                url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}/@{p_lat},{p_lng},14z"
            
            try:
                print(f"[speed-scraper] Scanning point {points.index((p_lat, p_lng)) + 1}/{len(points)}: {url[:60]}...")
                # Use 'commit' for the initial load, then wait for content
                main_page.goto(url, timeout=15000, wait_until='commit')
                
                # Check for cookies first if "Confirm" or "Consent" is in URL
                if "consent.google.com" in main_page.url or main_page.locator('button:has-text("Accept all")').count() > 0:
                    handle_cookies(main_page)

                # Wait for any result link to appear
                try:
                    main_page.wait_for_selector('a[href*="/maps/place/"]', timeout=5000)
                except:
                    # If it's a direct place result, extract it
                    data = _extract_place_details(main_page)
                    if data:
                        data['city_name'] = city_name
                        data['category'] = query
                        results.append(data)
                    continue

                # Collect links (Less scrolling for more speed)
                main_page.mouse.wheel(0, 1500)
                time.sleep(0.5)
                
                # Broaden selector to include more potential result links
                links_els = main_page.locator('a[href*="/maps/place/"], a[aria-label][href*="google.com/maps"]').all()
                place_urls = []
                for link in links_els:
                    try:
                        href = link.get_attribute("href")
                        if href and "/maps/place/" in href and href not in place_urls:
                            place_urls.append(href)
                    except: pass
                    if len(place_urls) >= 12: break 

                print(f"[speed-scraper] Found {len(place_urls)} businesses to extract.")
                if not place_urls: 
                    continue

                # PARALLEL EXTRACTION: Batch process place details
                batch_size = 4
                for i in range(0, len(place_urls), batch_size):
                    batch = place_urls[i:i + batch_size]
                    print(f"[speed-scraper] Extracting batch {i//batch_size + 1}/{(len(place_urls)-1)//batch_size + 1}...")
                    pages = []
                    for purl in batch:
                        p = context.new_page()
                        pages.append((p, purl))
                    
                    # Parallel load
                    for p, purl in pages:
                        try: p.goto(purl, timeout=12000, wait_until='domcontentloaded')
                        except: pass
                    
                    # Sequential extract (fast since pages are already loaded)
                    for p, _ in pages:
                        try:
                            data = _extract_place_details(p)
                            if data:
                                print(f"  ✓ Extracted: {data['name'][:30]}")
                                data['city_name'] = city_name
                                data['category'] = query
                                results.append(data)
                        except: pass
                        p.close()
                    
                    if len(results) >= 40: break

            except Exception as e:
                print(f"[speed-scraper] Grid error: {e}")
                continue

        browser.close()

    unique_results = deduplicate(results)
    print(f"[speed-scraper] DONE: Found {len(unique_results)}")
    return unique_results
