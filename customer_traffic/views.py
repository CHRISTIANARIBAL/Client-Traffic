from django.shortcuts import render
from django.http import JsonResponse
from .services.traffic_cache import get_live_traffic
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import redirect, render
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login
from django.shortcuts import get_object_or_404
from datetime import timedelta
from .models import *

@login_required
def dashboard(request):
    return render(request, "registration/dashboard.html")

def is_admin(user):
    return user.is_superuser

@login_required
@user_passes_test(is_admin)
def client_traffic_detail(request, client_id):
    profile = get_object_or_404(
        CustomerProfile.objects.select_related("user"),
        id=client_id
    )
    return render(
        request,
        "registration/client_traffic_detail.html",
        {"client": profile}
    )

@login_required
def client_traffic(request):
    try:
        profile = request.user.customerprofile
    except CustomerProfile.DoesNotExist:
        print(
            "TRAFFIC API DENIED:",
            "user=", request.user.username,
            "authenticated=", request.user.is_authenticated,
            "reason=No customer profile",
        )
        return JsonResponse({
            "error": "No customer profile is linked to this account."
        }, status=403)

    # Read the latest cached reading instead of querying MikroTik.
    live = get_live_traffic(profile.pppoe_username)

    if live is None:
        return JsonResponse({
            "error": "Live traffic is temporarily unavailable. Please try again."
        }, status=503)

    response = {
        "ac": live.get("ac"),
        "pppoe_username": profile.pppoe_username,
        "upload": int(live.get("upload", 0)),
        "download": int(live.get("download", 0)),
        "timestamp": live.get("timestamp"),
    }

    # Load history only when the dashboard explicitly requests it.
    if request.GET.get("history") == "1":
        cutoff = timezone.now() - timezone.timedelta(minutes=5)

        history = TrafficHistory.objects.filter(
            customer=profile,
            timestamp__gte=cutoff,
        ).order_by("timestamp").values(
            "timestamp", "upload", "download", "ac"
        )

        response["history"] = [
            {
                "time": item["timestamp"].isoformat(),
                "upload": item["upload"],
                "download": item["download"],
                "ac": item["ac"],
            }
            for item in history
        ]

    return JsonResponse(response)


@login_required
@user_passes_test(is_admin)
def client_list(request):
    clients = CustomerProfile.objects.select_related("user").order_by(
        "customer_name"
    )

    return render(
        request,
        "registration/client_list.html",
        {
            "clients": clients
        }
    )


@login_required
@user_passes_test(is_admin)
def client_add(request):
    User = get_user_model()

    if request.method == "POST":
        customer_name = request.POST.get("customer_name", "").strip()
        username = request.POST.get("username", "").strip()
        pppoe_username = request.POST.get("pppoe_username", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not customer_name:
            messages.error(request, "Customer name is required.")
            return redirect("client_add")

        if not username:
            messages.error(request, "Username is required.")
            return redirect("client_add")

        if not pppoe_username:
            messages.error(request, "PPPoE username is required.")
            return redirect("client_add")

        if not password:
            messages.error(request, "Password is required.")
            return redirect("client_add")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("client_add")

        if User.objects.filter(username=username).exists():
            messages.error(request, "That username already exists.")
            return redirect("client_add")

        if CustomerProfile.objects.filter(
            pppoe_username=pppoe_username
        ).exists():
            messages.error(request, "That PPPoE username is already registered.")
            return redirect("client_add")

        user = User.objects.create_user(
            username=username,
            password=password
        )

        CustomerProfile.objects.create(
            user=user,
            customer_name=customer_name,
            pppoe_username=pppoe_username
        )

        messages.success(
            request,
            f"{customer_name} was added successfully."
        )

        return redirect("client_list")

    return render(
        request,
        "registration/client_add.html"
    )


def admin_login(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("client_list")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)

        if user and user.is_active and user.is_superuser:
            login(request, user)
            return redirect("client_list")

        messages.error(request, "Invalid admin credentials.")

    return render(request, "registration/admin_login.html")


@login_required
@user_passes_test(is_admin)
def client_edit(request, client_id):
    profile = get_object_or_404(
        CustomerProfile.objects.select_related("user"),
        id=client_id
    )
    user = profile.user

    if request.method == "POST":
        customer_name = request.POST.get("customer_name", "").strip()
        username = request.POST.get("username", "").strip()
        pppoe_username = request.POST.get("pppoe_username", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")
        is_active = request.POST.get("is_active") == "on"

        if not customer_name or not username or not pppoe_username:
            messages.error(request, "Name, login username, and PPPoE username are required.")
            return redirect("client_edit", client_id=client_id)

        if get_user_model().objects.filter(username=username).exclude(id=user.id).exists():
            messages.error(request, "That login username is already in use.")
            return redirect("client_edit", client_id=client_id)

        if CustomerProfile.objects.filter(pppoe_username=pppoe_username).exclude(id=profile.id).exists():
            messages.error(request, "That PPPoE username is already registered.")
            return redirect("client_edit", client_id=client_id)

        if password or confirm_password:
            if password != confirm_password:
                messages.error(request, "Passwords do not match.")
                return redirect("client_edit", client_id=client_id)

            user.set_password(password)

        profile.customer_name = customer_name
        profile.pppoe_username = pppoe_username
        profile.save()

        user.username = username
        user.is_active = is_active
        user.save()

        messages.success(request, f"{customer_name} was updated successfully.")
        return redirect("client_list")

    return render(
        request,
        "registration/client_edit.html",
        {"client": profile}
    )


@login_required
@user_passes_test(is_admin)
def client_delete(request, client_id):
    profile = get_object_or_404(CustomerProfile, id=client_id)

    if request.method == "POST":
        customer_name = profile.customer_name
        user = profile.user
        profile.delete()
        user.delete()

        messages.success(
            request,
            f"{customer_name} and their linked traffic history were deleted."
        )
        return redirect("client_list")

    return render(
        request,
        "registration/client_delete.html",
        {"client": profile}
    )


@login_required
@user_passes_test(is_admin)
def client_traffic_history(request, client_id):
    profile = get_object_or_404(
        CustomerProfile,
        pk=client_id,
    )

    range_options = {
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "2h": timedelta(hours=2),
        "3h": timedelta(hours=3),
        "4h": timedelta(hours=4),
        "5h": timedelta(hours=5),
        "6h": timedelta(hours=6),
        "12h": timedelta(hours=12),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "15d": timedelta(days=15),
        "30d": timedelta(days=30),
    }

    selected_range = request.GET.get("range", "30m")
    time_window = range_options.get(
        selected_range,
        timedelta(minutes=30),
    )

    start_time = timezone.now() - time_window

    # Filter by the requested period first.
    records = list(
        TrafficHistory.objects.filter(
            customer=profile,
            timestamp__gte=start_time,
        ).order_by("timestamp")
    )

    # Keep at most 300 evenly spaced points across the full period.
    max_points = 300

    if len(records) > max_points:
        last_index = len(records) - 1
        records = [
            records[round(i * last_index / (max_points - 1))]
            for i in range(max_points)
        ]

    # The newest saved sample is used for the current-value cards.
    latest = TrafficHistory.objects.filter(
        customer=profile,
    ).order_by("-timestamp").first()

    return JsonResponse({
        "client_id": profile.pk,
        "current": {
            "upload": latest.upload,
            "download": latest.download,
        } if latest else None,
        "history": [
            {
                "timestamp": item.timestamp.isoformat(),
                "upload": item.upload,
                "download": item.download,
                "ac": item.ac,
            }
            for item in records
        ],
    })
