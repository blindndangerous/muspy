from django.http import JsonResponse
from django.shortcuts import render


def health(request):
    return JsonResponse({"status": "ok"})


def home(request):
    return render(request, "releasewatch/home.html", {"recent_events": [], "upcoming_events": []})


def release_list(request):
    return render(request, "releasewatch/release_list.html", {"events": []})
