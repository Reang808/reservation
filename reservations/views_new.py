from django.shortcuts import render


def calendar_new(request):
    return render(request, 'reservations/calendar_new.html')