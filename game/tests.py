import json
from django.test import TestCase
from channels.testing import WebsocketCommunicator
from mysite.asgi import application
from game.consumers import ROOM_STATES

class GameConsumerTests(TestCase):
    def setUp(self):
        ROOM_STATES.clear()

    async def test_room_creation_and_host_assignment(self):
        communicator = WebsocketCommunicator(application, "/ws/game/TEST01/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Join as first player (Host)
        await communicator.send_json_to({
            "action": "join",
            "name": "Alice",
            "avatar": "🦊",
            "color": "#ef4444",
            "target": 2,
            "mode": "create"
        })

        # Receive init event
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "init")
        self.assertTrue(response["is_host"])
        self.assertIn("snakes", response)
        self.assertIn("ladders", response)

        # Receive state broadcast
        state_resp = await communicator.receive_json_from()
        self.assertEqual(state_resp["type"], "state_event")
        self.assertEqual(state_resp["state"]["status"], "waiting")
        self.assertEqual(len(state_resp["state"]["players"]), 1)
        self.assertEqual(state_resp["state"]["players"][0]["name"], "Alice")
        self.assertTrue(state_resp["state"]["players"][0]["is_host"])

        await communicator.disconnect()

    async def test_second_player_join_and_bot_controls(self):
        # 1. Host joins
        host_comm = WebsocketCommunicator(application, "/ws/game/TEST02/")
        await host_comm.connect()
        await host_comm.send_json_to({
            "action": "join",
            "name": "HostPlayer",
            "avatar": "🦁",
            "color": "#ef4444",
            "target": 3,
            "mode": "create"
        })
        await host_comm.receive_json_from() # init
        await host_comm.receive_json_from() # state_event

        # 2. Add AI Bot
        await host_comm.send_json_to({"action": "add_bot"})
        bot_state = await host_comm.receive_json_from()
        self.assertEqual(len(bot_state["state"]["players"]), 2)
        self.assertTrue(bot_state["state"]["players"][1]["is_bot"])

        # 3. Guest joins
        guest_comm = WebsocketCommunicator(application, "/ws/game/TEST02/")
        await guest_comm.connect()
        await guest_comm.send_json_to({
            "action": "join",
            "name": "GuestPlayer",
            "avatar": "🐼",
            "color": "#3b82f6",
            "target": 3,
            "mode": "join"
        })

        guest_init = await guest_comm.receive_json_from()
        self.assertFalse(guest_init["is_host"])

        # Both host and guest receive the broadcast from guest joining
        host_sees_guest = await host_comm.receive_json_from()
        self.assertEqual(len(host_sees_guest["state"]["players"]), 3)

        guest_sees_all = await guest_comm.receive_json_from()
        self.assertEqual(len(guest_sees_all["state"]["players"]), 3)

        # 4. Host starts game
        await host_comm.send_json_to({"action": "start_game"})
        game_start_state = await host_comm.receive_json_from()
        self.assertEqual(game_start_state["state"]["status"], "playing")
        self.assertEqual(game_start_state["state"]["turn_index"], 0)

        # Guest also sees start_game
        await guest_comm.receive_json_from()

        # 5. First player rolls dice
        await host_comm.send_json_to({"action": "roll_dice"})
        move_resp = await host_comm.receive_json_from()
        self.assertEqual(move_resp["type"], "move_event")
        self.assertIn("dice", move_resp)
        self.assertIn("final_pos", move_resp)
        self.assertGreaterEqual(move_resp["dice"], 1)
        self.assertLessEqual(move_resp["dice"], 6)

        await guest_comm.disconnect()
        await host_comm.disconnect()

    async def test_restart_game_flow(self):
        comm = WebsocketCommunicator(application, "/ws/game/TEST03/")
        await comm.connect()
        await comm.send_json_to({
            "action": "join",
            "name": "PlayerOne",
            "target": 2,
            "mode": "instant_bot"
        })
        await comm.receive_json_from() # init
        await comm.receive_json_from() # state

        # Start game
        await comm.send_json_to({"action": "start_game"})
        await comm.receive_json_from() # state

        # Restart game
        await comm.send_json_to({"action": "restart_game"})
        restart_state = await comm.receive_json_from()
        self.assertEqual(restart_state["state"]["status"], "playing")
        self.assertEqual(restart_state["state"]["players"][0]["position"], 1)

        await comm.disconnect()

    def test_snake_and_ladder_map_integrity(self):
        from game.consumers import GameConsumer
        # Ensure all snake heads lead to lower tiles
        for head, tail in GameConsumer.SNAKES.items():
            self.assertGreater(head, tail, f"Snake head {head} must be higher than tail {tail}")
            self.assertGreaterEqual(tail, 1)
            self.assertLessEqual(head, 99)

        # Ensure all ladder bases lead to higher tiles
        for base, top in GameConsumer.LADDERS.items():
            self.assertLess(base, top, f"Ladder base {base} must be lower than top {top}")
            self.assertGreaterEqual(base, 1)
            self.assertLessEqual(top, 100)

        # Ensure no tile is both a snake head and ladder base
        snake_heads = set(GameConsumer.SNAKES.keys())
        ladder_bases = set(GameConsumer.LADDERS.keys())
        self.assertEqual(len(snake_heads.intersection(ladder_bases)), 0)

    async def test_two_player_room_strict_capacity_and_third_player_rejection(self):
        # 1. Admin creates a 2-player room
        admin_comm = WebsocketCommunicator(application, "/ws/game/TEST2P/")
        await admin_comm.connect()
        await admin_comm.send_json_to({
            "action": "join",
            "name": "AdminPlayer",
            "avatar": "🦊",
            "color": "#ef4444",
            "target": 2,
            "mode": "create"
        })
        admin_init = await admin_comm.receive_json_from()
        self.assertTrue(admin_init["is_host"])
        admin_state1 = await admin_comm.receive_json_from()
        self.assertEqual(len(admin_state1["state"]["players"]), 1)
        self.assertEqual(admin_state1["state"]["target_players"], 2)

        # 2. Admin attempts to start game early - must be blocked with error_msg, NO bot added
        await admin_comm.send_json_to({"action": "start_game"})
        early_err = await admin_comm.receive_json_from()
        self.assertEqual(early_err["type"], "error_msg")
        self.assertIn("Waiting for all players to join", early_err["message"])
        # Room must still have only 1 player, NOT 2 with a bot
        self.assertEqual(len(ROOM_STATES["TEST2P"]["players"]), 1)

        # 3. Friend enters the room code and joins as Player 2
        friend_comm = WebsocketCommunicator(application, "/ws/game/TEST2P/")
        await friend_comm.connect()
        await friend_comm.send_json_to({
            "action": "join",
            "name": "FriendPlayer",
            "avatar": "🦁",
            "color": "#3b82f6",
            "target": 2,
            "mode": "join"
        })
        friend_init = await friend_comm.receive_json_from()
        self.assertFalse(friend_init["is_host"])

        # Both receive state update with exactly 2 players
        admin_sees_friend = await admin_comm.receive_json_from()
        self.assertEqual(len(admin_sees_friend["state"]["players"]), 2)
        friend_sees_all = await friend_comm.receive_json_from()
        self.assertEqual(len(friend_sees_all["state"]["players"]), 2)

        # Verify both players are human, no bots
        self.assertFalse(admin_sees_friend["state"]["players"][0]["is_bot"])
        self.assertFalse(admin_sees_friend["state"]["players"][1]["is_bot"])

        # 4. Third player attempts to join - MUST be rejected with room_full!
        third_comm = WebsocketCommunicator(application, "/ws/game/TEST2P/")
        await third_comm.connect()
        await third_comm.send_json_to({
            "action": "join",
            "name": "ThirdIntruder",
            "avatar": "🐼",
            "color": "#10b981",
            "target": 2,
            "mode": "join"
        })
        rejected_resp = await third_comm.receive_json_from()
        self.assertEqual(rejected_resp["type"], "room_full")
        self.assertIn("room is full", rejected_resp["message"])

        # Confirm room STILL has exactly 2 players
        self.assertEqual(len(ROOM_STATES["TEST2P"]["players"]), 2)

        # 5. Admin starts the game now that 2/2 players are ready
        await admin_comm.send_json_to({"action": "start_game"})
        start_state_admin = await admin_comm.receive_json_from()
        self.assertEqual(start_state_admin["state"]["status"], "playing")
        self.assertEqual(len(start_state_admin["state"]["players"]), 2)

        start_state_friend = await friend_comm.receive_json_from()
        self.assertEqual(start_state_friend["state"]["status"], "playing")

        await third_comm.disconnect()
        await friend_comm.disconnect()
        await admin_comm.disconnect()


