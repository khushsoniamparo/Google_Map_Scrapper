# 🌐 Django Google Maps Scraper & Search App

A robust Django web application that allows users to search for places (e.g., "Tea in Bhilwara") and visualizes the results on an interactive map using scraped data from Google Maps. It features a modern, split-view UI similar to Google Maps or Zomato.

## 🚀 Features

*   **Real-time Scraping**: Uses **Playwright** to scrape live data from Google Maps (Names, Ratings, Addresses, Lat/Lng).
*   **Split-View UI**: Professional layout with a scrollable list on the left and a full-screen map on the right.
*   **Interactive Map**:
    *   Powered by **Leaflet.js** (OpenStreetMap) - No API Key required.
    *   Clicking a list item flies the map to the location.
    *   Clicking a map marker highlights the list item.
*   **Smart UX**:
    *   **Category Chips**: Quick search for common places (Gym, Cafe, ATM, etc.).
    *   **Loading State**: Visual feedback while the scraper runs.
    *   **Directions**: Direct link to open Google Maps navigation for any result.
*   **Robust Scraper**: Handles redirects (single result pages), consent popups, and scrolling for lazy-loaded results.

---

## 🛠️ Tech Stack

*   **Backend**: Django 5.0 (Python)
*   **Scraping**: Playwright (Headless Browser Automation)
*   **Frontend**: HTML5, CSS3, JavaScript (Leaflet.js for Maps)
*   **Styling**: Custom CSS (Outfit Font, Modern Shadow/Border Design)

---

## ⚙️ How It Works (Under the Hood)

### 1. The Search Request
When a user enters a query (e.g., "Gym") and location (e.g., "Mumbai"):
1.  Frontend sends a `GET` request to the Django view (`/`).
2.  `views.py` captures the `q` and `location` parameters.

### 2. The Scraper (`core/scraper.py`)
Because Google Maps relies heavily on JavaScript, simple HTTP requests (BeautifulSoup) fail. We use **Playwright**:
1.  **Launches a Browser**: A headless Chromium instance starts.
2.  **Navigates**: Goes to `https://www.google.com/maps/search/{query}+in+{location}`.
3.  **Handles Edge Cases**:
    *   *Cookie Popups*: Automatically clicks "Accept All".
    *   *Single Result Redirects*: Detects if Google redirects directly to a place (e.g., "M.L.V College") instead of a list.
4.  **Scrolls**: Simulates mouse wheel scrolling to trigger lazy loading of more results.
5.  **Extracts Data**:
    *   **Name**: From `aria-label` or `h1` tags.
    *   **Lat/Lng**: Regex parsing of the `!3d` and `!4d` parameters in the URL.
6.  **Returns**: A list of dictionaries (Name, Lat, Lng, Address, Rating).

### 3. The Frontend (`search.html`)
1.  **Rendering**: Django injects the scraped list into the template.
2.  **Map Initialization**: Leaflet.js creates a map centered on the first result.
3.  **Interactivity**:
    *   JavaScript loops through the results to create Markers.
    *   `flyTo()` animation is used for smooth map movement.
    *   `scrollIntoView()` ensures the active list item is always visible when a marker is clicked.

---

## 📦 Installation & Setup

### 1. Clone the Repository
```bash
git clone <repository_url>
cd scrapper_django
```

### 2. Install Dependencies
```bash
pip install django playwright
```

### 3. Install Browsers for Playwright
This downloads the Chromium browser binary needed for scraping.
```bash
python -m playwright install chromium
```

### 4. Run Migrations
```bash
python manage.py migrate
```

### 5. Start the Server
```bash
python manage.py runserver
```
Go to `http://127.0.0.1:8000/`

---

## 📂 Project Structure

```
scrapper_django/
│
├── core/
│   ├── templates/
│   │   └── search.html    # Main UI (Split view, Map logic)
│   ├── scraper.py         # Playwright logic (The "Engine")
│   ├── views.py           # Handles requests & calls scraper
│   └── urls.py            # Routing
│
├── scrapper_project/      # Main Django project settings
├── manage.py
└── db.sqlite3
```

## ⚠️ Notes
*   **Performance**: Scraping takes 5-15 seconds depending on network speed because it loads a real browser.
*   **Google Blocking**: Playwright uses a real "User-Agent" to mimic a human user to avoid being blocked by Google.

---
