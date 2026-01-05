import json
import os
import random
import sys
from typing import Any

SAVE_FILE = "savegame.json"


def load_world(filename: str) -> dict:
	with open(filename, "r", encoding="utf-8") as f:
		return json.load(f)


def normalise(text: str) -> str:
	return text.strip().lower()


def make_bar(percent: int, width: int = 20) -> str:
	percent = max(0, min(100, int(percent)))
	filled = int(round(width * (percent / 100)))
	return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def show_health(state: dict) -> None:
	hp = int(state.get("health", 100))
	print(f"Health: {make_bar(hp)} {hp}%")


def enemy_status(enemy: dict) -> str:
	return f"{enemy['name']} HP {enemy['hp']}/{enemy['max_hp']} | XP {enemy.get('xp_reward', 0)}"


def describe_room(world: dict, state: dict) -> None:
	room_name = state["current_room"]
	room = world["rooms"][room_name]

	print(f"\n== {room_name} ==")

	# Dark-room behaviour (simple + readable)
	if room_name == "Dungeon" and room_name not in state["lit_rooms"]:
		print("The dungeon is pitch black. You can hear chains clink, but you can't see the way.")
		print("Maybe a torch (or lantern) would help.")
		print("You see: shapes you can't quite make out.")
		print("Exits: ...somewhere. (Try: use torch / use lantern)")
		return

	print(room["description"])

	items = room.get("items", [])
	print("You see:", ", ".join(items) if items else "nothing interesting.")

	exits = room.get("exits", {})
	print("Exits:", ", ".join(exits.keys()) if exits else "none.")


def is_exit_locked(world: dict, from_room: str, direction: str) -> dict | None:
	for lock in world.get("locked_exits", []):
		if lock.get("from") == from_room and lock.get("direction") == direction:
			return lock
	return None


def has_equivalent_item(state: dict, required: str) -> bool:
	"""
	Allows small "equivalents" without changing the JSON format.
	Example: if a lock requires 'lantern', a 'torch' should also count.
	"""
	inv = set(state.get("inventory", []))
	if required in inv:
		return True

	# Equivalents
	equivalents = {
		"lantern": {"torch"},
	}
	return required in equivalents and bool(inv.intersection(equivalents[required]))


def is_exit_unlocked(state: dict, from_room: str, direction: str) -> bool:
	return (from_room, direction) in state.get("unlocked_exits", set())


def can_go(world: dict, state: dict, direction: str) -> tuple[bool, str]:
	current = state["current_room"]
	exits = world["rooms"][current].get("exits", {})

	if direction not in exits:
		return False, "You can't go that way."

	# Simple "darkness blocks the way" example
	if current == "Dungeon" and direction == "east" and current not in state["lit_rooms"]:
		return False, "It's too dark to find the tunnel. Light the room first. (Try: use torch)"

	# If an exit is permanently unlocked, ignore locks
	if is_exit_unlocked(state, current, direction):
		return True, ""

	lock = is_exit_locked(world, current, direction)
	if lock:
		required = lock.get("requires_item")
		if required and not has_equivalent_item(state, required):
			return False, lock.get("fail_text", "That way is locked.")

	return True, ""


def maybe_start_room_combat(world: dict, state: dict) -> None:
	"""
	Starts combat automatically if the room has an enemy and it hasn't been defeated.
	This is called after movement and after loading the game.
	"""
	room_name = state["current_room"]
	room_enemies = world.get("room_enemies", {})
	enemy_name = room_enemies.get(room_name)

	if not enemy_name:
		return

	defeated = state.get("defeated_enemies", set())
	if enemy_name in defeated:
		return

	enemy_def = world.get("enemies", {}).get(enemy_name)
	if not enemy_def:
		return

	enemy = {
		"name": enemy_name,
		"hp": int(enemy_def.get("max_hp", 30)),
		"max_hp": int(enemy_def.get("max_hp", 30)),
		"attack_min": int(enemy_def.get("attack_min", 5)),
		"attack_max": int(enemy_def.get("attack_max", 10)),
		"xp_reward": int(enemy_def.get("xp_reward", 10)),
	}

	state["in_combat"] = True
	state["enemy"] = enemy

	print("\n" + enemy_def.get("intro_text", f"A {enemy_name} attacks!"))
	print(enemy_status(enemy))
	show_health(state)
	print("Combat commands: attack | use <item> | run")


def move_player(world: dict, state: dict, direction: str) -> None:
	if state.get("in_combat"):
		print("You can't flee to another room mid-fight. (Try: run)")
		return

	ok, msg = can_go(world, state, direction)
	if not ok:
		print(msg)
		return

	current = state["current_room"]
	dest = world["rooms"][current]["exits"][direction]
	state["current_room"] = dest
	state["moves"] += 1
	describe_room(world, state)
	maybe_start_room_combat(world, state)


def get_item(world: dict, state: dict, item: str) -> None:
	if state.get("in_combat"):
		print("Now isn't the time to rummage around. (Try: attack / use <item> / run)")
		return

	room = world["rooms"][state["current_room"]]
	items = room.get("items", [])

	if item not in items:
		print("That item isn't here.")
		return

	items.remove(item)
	state["inventory"].append(item)
	state["moves"] += 1
	print(f"You picked up: {item}")


def drop_item(world: dict, state: dict, item: str) -> None:
	if state.get("in_combat"):
		print("Dropping things mid-fight is a bold choice. Finish this first.")
		return

	if item not in state["inventory"]:
		print("You don't have that item.")
		return

	state["inventory"].remove(item)
	world["rooms"][state["current_room"]].setdefault("items", []).append(item)
	state["moves"] += 1
	print(f"You dropped: {item}")


def show_inventory(state: dict) -> None:
	inv = state["inventory"]
	print("Inventory:", ", ".join(inv) if inv else "(empty)")


def talk_to(world: dict, state: dict, npc_name: str) -> None:
	if state.get("in_combat"):
		print("Your enemy isn't interested in conversation.")
		return

	room = world["rooms"][state["current_room"]]
	for npc in room.get("npcs", []):
		if normalise(npc.get("name", "")) == npc_name:
			print(npc.get("dialogue", "They have nothing to say."))
			state["moves"] += 1
			return
	print("There's no one by that name here.")


def heal_player(state: dict, amount: int) -> None:
	amount = max(0, int(amount))
	before = int(state["health"])
	state["health"] = min(100, before + amount)
	after = int(state["health"])
	gained = after - before
	print(f"You recover {gained}% health.")
	print(f"You now have {after}% health.")
	show_health(state)


def unlock_exit(state: dict, from_room: str, direction: str) -> None:
	state.setdefault("unlocked_exits", set()).add((from_room, direction))


def use_item(world: dict, state: dict, item: str) -> None:
	if item not in state["inventory"]:
		print("You don't have that item to use.")
		return

	usable = world.get("usable_items", {})
	data = usable.get(item)

	# If the item isn't listed in JSON, it still shouldn't crash.
	if not isinstance(data, dict):
		print("Nothing happens.")
		state["moves"] += 1
		return

	effect = data.get("effect")

	if effect == "heal_health":
		amount = int(data.get("amount", 0))
		print(data.get("text", "You feel better."))
		heal_player(state, amount)
		state["moves"] += 1
		return

	if effect == "light_room":
		allowed_rooms = data.get("rooms", [])
		room_name = state["current_room"]
		if allowed_rooms and room_name not in allowed_rooms:
			print("You wave the light around, but it doesn't change much here.")
			state["moves"] += 1
			return

		state.setdefault("lit_rooms", set()).add(room_name)
		print(data.get("text", "Light floods the room."))
		state["moves"] += 1
		describe_room(world, state)
		return

	if effect == "unlock_exit":
		from_room = data.get("from")
		direction = data.get("direction")
		if from_room == state["current_room"]:
			unlock_exit(state, from_room, direction)
			print(data.get("text", "You hear a lock click open."))
		else:
			print("That doesn't seem to fit anything here.")
		state["moves"] += 1
		return

	if effect == "shield":
		amount = int(data.get("amount", 0))
		state["shield"] = max(0, amount)
		print(data.get("text", "A protective warmth surrounds you."))
		state["moves"] += 1
		return

	print("Nothing happens.")
	state["moves"] += 1


def player_attack(state: dict) -> int:
	xp = int(state.get("xp", 0))
	base_min, base_max = 8, 14
	bonus = min(6, xp // 25)  # 0..6
	return random.randint(base_min + bonus, base_max + bonus)


def enemy_attack(enemy: dict) -> int:
	return random.randint(int(enemy["attack_min"]), int(enemy["attack_max"]))


def apply_enemy_damage_to_player(state: dict, damage: int) -> None:
	damage = max(0, int(damage))
	shield = int(state.get("shield", 0))
	if shield > 0:
		blocked = min(shield, damage)
		damage -= blocked
		state["shield"] = 0
		print(f"Your ward absorbs {blocked} damage, then fades.")

	before = int(state["health"])
	state["health"] = max(0, before - damage)
	after = int(state["health"])
	taken = before - after
	print(f"You take {taken}% damage.")
	print(f"You now have {after}% health.")
	show_health(state)


def combat_turn(world: dict, state: dict, verb: str, noun: str) -> None:
	enemy = state.get("enemy")
	if not enemy:
		state["in_combat"] = False
		return

	if verb == "attack":
		dmg = player_attack(state)
		before = enemy["hp"]
		enemy["hp"] = max(0, enemy["hp"] - dmg)
		lost = before - enemy["hp"]
		print(f"You strike for {lost} damage.")
		print(f"{enemy['name']} loses {lost} HP.")
		print(enemy_status(enemy))

		if enemy["hp"] <= 0:
			# Victory
			enemy_name = enemy["name"]
			enemy_def = world.get("enemies", {}).get(enemy_name, {})
			print(enemy_def.get("defeat_text", f"{enemy_name} is defeated!"))

			state["xp"] = int(state.get("xp", 0)) + int(enemy.get("xp_reward", 0))
			state.setdefault("defeated_enemies", set()).add(enemy_name)

			print(f"You gain {enemy.get('xp_reward', 0)} XP. Total XP: {state['xp']}")
			state["in_combat"] = False
			state["enemy"] = None
			return

		# Enemy responds
		edmg = enemy_attack(enemy)
		print(f"{enemy['name']} attacks!")
		apply_enemy_damage_to_player(state, edmg)
		return

	if verb == "use":
		if not noun:
			print("Use what? (Example: use ration)")
			return
		use_item(world, state, noun)

		# Enemy still gets a turn after you use an item (unless combat ended)
		enemy = state.get("enemy")
		if state.get("in_combat") and enemy:
			edmg = enemy_attack(enemy)
			print(f"{enemy['name']} attacks!")
			apply_enemy_damage_to_player(state, edmg)
		return

	if verb == "run":
		# Simple escape chance (boss fights are stickier)
		room = state["current_room"]
		is_boss = world.get("room_enemies", {}).get(room) == "Ember King"
		chance = 0.30 if is_boss else 0.55

		if random.random() < chance:
			print("You break away and retreat!")
			state["in_combat"] = False
			state["enemy"] = None
			state["moves"] += 1
			# Small retreat: go back to a safe adjacent room if possible
			exits = world["rooms"][room].get("exits", {})
			if "south" in exits:
				state["current_room"] = exits["south"]
			elif "west" in exits:
				state["current_room"] = exits["west"]
			# Describe where you ended up
			describe_room(world, state)
			return

		print("You try to run—but your enemy blocks the way!")
		enemy = state.get("enemy")
		if enemy:
			edmg = enemy_attack(enemy)
			print(f"{enemy['name']} punishes your hesitation!")
			apply_enemy_damage_to_player(state, edmg)
		return

	print("In combat you can: attack | use <item> | run")


def check_win_lose(world: dict, state: dict) -> tuple[bool, str]:
	# Lose by health
	if int(state.get("health", 100)) <= 0:
		return True, "Your vision tunnels… and the castle swallows the last of your strength. You lose."

	win = world.get("win_condition", {})
	wtype = win.get("type")

	if wtype == "has_item":
		if win.get("item") in state["inventory"]:
			return True, win.get("text", "You win!")

	if wtype == "reach_room":
		if state["current_room"] == win.get("room"):
			return True, win.get("text", "You win!")

	if wtype == "reach_room_with_item":
		if state["current_room"] == win.get("room") and win.get("item") in state["inventory"]:
			return True, win.get("text", "You win!")

	lose = world.get("lose_condition", {})
	ltype = lose.get("type")

	if ltype == "max_moves":
		limit = int(lose.get("moves", 0))
		if state["moves"] >= limit:
			return True, lose.get("text", "You lose!")

	return False, ""


def save_game(world: dict, state: dict) -> None:
	data = {
		"current_room": state["current_room"],
		"inventory": state["inventory"],
		"moves": state["moves"],
		"health": state.get("health", 100),
		"xp": state.get("xp", 0),
		"shield": state.get("shield", 0),
		"lit_rooms": list(state.get("lit_rooms", set())),
		"defeated_enemies": list(state.get("defeated_enemies", set())),
		"unlocked_exits": [list(x) for x in state.get("unlocked_exits", set())],
		"rooms": world["rooms"],
	}
	with open(SAVE_FILE, "w", encoding="utf-8") as f:
		json.dump(data, f, indent=2)
	print("Game saved.")


def load_game(world: dict, state: dict) -> None:
	if not os.path.exists(SAVE_FILE):
		print("No save file found.")
		return

	with open(SAVE_FILE, "r", encoding="utf-8") as f:
		data = json.load(f)

	state["current_room"] = data.get("current_room", world["start_room"])
	state["inventory"] = data.get("inventory", [])
	state["moves"] = data.get("moves", 0)
	state["health"] = int(data.get("health", 100))
	state["xp"] = int(data.get("xp", 0))
	state["shield"] = int(data.get("shield", 0))

	state["lit_rooms"] = set(data.get("lit_rooms", []))
	state["defeated_enemies"] = set(data.get("defeated_enemies", []))
	state["unlocked_exits"] = set((x[0], x[1]) for x in data.get("unlocked_exits", []) if isinstance(x, list) and len(x) == 2)

	rooms = data.get("rooms")
	if isinstance(rooms, dict):
		world["rooms"] = rooms

	state["in_combat"] = False
	state["enemy"] = None

	print("Game loaded.")
	describe_room(world, state)
	maybe_start_room_combat(world, state)


def show_help(world: dict) -> None:
	print("\nAvailable commands:")
	for cmd in world.get("commands_help", []):
		print(" -", cmd)

	print("\nExtra notes:")
	print(" - health shows your health bar (out of 100%).")
	print(" - Some rooms are dark: use torch/lantern to reveal paths.")
	print(" - Combat starts automatically in a few rooms.")


def parse_command(line: str) -> tuple[str, str]:
	line = normalise(line)
	if not line:
		return "", ""

	words = line.split()

	# Single-word commands
	if words[0] in ("look", "help", "quit", "inventory", "inv", "save", "load", "health", "attack", "run"):
		return words[0], ""

	# Talk to <npc>
	if len(words) >= 3 and words[0] == "talk" and words[1] == "to":
		return "talk", " ".join(words[2:])

	verb = words[0]
	noun = " ".join(words[1:]) if len(words) > 1 else ""
	return verb, noun


def main():
	filename = "castle_map.json"
	if len(sys.argv) >= 2:
		filename = sys.argv[1]

	world = load_world(filename)

	state: dict[str, Any] = {
		"current_room": world["start_room"],
		"inventory": [],
		"moves": 0,
		"health": 100,
		"xp": 0,
		"shield": 0,
		"lit_rooms": set(),
		"defeated_enemies": set(),
		"unlocked_exits": set(),
		"in_combat": False,
		"enemy": None,
	}

	print(f"\n{world.get('title', 'Text Adventure')}")
	print(world.get("intro_text", ""))
	describe_room(world, state)
	show_health(state)
	show_help(world)

	# If the start room has an enemy, trigger it
	maybe_start_room_combat(world, state)

	while True:
		finished, message = check_win_lose(world, state)
		if finished:
			print("\n" + message)
			break

		line = input("\n> ")
		verb, noun = parse_command(line)

		if verb == "":
			print("Please type a command. (Try: help)")
			continue

		# Combat mode: only allow combat verbs
		if state.get("in_combat"):
			combat_turn(world, state, verb, noun)
			continue

		if verb == "help":
			show_help(world)
		elif verb == "look":
			describe_room(world, state)
		elif verb in ("inventory", "inv"):
			show_inventory(state)
		elif verb == "health":
			show_health(state)
		elif verb == "go":
			if not noun:
				print("Go where? (Example: go north)")
			else:
				move_player(world, state, noun)
		elif verb == "get":
			if not noun:
				print("Get what? (Example: get lantern)")
			else:
				get_item(world, state, noun)
		elif verb == "drop":
			if not noun:
				print("Drop what? (Example: drop iron_key)")
			else:
				drop_item(world, state, noun)
		elif verb == "talk":
			if not noun:
				print("Talk to who? (Example: talk to guard)")
			else:
				talk_to(world, state, noun)
		elif verb == "use":
			if not noun:
				print("Use what? (Example: use ration)")
			else:
				use_item(world, state, noun)
				# Using an item can reveal something in the same room; check for combat after.
				maybe_start_room_combat(world, state)
		elif verb == "save":
			save_game(world, state)
		elif verb == "load":
			load_game(world, state)
		elif verb == "quit":
			print("Farewell, adventurer.")
			break
		else:
			print("I don't understand that command. (Try: help)")

		# If you moved into a hostile room, combat begins.
		maybe_start_room_combat(world, state)


if __name__ == "__main__":
	main()
