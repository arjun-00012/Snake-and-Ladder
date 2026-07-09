import random
import string
from django.shortcuts import render, redirect

def lobby(request):
    if request.method == "POST":
        room_code = request.POST.get("room_code", "").strip().upper()
        if not room_code:
            room_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return redirect('game_room', room_code=room_code)
    return render(request, 'lobby.html')

def game_room(request, room_code):
    return render(request, 'room.html', {'room_code': room_code})