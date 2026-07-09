from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Changed from as_backend_consumer() to as_asgi()
    re_path(r'ws/game/(?P<room_name>\w+)/$', consumers.GameConsumer.as_asgi()),
]