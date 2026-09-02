import json
import random
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer

# Global room storage: room_name -> room_state dict
ROOM_STATES = {}

AVAILABLE_COLORS = [
    {"bg": "#ef4444", "name": "Coral Red"},
    {"bg": "#3b82f6", "name": "Ocean Blue"},
    {"bg": "#eab308", "name": "Sun Yellow"},
    {"bg": "#a855f7", "name": "Cosmic Purple"},
    {"bg": "#10b981", "name": "Emerald Green"},
    {"bg": "#f97316", "name": "Vibrant Orange"},
]

BOT_NAMES = ['Cyber Bot 🤖', 'Neo Bot ⚡', 'Pixel Bot 👾', 'Turbo Bot 🚀']

class GameConsumer(AsyncWebsocketConsumer):
    # Definition of snakes (head -> tail) and ladders (base -> top)
    SNAKES = {
        16: 6,
        47: 26,
        49: 11,
        56: 53,
        62: 19,
        64: 60,
        87: 24,
        93: 73,
        95: 75,
        98: 78
    }
    LADDERS = {
        4: 14,
        9: 31,
        21: 42,
        28: 84,
        36: 44,
        51: 67,
        71: 91,
        80: 100
    }

    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'game_{self.room_name}'

        if self.room_name not in ROOM_STATES:
            ROOM_STATES[self.room_name] = {
                "host_id": self.channel_name,
                "players": [],
                "target_players": 2, # Default 2 players, configurable to 3 or 4
                "status": "waiting",  # "waiting", "playing", "finished"
                "turn_index": 0,
                "winner": None,
                "bot_count": 0,
                "rolling_lock": False,
            }

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        state = ROOM_STATES.get(self.room_name)
        if state:
            player_to_remove = None
            for p in state["players"]:
                if p["id"] == self.channel_name:
                    player_to_remove = p
                    break

            if player_to_remove:
                state["players"].remove(player_to_remove)

                # Reassign host if host disconnected
                if state["host_id"] == self.channel_name:
                    human_players = [p for p in state["players"] if not p["is_bot"]]
                    if human_players:
                        state["host_id"] = human_players[0]["id"]
                        human_players[0]["is_host"] = True
                    else:
                        state["host_id"] = None

                # Clean up if room is completely empty
                human_players = [p for p in state["players"] if not p["is_bot"]]
                if len(human_players) == 0:
                    ROOM_STATES.pop(self.room_name, None)
                    await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
                    return

                # Adjust turn index if out of bounds
                if state["turn_index"] >= len(state["players"]):
                    state["turn_index"] = 0

                await self.broadcast_state(
                    f"{player_to_remove['name']} left the room."
                )

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        action = data.get('action')
        state = ROOM_STATES.get(self.room_name)
        if not state:
            return

        if action == 'join':
            player_name = data.get('name', '').strip() or f"Player {len(state['players']) + 1}"
            avatar = data.get('avatar', '🦊')
            preferred_color = data.get('color', None)
            target_players = int(data.get('target', 2))
            is_instant_bot = (data.get('mode') == 'instant_bot')

            # Check if player is reconnecting
            existing_player = next((p for p in state["players"] if p["id"] == self.channel_name), None)
            if existing_player:
                existing_player["name"] = player_name
                existing_player["avatar"] = avatar
                if preferred_color:
                    existing_player["color"] = preferred_color
            else:
                if len(state["players"]) < 4:
                    is_host = (state["host_id"] == self.channel_name) or (len(state["players"]) == 0)
                    if is_host:
                        state["host_id"] = self.channel_name
                        state["target_players"] = max(2, min(4, target_players))

                    # Determine color: use preferred if available, otherwise pick next available color
                    used_colors = [p["color"] for p in state["players"]]
                    chosen_color = preferred_color
                    if not chosen_color or chosen_color in used_colors:
                        for c in AVAILABLE_COLORS:
                            if c["bg"] not in used_colors:
                                chosen_color = c["bg"]
                                break
                        if not chosen_color:
                            chosen_color = AVAILABLE_COLORS[len(state["players"]) % len(AVAILABLE_COLORS)]["bg"]

                    new_player = {
                        "id": self.channel_name,
                        "name": player_name,
                        "avatar": avatar,
                        "color": chosen_color,
                        "position": 1,
                        "is_bot": False,
                        "is_host": is_host,
                    }
                    state["players"].append(new_player)

                    # If Instant Bot mode requested by host, automatically add AI bot
                    if is_instant_bot and is_host and len(state["players"]) == 1:
                        self.add_bot_sync(state)

            # Send init response to this client
            await self.send(text_data=json.dumps({
                'type': 'init',
                'my_id': self.channel_name,
                'is_host': (state["host_id"] == self.channel_name),
                'snakes': self.SNAKES,
                'ladders': self.LADDERS,
                'available_colors': AVAILABLE_COLORS,
                'state': self.compile_state(state)
            }))

            # Broadcast updated state to all players in the room
            await self.broadcast_state(f"{player_name} joined the arena.")

        elif action == 'change_color':
            new_color = data.get('color')
            if new_color and state["status"] == "waiting":
                player = next((p for p in state["players"] if p["id"] == self.channel_name), None)
                if player:
                    player["color"] = new_color
                    await self.broadcast_state(f"{player['name']} changed color.")

        elif action == 'set_target_players':
            if state["host_id"] == self.channel_name and state["status"] == "waiting":
                target = int(data.get('target', 2))
                state["target_players"] = max(2, min(4, target))
                await self.broadcast_state(f"Host set target players to {state['target_players']}.")

        elif action == 'start_game':
            if state["host_id"] == self.channel_name:
                # If room has fewer players than target_players, auto-fill remaining slots with AI Bots
                while len(state["players"]) < state["target_players"]:
                    self.add_bot_sync(state)

                if len(state["players"]) < 2:
                    self.add_bot_sync(state)

                state["status"] = "playing"
                state["turn_index"] = 0
                state["winner"] = None
                state["rolling_lock"] = False
                for p in state["players"]:
                    p["position"] = 1

                await self.broadcast_state("Game started! All players are ready. Roll to begin! 🎲")

                # If first player is an AI Bot, trigger their turn
                curr_player = state["players"][state["turn_index"]]
                if curr_player["is_bot"]:
                    asyncio.create_task(self.trigger_bot_turn())

        elif action == 'add_bot':
            if state["host_id"] == self.channel_name and len(state["players"]) < 4 and state["status"] == "waiting":
                self.add_bot_sync(state)
                await self.broadcast_state("AI Bot added to the room.")

        elif action == 'remove_bot':
            if state["host_id"] == self.channel_name and state["status"] == "waiting":
                for p in reversed(state["players"]):
                    if p["is_bot"]:
                        state["players"].remove(p)
                        await self.broadcast_state(f"{p['name']} was removed.")
                        break

        elif action == 'roll_dice':
            if state["status"] != "playing" or state["rolling_lock"]:
                return

            if state["turn_index"] >= len(state["players"]):
                return

            curr_player = state["players"][state["turn_index"]]
            if curr_player["id"] != self.channel_name:
                return  # Block turn if not active player

            await self.execute_roll(curr_player)

        elif action == 'send_reaction':
            emoji = data.get('emoji', '🔥')
            sender = next((p for p in state["players"] if p["id"] == self.channel_name), None)
            sender_name = sender["name"] if sender else "Player"
            sender_color = sender["color"] if sender else "#38bdf8"
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'reaction_event',
                    'sender_name': sender_name,
                    'sender_color': sender_color,
                    'emoji': emoji,
                    'player_id': self.channel_name
                }
            )

        elif action == 'restart_game':
            if len(state["players"]) > 0:
                state["status"] = "playing"
                state["turn_index"] = 0
                state["winner"] = None
                state["rolling_lock"] = False
                for p in state["players"]:
                    p["position"] = 1

                await self.broadcast_state("New match started! All tokens returned to tile 1. 🔄")

                curr_player = state["players"][state["turn_index"]]
                if curr_player["is_bot"]:
                    asyncio.create_task(self.trigger_bot_turn())

    def add_bot_sync(self, state):
        if len(state["players"]) >= 4:
            return
        state["bot_count"] += 1
        bot_idx = state["bot_count"]
        bot_name = BOT_NAMES[(bot_idx - 1) % len(BOT_NAMES)]
        avatar = '🤖'

        # Pick color not already in use
        used_colors = [p["color"] for p in state["players"]]
        chosen_color = AVAILABLE_COLORS[len(state["players"]) % len(AVAILABLE_COLORS)]["bg"]
        for c in AVAILABLE_COLORS:
            if c["bg"] not in used_colors:
                chosen_color = c["bg"]
                break

        bot_player = {
            "id": f"bot_{bot_idx}_{random.randint(1000, 9999)}",
            "name": bot_name,
            "avatar": avatar,
            "color": chosen_color,
            "position": 1,
            "is_bot": True,
            "is_host": False,
        }
        state["players"].append(bot_player)

    async def execute_roll(self, player):
        state = ROOM_STATES.get(self.room_name)
        if not state:
            return

        state["rolling_lock"] = True
        dice_value = random.randint(1, 6)
        start_pos = player["position"]
        target_pos = start_pos + dice_value
        intermediate_pos = target_pos
        final_pos = target_pos
        move_type = "normal"
        log_msg = f"{player['name']} rolled a {dice_value}."

        if target_pos > 100:
            intermediate_pos = start_pos
            final_pos = start_pos
            move_type = "overshoot"
            log_msg += f" Needed {100 - start_pos} to reach 100, stayed at {start_pos}."
        else:
            if target_pos in self.SNAKES:
                final_pos = self.SNAKES[target_pos]
                move_type = "snake"
                log_msg += f" Landed on {target_pos} and got bitten by a 🐍 SNAKE down to {final_pos}!"
            elif target_pos in self.LADDERS:
                final_pos = self.LADDERS[target_pos]
                move_type = "ladder"
                log_msg += f" Landed on {target_pos} and climbed a 🪜 LADDER up to {final_pos}!"
            else:
                log_msg += f" Moved to {final_pos}."

            player["position"] = final_pos

            if final_pos == 100:
                state["status"] = "finished"
                state["winner"] = player["name"]
                move_type = "win"
                log_msg += f" 👑 {player['name']} reached 100 and WON THE MATCH! 🏆"

        # Advance turn if game not over
        if state["status"] != "finished":
            state["turn_index"] = (state["turn_index"] + 1) % len(state["players"])

        # Broadcast the move event to EVERY connected client in real-time
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'move_event',
                'player_id': player["id"],
                'player_name': player["name"],
                'player_avatar': player["avatar"],
                'player_color': player["color"],
                'dice': dice_value,
                'start_pos': start_pos,
                'intermediate_pos': intermediate_pos,
                'final_pos': final_pos,
                'move_type': move_type,
                'log': log_msg,
                'state': self.compile_state(state)
            }
        )

        state["rolling_lock"] = False

        # If next player is an AI Bot, trigger their automated turn after delay
        if state["status"] == "playing":
            next_player = state["players"][state["turn_index"]]
            if next_player["is_bot"]:
                asyncio.create_task(self.trigger_bot_turn())

    async def trigger_bot_turn(self):
        await asyncio.sleep(2.3)
        state = ROOM_STATES.get(self.room_name)
        if not state or state["status"] != "playing":
            return

        if state["turn_index"] < len(state["players"]):
            curr_player = state["players"][state["turn_index"]]
            if curr_player["is_bot"]:
                await self.execute_roll(curr_player)

    def compile_state(self, state):
        current_turn_player = None
        if state["players"] and state["turn_index"] < len(state["players"]):
            current_turn_player = state["players"][state["turn_index"]]

        return {
            "status": state["status"],
            "host_id": state["host_id"],
            "target_players": state.get("target_players", 2),
            "turn_index": state["turn_index"],
            "current_turn_name": current_turn_player["name"] if current_turn_player else "Waiting...",
            "current_turn_id": current_turn_player["id"] if current_turn_player else None,
            "current_turn_color": current_turn_player["color"] if current_turn_player else "#94a3b8",
            "winner": state["winner"],
            "players": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "avatar": p["avatar"],
                    "color": p["color"],
                    "position": p["position"],
                    "is_bot": p["is_bot"],
                    "is_host": p["is_host"]
                }
                for p in state["players"]
            ]
        }

    async def broadcast_state(self, log_message=""):
        state = ROOM_STATES.get(self.room_name)
        if state:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'state_event',
                    'state': self.compile_state(state),
                    'log': log_message
                }
            )

    async def state_event(self, event):
        await self.send(text_data=json.dumps(event))

    async def move_event(self, event):
        await self.send(text_data=json.dumps(event))

    async def reaction_event(self, event):
        await self.send(text_data=json.dumps(event))