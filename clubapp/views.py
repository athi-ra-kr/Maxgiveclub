from decimal import Decimal, ROUND_HALF_UP
import math
import json
from datetime import date, datetime, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Sum
from django.utils import timezone

# Assuming your models are named Member and PVTransaction
from .models import Member, PVTransaction






# ---------------------------------------------------------
#  LOGIC ENGINE: PV CALCULATION (WITH 2026 START CLAMP)
# ---------------------------------------------------------

def get_effective_date(date_obj):
    """
    Forces any date before Jan 1, 2026 to be Jan 1, 2026.
    """
    project_start = date(2026, 1, 1)
    # Ensure we are comparing date objects
    if isinstance(date_obj, datetime):
        d = date_obj.date()
    else:
        d = date_obj
        
    if d < project_start:
        return project_start
    return d

# In views.py

# ... (Imports remain the same) ...

# ---------------------------------------------------------
#  LOGIC ENGINE: FIXED BASE PRICE + PERSONAL TENURE GROWTH
# ---------------------------------------------------------

def get_base_price_for_purchase_year(year):
    """
    Calculates the Entry Price (Base Value) for a specific year.
    2026: 100.00
    2027: 108.00  (100 + 8%)
    2028: 117.72  (108 + 9%)
    ...
    """
    if year < 2026: return 100.00
    if year == 2026: return 100.00
    
    price = 100.00
    # Calculate cumulative System Growth to find entry price
    for y in range(2026, year):
        # 2026->2027: 8%
        # 2027->2028: 9%
        # 2028->2029: 10%
        rate = 8 + (y - 2026)
        
        if rate > 14: rate = 14
        
        price *= (1 + rate / 100.0)
        
    return price

def calculate_pv_value_at_date(pv_units, purchase_date, target_year, target_month):
    # 1. DATE CLAMP: Treat Dec 2025 (or older) as Jan 1, 2026
    p_date = get_effective_date(purchase_date)
    
    # 2. Total Months Calculation
    start_total_months = (p_date.year * 12) + p_date.month
    target_total_months = (target_year * 12) + target_month
    
    months_diff = target_total_months - start_total_months

    # If target is before join date
    if months_diff < 0:
        return None
        
    # --- STEP A: DETERMINE BASE PRICE (ENTRY VALUE) ---
    start_price = get_base_price_for_purchase_year(p_date.year)
    current_value = float(pv_units) * float(start_price)
    
    # --- STEP B: EXACT JOIN MONTH FIX (CRITICAL) ---
    # This forces the value to stay at Base Price (108.00) for the joining month.
    if months_diff == 0:
        return current_value

    # --- STEP C: PERSONAL TENURE GROWTH LOOP ---
    # Rule: "Every person starts with 8%, then 9%, then 10%..."
    
    for m in range(1, months_diff + 1):
        # Calculate Membership Year (1st year, 2nd year, etc.)
        membership_year = ((m - 1) // 12) + 1
        
        # Rate: Start at 8, increase by 1 every year
        rate = 8 + (membership_year - 1)
        
        # Cap at 14%
        if rate > 14: rate = 14
        
        # Monthly Geometric Compounding
        monthly_rate = math.pow(1 + (rate / 100.0), 1/12.0) - 1
        current_value *= (1 + monthly_rate)

    return current_value

def member_pv_overview(request):
    today = timezone.now().date()
    current_real_year = today.year
    start_year = 2026
    
    try: selected_year = int(request.GET.get("year", current_real_year))
    except: selected_year = current_real_year
    if selected_year < start_year: selected_year = start_year
    
    available_years = list(range(start_year, selected_year + 5))

    search_query = request.GET.get("search", "").strip()
    members_qs = Member.objects.all().order_by("join_date")
    if search_query:
        members_qs = members_qs.filter(Q(member_code__icontains=search_query) | Q(full_name__icontains=search_query))

    paginator = Paginator(members_qs, 5)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    member_rows = []

    for member in page_obj:
        # 1. Get Effective Join Date
        raw_date = member.join_date.date() if hasattr(member.join_date, "date") else member.join_date
        effective_join = get_effective_date(raw_date)
        join_month_score = (effective_join.year * 12) + effective_join.month
        
        tx_qs = PVTransaction.objects.filter(member=member)
        total_pv = tx_qs.aggregate(Sum("pv_units"))["pv_units__sum"] or 0

        months_data = []
        year_end_pv = 0
        year_end_val = 0.0

        for m_idx in range(1, 13):
            current_month_score = (selected_year * 12) + m_idx
            
            # --- A. HYPHEN MASK (Pre-Join) ---
            if current_month_score < join_month_score:
                months_data.append({"pv": "-", "value": "-", "is_join": False, "is_anniversary": False})
                continue

            # --- B. CALCULATION ---
            is_join_month = (current_month_score == join_month_score)
            is_anniversary = (selected_year > effective_join.year and m_idx == effective_join.month)

            m_pv = 0
            m_val = 0.0
            has_valid_data = False

            for tx in tx_qs:
                tx_date = get_effective_date(tx.purchase_date)
                
                # === CRITICAL FIX: DATE SYNC ===
                # If transaction date is older than join date (e.g., Tx in Jan, Join in Dec),
                # force the transaction date to match the Join Date.
                # This ensures we get 0 months difference (Base Price) instead of 11 months growth.
                if tx_date < effective_join:
                    tx_date = effective_join
                
                tx_month_score = (tx_date.year * 12) + tx_date.month
                
                if current_month_score >= tx_month_score:
                    # Pass the CORRECTED tx_date to the calculator
                    val = calculate_pv_value_at_date(tx.pv_units, tx_date, selected_year, m_idx)
                    if val is not None:
                        m_pv += tx.pv_units
                        m_val += val
                        has_valid_data = True

            if not has_valid_data:
                months_data.append({"pv": "-", "value": "-", "is_join": False, "is_anniversary": False})
            else:
                months_data.append({
                    "pv": m_pv,
                    "value": f"{m_val:,.2f}",
                    "is_join": is_join_month,
                    "is_anniversary": is_anniversary
                })

            if m_idx == 12:
                year_end_pv = m_pv
                year_end_val = m_val

        member_rows.append({
            "member": member,
            "join_date": effective_join,
            "total_pv": total_pv,
            "months": months_data,
            "year_end_pv": year_end_pv,
            "year_end_val": f"{year_end_val:,.2f}" if year_end_pv != 0 else "-"
        })

    try: base_display = f"{get_base_price_for_purchase_year(selected_year):.2f}"
    except: base_display = "100.00"

    context = {
        "page_obj": page_obj,
        "member_rows": member_rows,
        "selected_year": selected_year,
        "available_years": available_years,
        "month_labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "search_query": search_query,
        "base_price_this_year": base_display
    }
    return render(request, "member_pv_overview.html", context)

# ==============================================================================
#   OTHER VIEWS (Standard Code - kept brief to focus on logic)
# ==============================================================================

def index(request):
    return render(request, "index.html")

def adminlogin(request):
    # Your existing login logic
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        if username == "maxgiveclub@gmail.com" and password == "maxgiveclub@123":
            request.session['admin_user'] = True
            return redirect("project_value")
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, "adminlogin.html")

def logout_admin(request):
    request.session.flush()
    return redirect("adminlogin")

def admin_dashboard(request):
    return render(request, "admin_dashboard.html")

def project_value_view(request):
    # This view shows the static growth table (Image 1 logic)
    base_amt = 1000
    rows = []
    curr = base_amt
    for i in range(1, 11):
        # Determine Rate
        real_year = 2026 + i - 1
        if real_year <= 2027: rate = 8
        else: rate = 9 + (real_year - 2028)
        if rate > 14: rate = 14
        
        interest = curr * (rate / 100.0)
        end_val = curr + interest
        
        rows.append({
            "year": f"Year {i} ({real_year})", 
            "rate": f"{rate}%",
            "start_amt": round(curr),
            "return": round(interest),
            "end_amt": round(end_val)
        })
        curr = end_val
    return render(request, "project_value.html", {"logic_rows": rows, "base_example": base_amt})

# --- MEMBER CRUD (Standard) ---
def add_member(request):
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone_number", "").strip()
        address = request.POST.get("address", "").strip()
        
        try:
            m = Member.objects.create(full_name=full_name, email=email, phone_number=phone, address=address)
            messages.success(request, f"Member {m.member_code} created.")
            return redirect("list_members")
        except IntegrityError:
            messages.error(request, "Email already exists.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
    return render(request, "add_member.html", {"mode": "add"})

def list_members(request):
    q = request.GET.get("search", "")
    qs = Member.objects.all().order_by("-join_date")
    if q: qs = qs.filter(Q(full_name__icontains=q) | Q(member_code__icontains=q))
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    return render(request, "list_members.html", {"page_obj": page_obj, "search": q})

def edit_member(request, pk):
    m = get_object_or_404(Member, pk=pk)
    if request.method == "POST":
        m.full_name = request.POST.get("full_name")
        m.email = request.POST.get("email")
        m.phone_number = request.POST.get("phone_number")
        m.address = request.POST.get("address")
        m.save()
        messages.success(request, "Member updated.")
        return redirect("list_members")
    return render(request, "add_member.html", {"mode": "edit", "member": m, 
                  "full_name": m.full_name, "email": m.email, "phone_number": m.phone_number, "address": m.address})

def delete_member(request, pk):
    m = get_object_or_404(Member, pk=pk)
    if request.method == "POST": m.delete()
    return redirect("list_members")

# --- PV TRANSACTION CRUD (Standard) ---


# --- Helper Function for PV Logic ---
def calculate_pv_rate(target_year):
    """
    Calculates the PV value for a specific year based on the 
    growth projection table (Compounded Annual Growth).
    """
    base_year = 2026
    current_value = 100.00  # Base value in 2026

    if target_year <= base_year:
        return current_value

    # Loop from 2027 up to the target year
    for year in range(base_year + 1, target_year + 1):
        # Determine the growth percentage for this specific year
        if year == 2027:
            percent = 0.08  # 8%
        elif year == 2028:
            percent = 0.09  # 9%
        elif year == 2029:
            percent = 0.10  # 10%
        elif year == 2030:
            percent = 0.11  # 11%
        elif year == 2031:
            percent = 0.12  # 12%
        elif year == 2032:
            percent = 0.13  # 13%
        else:
            percent = 0.14  # 14% (Capped from 2033 onwards)
        
        # Apply compound growth
        current_value = current_value + (current_value * percent)

    return round(current_value, 2)

# --- Views ---

def buy_pv_list(request):
    q = request.GET.get("q", "")
    qs = PVTransaction.objects.select_related("member").order_by("-purchase_date")
    
    if q: 
        qs = qs.filter(Q(member__full_name__icontains=q) | Q(member__member_code__icontains=q))
    
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    
    return render(request, "buy_pv_list.html", {"page_obj": page_obj, "query": q})

def buy_pv_add(request):
    members = Member.objects.all().order_by("member_code")
    
    # Calculate rate based on the Current Year
    current_year = datetime.now().year
    current_rate = calculate_pv_rate(current_year)

    if request.method == "POST":
        try:
            m = Member.objects.get(pk=request.POST.get("member_id"))
            units = int(request.POST.get("pv_units"))
            
            # Create transaction (Assuming purchase_date auto-adds 'now')
            PVTransaction.objects.create(member=m, pv_units=units)
            
            messages.success(request, f"Transaction added at rate {current_rate}.")
            return redirect("buy_pv_list")
        except Exception as e:
            messages.error(request, f"Error adding transaction: {e}")

    # Pass the calculated current_rate to the template
    return render(request, "buy_pv_form.html", {
        "mode": "add", 
        "members": members, 
        "pv_rate": current_rate,
        "current_year": current_year
    })

def buy_pv_edit(request, pk):
    tx = get_object_or_404(PVTransaction, pk=pk)
    members = Member.objects.all()
    
    # For editing, we should likely show the rate OF THE YEAR IT WAS BOUGHT
    # Assuming tx.purchase_date is a DateField or DateTimeField
    tx_year = tx.purchase_date.year if tx.purchase_date else datetime.now().year
    historical_rate = calculate_pv_rate(tx_year)

    if request.method == "POST":
        tx.member = Member.objects.get(pk=request.POST.get("member_id"))
        tx.pv_units = int(request.POST.get("pv_units"))
        tx.save()
        return redirect("buy_pv_list")
        
    return render(request, "buy_pv_form.html", {
        "mode": "edit", 
        "members": members, 
        "selected_member_id": tx.member.id, 
        "pv_units": tx.pv_units,
        "pv_rate": historical_rate # Shows the rate valid for that transaction year
    })

def buy_pv_delete(request, pk):
    tx = get_object_or_404(PVTransaction, pk=pk)
    if request.method == "POST": 
        tx.delete()
    return redirect("buy_pv_list")
# --- MEMBER PORTAL (Standard) ---
def memberlogin(request):
    if request.method == "POST":
        code = request.POST.get("member_code")
        pwd = request.POST.get("password")
        try:
            m = Member.objects.get(member_code=code)
            if m.password == pwd:
                request.session["member_id"] = m.id
                return redirect("member_dashboard")
        except: pass
        messages.error(request, "Invalid credentials")
    return render(request, "memberlogin.html")

 








 # ---------------------------------------------------------
#  ADD THIS FUNCTION (It is missing in your current view)
# ---------------------------------------------------------
def calculate_current_value(pv_units, purchase_date):
    """
    Calculates value based on full years passed + remaining months.
    Logic: User starts at 8%, then 9%... independent of calendar year.
    """
    today = timezone.now().date()
    # Handle both datetime and date objects safely
    p_date = purchase_date.date() if isinstance(purchase_date, datetime) else purchase_date
    
    # If purchase is in future, return buy value
    if p_date > today:
        base_price = get_base_price_for_purchase_year(p_date.year)
        return float(pv_units) * base_price

    # 1. Get Starting Value
    start_price = get_base_price_for_purchase_year(p_date.year)
    current_val = float(pv_units) * float(start_price)

    # 2. Calculate Tenure (Total months passed)
    total_months_diff = (today.year - p_date.year) * 12 + (today.month - p_date.month)

    if total_months_diff <= 0:
        return current_val

    # 3. Apply Growth Month by Month
    # Year 1 (Months 1-12): 8% | Year 2 (Months 13-24): 9% ...
    for m in range(1, total_months_diff + 1):
        year_of_membership = (m - 1) // 12 
        
        rate = 8 + year_of_membership
        if rate > 14: rate = 14
        
        # Monthly Compounding
        monthly_rate = (rate / 100.0) / 12
        current_val = current_val * (1 + monthly_rate)

    return current_val
    



    
# ---------------------------------------------------------
#  VIEW: MEMBER DASHBOARD
# ---------------------------------------------------------
def member_dashboard(request):
    mid = request.session.get("member_id")
    if not mid: 
        return redirect("memberlogin")
    
    member = get_object_or_404(Member, pk=mid)
    txs = PVTransaction.objects.filter(member=member).order_by('-purchase_date')
    
    dashboard_data = []
    overall_total_value = 0 
    
    for tx in txs:
        purchase_year = tx.purchase_date.year
        
        # A. Get Initial Buy Value
        # If I join in 2027, I pay 108.00 per unit.
        start_price = get_base_price_for_purchase_year(purchase_year)
        buy_value = float(tx.pv_units) * float(start_price)

        # B. Get Current Real-Time Value
        curr_val = calculate_current_value(tx.pv_units, tx.purchase_date)
        
        # C. Generate 10-Year Projection Graph
        # Logic: Start at Buy Value. 
        # End of Year 1 = +8%
        # End of Year 2 = +9%
        
        graph_labels = []
        graph_data = []
        
        # Point 0: The Purchase Date
        graph_labels.append(str(purchase_year))
        graph_data.append(round(buy_value, 2))
        
        running_val = buy_value
        
        # Loop for next 10 years
        for i in range(1, 11): 
            future_year = purchase_year + i
            
            # Growth Logic: Year 1 = 8%, Year 2 = 9%...
            growth_rate = 8 + (i - 1) 
            if growth_rate > 14: growth_rate = 14
            
            # Compound the value
            running_val = running_val * (1 + growth_rate / 100.0)
            
            graph_labels.append(str(future_year))
            graph_data.append(round(running_val, 2))

        dashboard_data.append({
            "id": tx.id,
            "date": tx.purchase_date,
            "pv_units": tx.pv_units,
            "buy_value": buy_value,
            "current_value": Decimal(curr_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "graph_labels": json.dumps(graph_labels),
            "graph_data": json.dumps(graph_data)
        })
        
        overall_total_value += curr_val
        
    context = {
        "member": member, 
        "dashboard_data": dashboard_data, 
        "overall_total_value": Decimal(overall_total_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    }
    
    return render(request, "member_dashboard.html", context)



def member_logout(request):
    request.session.flush()
    return redirect("memberlogin")

# ---------------------------------------------------------
#  VIEW: MEMBER CERTIFICATE
# ---------------------------------------------------------
def member_certificate(request, pk):
    mid = request.session.get("member_id")
    if not mid:
        return redirect("memberlogin")
    
    # Fetch specific transaction for this member
    tx = get_object_or_404(PVTransaction, pk=pk, member_id=mid)
    
    # 1. Calculate Original Cost
    # If bought in 2027, use 2027 base price
    start_price = get_base_price_for_purchase_year(tx.purchase_date.year)
    buy_value = float(tx.pv_units) * float(start_price)
    
    context = {
        "member": tx.member,
        "transaction": tx,
        "buy_pv_value": f"{buy_value:,.2f}",
        "purchase_year": tx.purchase_date.year,
        "base_price_at_purchase": start_price, # Optional: display price per unit
        "today": timezone.now().date()
    }
    
    return render(request, "member_certificate.html", context)