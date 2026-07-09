import json
import random
from channels.generic.websocket import AsyncWebsocketConsumer

# Thread-safe global room storage for tracking positions without database writes
ROOM_STATES = {}

class GameConsumer(AsyncWebsocketConsumer):
    # Definition of snakes (head -> tail) and ladders (base -> top)
    SNAKES = {16: 6, 47: 26, 49: 11, 56: 53, 62: 19, 64: 60, 87: 24, 93: 73, 95: 75, 98: 78}
    LADDERS = {1: 38, 4: 14, 9: 31, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 80: 100}

    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'game_{self.room_name}'

        # Initialize the global room state if it doesn't exist
        if self.room_name not in ROOM_STATES:
            ROOM_STATES[self.room_name] = {
                "players": [], # list of channel_names
                "positions": {}, # channel_name -> int position
                "turn_index": 0,
                "game_over": False
            }

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        state = ROOM_STATES[self.room_name]
        # Allow entry up to standard capacity limits
        if len(state["players"]) < 4:
            state["players"].append(self.channel_name)
            player_num = len(state["players"])
            state["positions"][self.channel_name] = 1
            
            # Send assigned identity metadata directly back to the freshly joined client
            await self.send(text_data=json.dumps({
                'type': 'init',
                'player_identity': f"Player {player_num}"
            }))
            
            # Update all room connected displays
            await self.broadcast_state()

    async def disconnect(self, close_code):
        state = ROOM_STATES.get(self.room_name)
        if state and self.channel_name in state["players"]:
            idx = state["players"].index(self.channel_name)
            state["players"].remove(self.channel_name)
            if self.channel_name in state["positions"]:
                del state["positions"][self.channel_name]
            
            if len(state["players"]) == 0:
                del ROOM_STATES[self.room_name]
            else:
                if state["turn_index"] >= len(state["players"]):
                    state["turn_index"] = 0
                await self.broadcast_state()

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get('action')
        state = ROOM_STATES.get(self.room_name)

        if not state or state["game_over"]:
            return

        # Core Turn Validation Check
        current_player_channel = state["players"][state["turn_index"]]
        if self.channel_name != current_player_channel:
            return # Block illegal turns

        if action == 'roll_dice':
            dice_value = random.randint(1, 6)
            current_pos = state["positions"][self.channel_name]
            
            target_pos = current_pos + dice_value
            log_msg = f"Player {state['players'].index(self.channel_name)+1} rolled a {dice_value}."

            if target_pos <= 100:
                # Process Snake or Ladder interactions
                if target_pos in self.SNAKES:
                    target_pos = self.SNAKES[target_pos]
                    log_msg += f" Oh no, a snake bit them down to {target_pos}!"
                elif target_pos in self.LADDERS:
                    target_pos = self.LADDERS[target_pos]
                    log_msg += f" Great! Climbed a ladder up to {target_pos}!"
                else:
                    log_msg += f" Moved to {target_pos}."
                
                state["positions"][self.channel_name] = target_pos

                if target_pos == 100:
                    state["game_over"] = True
                    log_msg += " WINS THE GAME! 🏆"

            else:
                log_msg += " Rolled too high to move!"

            # Increment turn execution to the next available index
            if not state["game_over"]:
                state["turn_index"] = (state["turn_index"] + 1) % len(state["players"])

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'game_update',
                    'state': self.compile_state_data(state),
                    'log': log_msg,
                    'dice': dice_value
                }
            )

    async def broadcast_state(self):
        state = ROOM_STATES.get(self.room_name)
        if state:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'game_update',
                    'state': self.compile_state_data(state),
                    'log': "A new player connected to the room.",
                    'dice': "-"
                }
            )

    def compile_state_data(self, state):
        # Format map objects to arrays using clean text keys for plain JS consumption
        client_positions = {}
        for ch_name, pos in state["positions"].items():
            p_index = state["players"].index(ch_name) + 1
            client_positions[f"Player {p_index}"] = pos
            
        current_turn_label = "Waiting for players..."
        if state["players"]:
            curr_turn_ch = state["players"][state["turn_index"]]
            current_turn_label = f"Player {state['players'].index(curr_turn_ch) + 1}"

        return {
            "positions": client_positions,
            "current_turn": current_turn_label,
            "game_over": state["game_over"]
        }

    async def game_update(self, event):
        await self.send(text_data=json.dumps(event))