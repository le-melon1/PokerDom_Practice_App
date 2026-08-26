"""Session-parameterized ports of backend/api.py's core game logic
(_new_table, _step_one_bot, _on_hand_finished, _apply_table_turnover,
hero_action, live_ev) -- same call sequence and argument wiring as that
module, with its global `state` dict replaced by an explicit `session:
BotSession` parameter and `HERO_SEAT` replaced by `session.hero_seat`.

Deliberately NOT importing backend/api.py itself (that module has import-time
side effects -- it loads its own single-user state.pkl on import -- and this
bot must stay fully independent of the web app's process/state).
"""

from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import bot_think_time, choose_bot_action
from backend.bots.player_profile_bots import choose_player_profile_action, player_profile_think_time
from backend.dossier import TableDossier
from backend.engine.hand import Hand, IllegalAction
from backend.engine.table import Table
from backend.ev.live_ev import estimate_live_ev, recommend_gto_action
from backend.hand_history import HandHistoryStore, grade_decision
from backend.sessions.live_dynamics import TableTurnover
from backend.telegram_bot.session import BotSession

# PokerDom's real microlimit rake structure -- same constants as
# backend/api.py's RAKE_PERCENT/RAKE_CAP_BB (see that module's comment for
# sourcing: 5% of the pot, capped at 5bb, "no flop no drop").
RAKE_PERCENT = 0.05
RAKE_CAP_BB = 5.0


def new_table(session: BotSession, max_seats: int = 6, starting_stack: float = 200.0, sb: float = 1.0, bb: float = 2.0) -> Table:
    table = Table(
        small_blind=sb,
        big_blind=bb,
        max_seats=max_seats,
        rake_percent=RAKE_PERCENT,
        rake_cap_bb=RAKE_CAP_BB,
    )
    dossier = TableDossier()
    bot_seats = [s for s in range(1, max_seats + 1) if s != session.hero_seat]
    turnover = TableTurnover(
        bot_seats,
        allowed_archetypes=session.settings.get("allowed_archetypes"),
        player_profile_ids=session.settings.get("player_profile_ids"),
    )

    for seat in range(1, max_seats + 1):
        table.add_player(seat=seat, name=("Hero" if seat == session.hero_seat else f"Bot{seat}"), stack=starting_stack)

    session.table = table
    session.dossier = dossier
    session.turnover = turnover
    session.starting_stack = starting_stack
    session.hand = None
    session.hand_history = HandHistoryStore()
    session.hand_number = 0
    session.hero_decisions = []
    return table


def new_hand(session: BotSession) -> Hand:
    if session.table is None:
        raise RuntimeError("no table -- call new_table first")
    hand = session.table.start_new_hand()
    session.hand = hand
    session.hand_number += 1
    session.hero_decisions = []
    return hand


def apply_hero_action(session: BotSession, action: str, amount: float | None = None) -> dict:
    """Mirrors backend/api.py's hero_action() handler exactly: grade against
    the objective (auto/dossier-blended) EV read computed BEFORE the action
    is applied, then apply it. Returns a dict with the trainer_feedback shape
    api.py's response also carries, so formatting.py can reuse it directly."""
    hand = session.hand
    if hand is None or hand.finished:
        raise RuntimeError("no hand in progress")
    if hand.current_actor() != session.hero_seat:
        raise RuntimeError("not hero's turn")

    street = hand.street
    to_call = hand.legal_actions(session.hero_seat)["call_amount"]
    ev = estimate_live_ev(hand, session.hero_seat, opponent_archetype=None, dossier=session.dossier, equity_trials=800)
    rec = recommend_gto_action(
        hand,
        session.hero_seat,
        opponent_archetype=None,
        dossier=session.dossier,
        equity_trials=800,
        base=ev,
    )
    decision = grade_decision(street, to_call, action, amount, ev, recommendation=rec)
    session.hero_decisions.append(decision)

    try:
        hand.apply_action(session.hero_seat, action, amount)
    except IllegalAction:
        session.hero_decisions.pop()
        raise

    if hand.finished:
        _on_hand_finished(session)

    return {
        "grade": decision.trainer_grade,
        "verdict": decision.verdict,
        "ev_loss": round(decision.solver_ev_loss, 3) if decision.solver_ev_loss is not None else None,
        "solver_action": decision.solver_action,
        "solver_amount": round(decision.solver_amount, 2) if decision.solver_amount is not None else None,
    }


def step_one_bot(session: BotSession) -> float | None:
    """Compute and apply exactly one bot action (whoever is currently on
    turn). Returns that bot's think-time, or None if there's nothing to do
    (hero's turn, or hand over) -- same contract as api.py's _step_one_bot."""
    hand = session.hand
    if hand is None or hand.finished:
        return None
    seat = hand.current_actor()
    if seat is None or seat == session.hero_seat:
        return None

    turnover: TableTurnover = session.turnover
    profile_id = turnover.profile_id_for(seat)
    if profile_id:
        session_hands_so_far = turnover.occupants[seat].hands_played
        action, amount = choose_player_profile_action(hand, seat, profile_id, session_hands_so_far)
        think_time = player_profile_think_time(action)
    else:
        archetype = turnover.archetype_for(seat)
        freq_tier = turnover.freq_tier_for(seat)
        tilt_tier = turnover.tilt_tier_for(seat)
        bluff_tier_a = turnover.bluff_tier_a_for(seat)
        bluff_tier_c = turnover.bluff_tier_c_for(seat)
        hero_dossier = session.dossier.by_seat.get(session.hero_seat)
        action, amount = choose_bot_action(
            hand,
            seat,
            archetype=archetype,
            freq_tier=freq_tier,
            tilt_tier=tilt_tier,
            bluff_tier_a=bluff_tier_a,
            bluff_tier_c=bluff_tier_c,
            hero_seat=session.hero_seat,
            hero_dossier=hero_dossier,
        )
        think_time = bot_think_time(action)
    try:
        hand.apply_action(seat, action, amount)
    except IllegalAction:
        hand.apply_action(seat, "fold")

    if hand.finished:
        _on_hand_finished(session)
    return think_time


def _on_hand_finished(session: BotSession) -> None:
    hand = session.hand
    session.dossier.record_hand(hand)
    if hand.result is not None and hand.result.rake:
        session.table.record_rake(hand.result.rake)
    session.hand_history.record(hand, session.hand_number, session.hero_seat, session.hero_decisions)
    _apply_table_turnover(session)


def _apply_table_turnover(session: BotSession) -> None:
    hand = session.hand
    turnover: TableTurnover = session.turnover
    table: Table = session.table
    turnover.record_hand_for_tilt(hand)
    seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != session.hero_seat}
    turned_over = turnover.after_hand(seat_stacks, session.starting_stack)

    for seat, did_turn_over in turned_over.items():
        if not did_turn_over:
            continue
        table.players[seat].stack = session.starting_stack
        table.players[seat].sitting_out = False
        session.dossier.reset_seat(seat)


def compute_abc_strategy_hint(session: BotSession) -> dict:
    """Hint powered by the ABC bot (choose_abc_action) -- the rule-based
    strategy this whole project spent months A/B-testing flag by flag
    (see abc_bot.py's own changelog docstring), not the equity/CFR panel.
    Feeds it the SAME live opponent reads (archetype/freq_tier/tilt/bluff
    tier, from session.turnover) that a seated bot's own decisions already
    use -- so the hint reflects exactly the opponent-aware rules this
    session confirmed (WIDER_CALL_VS_OFTEN_TIER, BLUFF_VS_RARE_TIER, etc.),
    not a generic equity calculation.

    Returns {"action": str, "amount": float|None, "opponents": [{"seat",
    "name", "archetype", "freq_tier", "tilt_tier"}]} for a live opponent
    who is still in the hand."""
    hand = session.hand
    if hand is None or hand.finished:
        raise RuntimeError("no hand in progress")
    if hand.current_actor() != session.hero_seat:
        raise RuntimeError("not hero's turn")

    turnover: TableTurnover = session.turnover
    live_opponents = [
        seat for seat, p in hand.players.items() if seat != session.hero_seat and p.in_hand
    ]
    opponent_archetypes = {s: turnover.archetype_for(s) for s in live_opponents}
    opponent_freq_tiers = {s: turnover.freq_tier_for(s) for s in live_opponents}
    opponent_tilt_states = {s: turnover.tilt_tier_for(s) for s in live_opponents}
    opponent_bluff_tiers_a = {s: turnover.bluff_tier_a_for(s) for s in live_opponents}
    opponent_bluff_tiers_c = {s: turnover.bluff_tier_c_for(s) for s in live_opponents}

    action, amount = choose_abc_action(
        hand,
        session.hero_seat,
        opponent_archetypes=opponent_archetypes,
        opponent_freq_tiers=opponent_freq_tiers,
        opponent_tilt_states=opponent_tilt_states,
        opponent_bluff_tiers_a=opponent_bluff_tiers_a,
        opponent_bluff_tiers_c=opponent_bluff_tiers_c,
    )

    return {
        "action": action,
        "amount": round(amount, 2) if amount is not None else None,
        "opponents": [
            {
                "seat": s,
                "name": hand.players[s].name,
                "archetype": opponent_archetypes[s],
                "freq_tier": opponent_freq_tiers[s],
                "tilt_tier": opponent_tilt_states[s],
            }
            for s in live_opponents
        ],
    }
