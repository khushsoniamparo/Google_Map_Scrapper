from django.shortcuts import render
from django.http import JsonResponse
from .scraper import scrape_google_maps
from datetime import datetime
import json
import concurrent.futures
import uuid
import razorpay
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from .models import Subscription

FREE_LIMIT    = 10
PREMIUM_LIMIT = 1000


def build_location_string(city, state, country):
    parts = [p.strip() for p in [city, state, country] if p and p.strip()]
    return ", ".join(parts) if parts else None


PLANS = {
    "starter": {"name": "Starter",   "searches": 100,  "price": 99},
    "pro":     {"name": "Pro",        "searches": 500,  "price": 299},
    "elite":   {"name": "Elite",      "searches": 1000, "price": 599},
}


def create_razorpay_order(request):
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            plan_key = body.get("plan", "pro")
        except Exception:
            plan_key = "pro"

        plan = PLANS.get(plan_key, PLANS["pro"])
        amount = plan["price"] * 100  # Razorpay expects amount in paise (INR)

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        
        try:
            # Create Razorpay Order
            data = {
                "amount": amount,
                "currency": "INR",
                "payment_capture": "1"
            }
            order = client.order.create(data=data)
            
            # Save order_id to DB if user is authenticated
            if request.user.is_authenticated:
                sub, created = Subscription.objects.get_or_create(user=request.user)
                sub.razorpay_order_id = order['id']
                sub.plan_name = plan["name"]
                sub.premium_searches = plan["searches"]
                sub.save()

            return JsonResponse({
                "order_id": order['id'],
                "amount": amount,
                "currency": "INR",
                "key": settings.RAZORPAY_KEY_ID,
                "plan_name": plan["name"]
            })
        except Exception as e:
            print(f"Razorpay Order Error: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def verify_payment(request):
    if request.method == "POST":
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        plan_key = data.get('plan_key')

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }

        try:
            # Verify signature
            client.utility.verify_payment_signature(params_dict)
            
            # If verification successful, update user subscription
            plan = PLANS.get(plan_key, PLANS["pro"])
            
            # Update session (for immediate UI feedback)
            request.session['is_premium'] = True
            request.session['plan_name'] = plan["name"]
            request.session['premium_searches'] = plan["searches"]
            
            # Update database if user is authenticated
            if request.user.is_authenticated:
                sub, created = Subscription.objects.get_or_create(user=request.user)
                sub.is_premium = True
                sub.plan_name = plan["name"]
                sub.premium_searches = plan["searches"]
                sub.razorpay_order_id = razorpay_order_id
                sub.razorpay_payment_id = razorpay_payment_id
                sub.razorpay_signature = razorpay_signature
                sub.save()

            return JsonResponse({"status": "ok"})
        except Exception as e:
            print(f"Payment verification failed: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error"}, status=405)


@csrf_exempt
def razorpay_webhook(request):
    # Webhook for Razorpay to confirm payment even if user closes the tab before verification
    if request.method == "POST":
        payload = request.body
        signature = request.headers.get("X-Razorpay-Signature")
        
        # Typically you check secret from settings
        # client.utility.verify_webhook_signature(payload, signature, settings.RAZORPAY_WEBHOOK_SECRET)
        
        try:
            data = json.loads(payload)
            if data['event'] == 'payment.captured':
                payment = data['payload']['payment']['entity']
                order_id = payment['order_id']
                payment_id = payment['id']
                
                # Update subscription based on order_id
                try:
                    sub = Subscription.objects.get(razorpay_order_id=order_id)
                    sub.is_premium = True
                    sub.razorpay_payment_id = payment_id
                    sub.save()
                    print(f"Webhook: Updated subscription for order {order_id}")
                except Subscription.DoesNotExist:
                    print(f"Webhook: Order {order_id} not found in database")
                    
            return JsonResponse({"status": "ok"})
        except Exception as e:
            print(f"Webhook error: {e}")
            return JsonResponse({"status": "error"}, status=400)
            
    return JsonResponse({"status": "error"}, status=405)


def activate_premium(request):
    # This view is now mostly redundant but keeping it for backward compatibility or simple local testing
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            plan_key = body.get("plan", "pro")
        except Exception:
            plan_key = "pro"

        plan = PLANS.get(plan_key, PLANS["pro"])
        request.session['is_premium']       = True
        request.session['plan_name']        = plan["name"]
        request.session['premium_searches'] = plan["searches"]
        
        # Also update DB if possible
        if request.user.is_authenticated:
            sub, created = Subscription.objects.get_or_create(user=request.user)
            sub.is_premium = True
            sub.plan_name = plan["name"]
            sub.premium_searches = plan["searches"]
            sub.save()

        return JsonResponse({"status": "ok", "plan": plan["name"], "limit": plan["searches"]})
    return JsonResponse({"status": "error"}, status=405)


def pricing_view(request):
    is_premium = request.session.get('is_premium', False)
    plan_name  = request.session.get('plan_name', None)
    
    # Check DB if session is empty but user is logged in
    if not is_premium and request.user.is_authenticated:
        try:
            sub = request.user.subscription
            if sub.is_premium:
                is_premium = True
                plan_name = sub.plan_name
                request.session['is_premium'] = True
                request.session['plan_name'] = sub.plan_name
                request.session['premium_searches'] = sub.premium_searches
        except Subscription.DoesNotExist:
            pass

    plan_searches = request.session.get('premium_searches', PREMIUM_LIMIT)
    max_searches = plan_searches if is_premium else FREE_LIMIT
    searches_used = request.session.get('searches_used', 0)

    return render(request, "pricing.html", {
        "plans":      PLANS,
        "is_premium": is_premium,
        "plan_name":  plan_name,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "searches_used": searches_used,
        "max_searches": max_searches,
    })


def tasks_view(request):
    """Shows the full search history for the current session."""
    history    = request.session.get('search_history', [])
    is_premium = request.session.get('is_premium', False)
    plan_name  = request.session.get('plan_name', None)

    plan_searches = request.session.get('premium_searches', PREMIUM_LIMIT)
    max_searches = plan_searches if is_premium else FREE_LIMIT
    searches_used = request.session.get('searches_used', 0)
    searches_left = max(0, max_searches - searches_used)
    limit_reached = searches_used >= max_searches

    return render(request, "tasks.html", {
        "history":       list(reversed(history)),
        "is_premium":    is_premium,
        "plan_name":     plan_name,
        "searches_used": searches_used,
        "searches_left": searches_left,
        "max_searches":  max_searches,
        "limit_reached": limit_reached,
        "free_limit":    FREE_LIMIT,
    })


def about_view(request):
    is_premium = request.session.get('is_premium', False)
    plan_name  = request.session.get('plan_name', None)
    
    plan_searches = request.session.get('premium_searches', PREMIUM_LIMIT)
    max_searches = plan_searches if is_premium else FREE_LIMIT
    searches_used = request.session.get('searches_used', 0)

    return render(request, "about.html", {
        "is_premium": is_premium,
        "plan_name":  plan_name,
        "searches_used": searches_used,
        "max_searches": max_searches,
    })


def clear_history(request):
    """POST — wipes the session search history."""
    if request.method == "POST":
        request.session['search_history'] = []
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "error"}, status=405)


import uuid

def search_view(request):
    results       = []
    error_message = None
    location_used = None
    task_id       = None

    # --- Tier logic ---
    is_premium   = request.session.get('is_premium', False)
    plan_searches = request.session.get('premium_searches', PREMIUM_LIMIT)
    max_searches = plan_searches if is_premium else FREE_LIMIT

    searches_used = request.session.get('searches_used', 0)
    limit_reached = searches_used >= max_searches

    # --- Read inputs (Multi-tag support) ---
    queries   = request.GET.getlist('q')
    countries = request.GET.getlist('countries')
    states    = request.GET.getlist('states')
    cities    = request.GET.getlist('cities')

    # Generate location combinations
    locations = []
    if cities:
        for c in cities:
            s = states[0] if states else ""
            co = countries[0] if countries else ""
            locations.append(build_location_string(c, s, co))
    elif states:
        for s in states:
            co = countries[0] if countries else ""
            locations.append(build_location_string("", s, co))
    elif countries:
        for co in countries:
            locations.append(build_location_string("", "", co))

    if request.method == "GET" and queries:
        if not locations:
            error_message = "Please add at least one location (City, State, or Country)."
        elif limit_reached:
            pass
        else:
            try:
                all_raw_results = []
                
                # Tier-based thread limit
                max_workers = 3 if is_premium else 2
                print(f"[search] Initializing parallel search for {len(queries)} x {len(locations)} targets with {max_workers} workers...")
                
                search_tasks = []
                # Map location string to a cleaner city name for filtering
                for q in queries:
                    if cities:
                        for c in cities:
                            s = states[0] if states else ""
                            co = countries[0] if countries else ""
                            loc_str = build_location_string(c, s, co)
                            search_tasks.append((q.strip(), loc_str, c))
                    elif states:
                        for s in states:
                            co = countries[0] if countries else ""
                            loc_str = build_location_string("", s, co)
                            search_tasks.append((q.strip(), loc_str, s))
                    else:
                        for co in countries:
                            loc_str = build_location_string("", "", co)
                            search_tasks.append((q.strip(), loc_str, co))

                # Run parallel searches
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    print(f"[search] Submitting {len(search_tasks)} tasks to pool...")
                    future_to_search = {
                        executor.submit(scrape_google_maps, q, loc, city): (q, loc) 
                        for q, loc, city in search_tasks if q and loc
                    }
                    print(f"[search] Waiting for completions...")
                    for future in concurrent.futures.as_completed(future_to_search):
                        try:
                            grid_results = future.result()
                            if grid_results:
                                print(f"[search] Received {len(grid_results)} leads from a task.")
                                all_raw_results.extend(grid_results)
                        except Exception as e:
                            print(f"[search] Task error: {e}")
                
                print(f"[search] Parallel processing complete. Total raw leads: {len(all_raw_results)}")
                from .scraper import deduplicate
                results = deduplicate(all_raw_results)
                
                # Default sort: Better leads (with websites) first
                results.sort(key=lambda r: 0 if r.get("website", "n/a") == "n/a" else 1, reverse=True)

                searches_used += 1
                request.session['searches_used'] = searches_used
                limit_reached = searches_used >= max_searches
                location_used = ", ".join(locations[:2]) + ("..." if len(locations) > 2 else "")

                # --- Save to search history ---
                task_id = str(uuid.uuid4())[:8]
                history = request.session.get('search_history', [])
                history.append({
                    "task_id":      task_id,
                    "query":        ", ".join(queries),
                    "location":     ", ".join(locations),
                    "result_count": len(results),
                    "timestamp":    datetime.now().strftime("%d %b %Y, %I:%M %p"),
                    "city":         ", ".join(cities),
                    "state":        ", ".join(states),
                    "country":      ", ".join(countries),
                })
                request.session['search_history'] = history
                
                # Store results separately to keep history list light for the UI
                task_results = request.session.get('task_results', {})
                task_results[task_id] = results
                request.session['task_results'] = task_results

                if not results:
                    error_message = "No results found for your search criteria."

            except Exception as e:
                print(f"Scraping error: {e}")
                results = []
                error_message = f"Error: {str(e)}"

    searches_left = max(0, max_searches - searches_used)

    return render(request, "search.html", {
        "results":        results,
        "task_id":        task_id,
        "query_list":     queries,
        "countries_list": countries,
        "states_list":    states,
        "cities_list":    cities,
        "location_used":  location_used,
        "error_message":  error_message,
        "searches_used":  searches_used,
        "searches_left":  searches_left,
        "max_searches":   max_searches,
        "limit_reached":  limit_reached,
        "is_premium":     is_premium,
        "free_limit":     FREE_LIMIT,
    })

import csv
from django.http import HttpResponse

def export_csv_view(request):
    """
    Backend CSV Export: 
    1. Receives task_id and fields via POST
    2. Retrieves data from session
    3. Filters data dynamically
    4. Generates CSV response
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
        task_id = body.get("task_id")
        fields = body.get("fields", [])
        # Optional: frontend filters
        city_filter = body.get("city_filter", "all")
        cat_filter = body.get("cat_filter", "all")
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid request body"}, status=400)

    if not fields:
        return JsonResponse({"status": "error", "message": "No fields selected"}, status=400)

    # 1. Retrieve data
    all_task_results = request.session.get('task_results', {})
    
    # If no task_id, try to get the most recent one or return error
    if not task_id:
        history = request.session.get('search_history', [])
        if history:
            task_id = history[-1].get('task_id')
    
    results = all_task_results.get(task_id, [])
    if not results:
        return JsonResponse({"status": "error", "message": "Data not found"}, status=404)

    # 2. Apply UI filters if any (to match exactly what the user sees)
    if city_filter != "all":
        results = [r for r in results if r.get('city_name') == city_filter]
    if cat_filter != "all":
        results = [r for r in results if r.get('category') == cat_filter]

    # 3. Create CSV Response
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="leads_export_{task_id}.csv"'
    
    # BOM for Excel UTF-8 (Write as string, Django handles encoding)
    response.write('\ufeff')
    
    writer = csv.DictWriter(response, fieldnames=fields, extrasaction='ignore')
    
    # Map labels (Optional but friendly)
    labels = {
        'name': 'Business Name', 'address': 'Address', 'phone': 'Phone',
        'website': 'Website', 'rating': 'Rating', 'reviews': 'Reviews',
        'lat': 'Latitude', 'lng': 'Longitude', 'city_name': 'City', 'category': 'Category'
    }
    
    # Write custom header row
    header = {f: labels.get(f, f.capitalize()) for f in fields}
    writer.writerow(header)
    
    # Write filtered data
    for row in results:
        # Clean data (e.g. n/a to empty)
        clean_row = {}
        for f in fields:
            val = row.get(f, "")
            if f == 'website' and val == 'n/a': val = ""
            clean_row[f] = val
        writer.writerow(clean_row)

    return response


def task_detail_view(request, task_id):
    history = request.session.get('search_history', [])
    # Use .get() to safely check for 'task_id' and avoid KeyError on older history items
    task_meta = next((item for item in history if item.get('task_id') == task_id), None)
    
    if not task_meta:
        return render(request, "search.html", {"error_message": "Task not found."})

    all_task_results = request.session.get('task_results', {})
    results = all_task_results.get(task_id, [])

    is_premium = request.session.get('is_premium', False)
    searches_used = request.session.get('searches_used', 0)
    plan_searches = request.session.get('premium_searches', PREMIUM_LIMIT)
    max_searches = plan_searches if is_premium else FREE_LIMIT

    return render(request, "task_detail.html", {
        "task_id":     task_id,
        "task_meta":   task_meta,
        "results":     results,
        "is_premium":  is_premium,
        "searches_used": searches_used,
        "max_searches": max_searches,
    })

