from backend.ev.live_ev import recommend_gto_action


def test_recommendation_uses_uncertainty_when_actions_are_tied():
    class FakeHand:
        def __init__(self):
            self.players = {}
            self.board = []
            self.street = "flop"
            self.actions = []

        def legal_actions(self, seat):
            return {"can_call": True, "can_check": True, "call_amount": 0.0, "min_raise_to": 0.0, "max_raise_to": 0.0}

        def current_actor(self):
            return 1

    class FakePlayer:
        def __init__(self):
            self.stack = 100.0
            self.seat = 1
            self.in_hand = True
            self.street_contributed = 0.0
            self.total_contributed = 0.0
            self.hole_cards = ["As", "Kd"]

    hand = FakeHand()
    hand.players[1] = FakePlayer()

    rec = recommend_gto_action(hand, 1, dossier=None, equity_trials=1, base=None)

    assert rec.recommended_action in {"fold", "check", "call"}
