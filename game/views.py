import random
import string
import urllib.parse
from django.shortcuts import render, redirect

def lobby(request):
    if request.method == "POST":
        room_code = request.POST.get("room_code", "").strip().upper()
        player_name = request.POST.get("player_name", "").strip() or "Player"
        avatar = request.POST.get("avatar", "👑")
        color = request.POST.get("color", "#1e40af")
        target_players = request.POST.get("target_players", "2")
        action = request.POST.get("action", "create")
        
        if not room_code or action == "create":
            room_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            mode = "create"
        else:
            mode = "join"
            
        params = urllib.parse.urlencode({
            'name': player_name,
            'avatar': avatar,
            'color': color,
            'target': target_players,
            'mode': mode
        })
        return redirect(f'/room/{room_code}/?{params}')
    return render(request, 'lobby.html')

def game_room(request, room_code):
    player_name = request.GET.get('name', 'Player').strip() or 'Player'
    avatar = request.GET.get('avatar', '👑')
    color = request.GET.get('color', '#1e40af')
    target = request.GET.get('target', '2')
    mode = request.GET.get('mode', 'create')
    
    return render(request, 'room.html', {
        'room_code': room_code,
        'default_player_name': player_name,
        'default_avatar': avatar,
        'default_color': color,
        'default_target': target,
        'default_mode': mode
    })