"""CLI smoke test: run many hands at a 6-max table with random legal actions,
verify total chips in play never change and nothing crashes."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.engine.hand import IllegalAction
from backend.engine.table import Table

N_HANDS = 500
N_PLAYERS = 6
STARTING_STACK = 200.0


def random_action(hand, seat):
    legal = hand.legal_actions(seat)
    choices = ["fold"]
    if legal["can_check"]:
        choices.append("check")
    if legal["can_call"]:
        choices.append("call")
    if legal["max_raise_to"] > hand.current_bet:
        choices.append("raise")

    action = random.choice(choices)
    if action == "raise":
        lo, hi = legal["min_raise_to"], legal["max_raise_to"]
        amount = round(random.uniform(lo, hi), 2)
        return action, amount
    return action, None


def main():
    table = Table(small_blind=1.0, big_blind=2.0, max_seats=N_PLAYERS)
    for i in range(N_PLAYERS):
        table.add_player(seat=i + 1, name=f"Bot{i+1}", stack=STARTING_STACK)

    total_chips_start = sum(p.stack for p in table.players.values())
    hands_completed = 0
    errors = 0

    for _ in range(N_HANDS):
        active = [p for p in table.players.values() if p.stack > 0]
        if len(active) < 2:
            print(f"Stopping early: only {len(active)} players with chips left")
            break

        hand = table.start_new_hand()
        guard = 0
        while not hand.finished and guard < 200:
            seat = hand.current_actor()
            if seat is None:
                break
            action, amount = random_action(hand, seat)
            try:
                hand.apply_action(seat, action, amount)
            except IllegalAction as e:
                errors += 1
                print(f"IllegalAction on seat {seat} action={action} amount={amount}: {e}")
                break
            guard += 1

        if guard >= 200:
            print("WARNING: hand did not finish within 200 actions (possible infinite loop)")
            errors += 1

        hands_completed += 1
        total_chips_now = sum(p.stack for p in table.players.values())
        if abs(total_chips_now - total_chips_start) > 1e-6:
            print(f"CHIP CONSERVATION VIOLATION after hand {hands_completed}: "
                  f"{total_chips_now} != {total_chips_start}")
            errors += 1
            break

    print(f"\nCompleted {hands_completed}/{N_HANDS} hands, {errors} errors.")
    print(f"Total chips: start={total_chips_start}, end={sum(p.stack for p in table.players.values())}")
    for p in sorted(table.players.values(), key=lambda x: x.seat):
        print(f"  seat {p.seat} ({p.name}): stack={p.stack:.2f}")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
