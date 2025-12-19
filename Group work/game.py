import json
import os
import sys

SAVE_FILE = "savegame.json"


def load_world(filename: str) -> dict:
	with open(filename, "r", encoding="utf-8") as f:
		return json.load(f)


def normalise(text: str) -> str:
	return text.strip().lower()


def describe_room(world: dict, state: dict) -> None:
	room_name = state["current_room"]
	room = world["rooms"][room_name]

	print(f"\n== {room_name} ==")
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


def can_go(world: dict, state: dict, direction: str) -> tuple[bool, str]:
	current = state["current_room"]
	exits = world["rooms"][current].get("exits", {})

	if direction not in exits:
		return False, "You can't go that way."

	lock = is_exit_locked(world, current, direction)
	if lock:
		required = lock.get("requires_item")
		if required and required not in state["inventory"]:
			return False, lock.get("fail_text", "That way is locked.")

	return True, ""


def move_player(world: dict, state: dict, direction: str) -> None:
	ok, msg = can_go(world, state, direction)
	if not ok:
		print(msg)
		return

	current = state["current_room"]
	dest = world["rooms"][current]["exits"][direction]
	state["current_room"] = dest
	state["moves"] += 1
	describe_room(world, state)


def get_item(world: dict, state: dict, item: str) -> None:
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
	room = world["rooms"][state["current_room"]]
	for npc in room.get("npcs", []):
		if normalise(npc.get("name", "")) == npc_name:
			print(npc.get("dialogue", "They have nothing to say."))
			state["moves"] += 1
			return
	print("There's no one by that name here.")


def use_item(world: dict, state: dict, item: str) -> None:
	if item not in state["inventory"]:
		print("You don't have that item to use.")
		return

	usable = world.get("usable_items", {})
	if item not in usable:
		print("Nothing happens.")
		state["moves"] += 1
		return

	effect = usable[item].get("effect")
	if effect == "heal_moves":
		amount = int(usable[item].get("amount", 0))
		state["moves"] = max(0, state["moves"] - amount)
		print(usable[item].get("text", "You feel better."))
		state["moves"] += 1
		return

	print("Nothing happens.")
	state["moves"] += 1


def check_win_lose(world: dict, state: dict) -> tuple[bool, str]:
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

	rooms = data.get("rooms")
	if isinstance(rooms, dict):
		world["rooms"] = rooms

	print("Game loaded.")
	describe_room(world, state)


def show_help(world: dict) -> None:
	print("\nAvailable commands:")
	for cmd in world.get("commands_help", []):
		print(" -", cmd)


def parse_command(line: str) -> tuple[str, str]:
	line = normalise(line)
	if not line:
		return "", ""

	words = line.split()

	if words[0] in ("look", "help", "quit", "inventory", "inv", "save", "load"):
		return words[0], ""

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

	state = {
		"current_room": world["start_room"],
		"inventory": [],
		"moves": 0,
	}

	print(f"\n{world.get('title', 'Text Adventure')}")
	print(world.get("intro_text", ""))
	describe_room(world, state)
	show_help(world)

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

		if verb == "help":
			show_help(world)
		elif verb == "look":
			describe_room(world, state)
		elif verb in ("inventory", "inv"):
			show_inventory(state)
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
		elif verb == "save":
			save_game(world, state)
		elif verb == "load":
			load_game(world, state)
		elif verb == "quit":
			print("Farewell, adventurer.")
			break
		else:
			print("I don't understand that command. (Try: help)")


if __name__ == "__main__":
    main()