"""Session-parameterized ports of backend/api.py's core game logic
(_new_table, _step_one_bot, _on_hand_finished, _apply_table_turnover,
hero_action, live_ev) -- same call sequence and argument wiring as that
module, with its global `state` dict replaced by an explicit `session:
BotSession` parameter and `HERO_SEAT` replaced by `session.hero_seat`.

Deliberately NOT importing backend/api.py itself (that module has import-time
side effects -- it loads its own single-user state.pkl on import -- and this
bot must stay fully independent of the web app's process/state).
"""

import random

from backend.bots.abc_bot import choose_abc_action
from backend.bots.behavior_clone import bot_think_time, choose_bot_action
from backend.bots.player_profile_bots import choose_player_profile_action, player_profile_think_time
from backend.dossier import TableDossier
from backend.engine.hand import Hand, IllegalAction
from backend.engine.table import Table
from backend.ev.live_ev import estimate_live_ev, recommend_gto_action
from backend.hand_history import HandHistoryStore, grade_decision
from backend.sessions.live_dynamics import TableTurnover
from backend.telegram_bot import drills, forcing
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

    # drill mode (2026-08-26): a selected flag's archetype/freq_tier
    # requirements bias who gets seated -- see drills.py's DrillSpec.
    merged = drills.merge_specs(session.settings.get("drill_flags", []))
    allowed_archetypes = session.settings.get("allowed_archetypes")
    if merged.archetype_filter:
        allowed_archetypes = list(merged.archetype_filter)
    forced_freq_tier = drills.freq_tier_assignment(merged, bot_seats) if merged.freq_tier_seats else None

    turnover = TableTurnover(
        bot_seats,
        allowed_archetypes=allowed_archetypes,
        player_profile_ids=session.settings.get("player_profile_ids"),
        forced_freq_tier=forced_freq_tier,
    )

    for seat in range(1, max_seats + 1):
        name = "Hero" if seat == session.hero_seat else turnover.name_for(seat)
        table.add_player(seat=seat, name=name, stack=starting_stack)

    session.table = table
    session.dossier = dossier
    session.turnover = turnover
    session.starting_stack = starting_stack
    session.hand = None
    session.hand_history = HandHistoryStore()
    session.hand_number = 0
    session.hero_decisions = []
    session.street_decisions = []
    return table


def new_hand(session: BotSession) -> Hand:
    if session.table is None:
        raise RuntimeError("no table -- call new_table first")

    # drill mode: force hero's seat rotation to land at a specific position
    # BEFORE dealing (Table.start_new_hand always advances the button by
    # one first -- see forcing.pick_hero_position_button's own docstring).
    merged = drills.merge_specs(session.settings.get("drill_flags", []))
    position = drills.resolve_position(merged, session.hand_number)
    if position:
        session.table.button_seat = forcing.pick_hero_position_button(session.table, session.hero_seat, position)

    hand = session.table.start_new_hand()
    session.hand = hand
    session.hand_number += 1
    session.hero_decisions = []
    session.street_decisions = []

    if merged.hero_hand_notations:
        swap = forcing.pick_hand_swap(hand, set(merged.hero_hand_notations), random.Random(), session.hero_seat)
        if swap is not None:
            forcing.apply_hand_swap(hand, swap[0], swap[1], session.hero_seat)

    if merged.force_tilt:
        for seat, player in hand.players.items():
            if seat != session.hero_seat and player.in_hand:
                session.turnover.force_tilt(seat, "acute")

    return hand


def _live_opponent_reads(session: BotSession) -> tuple[list[int], dict, dict, dict, dict, dict]:
    """The same live opponent-read dicts (archetype/freq_tier/tilt/bluff
    tier) both the hint and the post-action ABC-recommendation snapshot
    need -- factored out so they're built identically in both places."""
    hand = session.hand
    turnover: TableTurnover = session.turnover
    live_opponents = [seat for seat, p in hand.players.items() if seat != session.hero_seat and p.in_hand]
    opponent_archetypes = {s: turnover.archetype_for(s) for s in live_opponents}
    opponent_freq_tiers = {s: turnover.freq_tier_for(s) for s in live_opponents}
    opponent_tilt_states = {s: turnover.tilt_tier_for(s) for s in live_opponents}
    opponent_bluff_tiers_a = {s: turnover.bluff_tier_a_for(s) for s in live_opponents}
    opponent_bluff_tiers_c = {s: turnover.bluff_tier_c_for(s) for s in live_opponents}
    return live_opponents, opponent_archetypes, opponent_freq_tiers, opponent_tilt_states, opponent_bluff_tiers_a, opponent_bluff_tiers_c


def _abc_recommendation(session: BotSession) -> tuple[str, float | None]:
    """What choose_abc_action recommends for hero's CURRENT decision point,
    fed the same live opponent reads compute_abc_strategy_hint uses. Shared
    by the hint feature and apply_hero_action's per-street review record."""
    hand = session.hand
    _, archetypes, freq_tiers, tilt_states, bluff_a, bluff_c = _live_opponent_reads(session)
    return choose_abc_action(
        hand,
        session.hero_seat,
        opponent_archetypes=archetypes,
        opponent_freq_tiers=freq_tiers,
        opponent_tilt_states=tilt_states,
        opponent_bluff_tiers_a=bluff_a,
        opponent_bluff_tiers_c=bluff_c,
    )


def apply_hero_action(session: BotSession, action: str, amount: float | None = None) -> dict:
    """Mirrors backend/api.py's hero_action() handler: grade against the
    objective (auto/dossier-blended) EV read computed BEFORE the action is
    applied, then apply it. Also snapshots what the ABC strategy itself
    recommends at this exact decision point (session.street_decisions),
    for the end-of-hand full review -- per-street, not just the last
    action. Returns a dict with the trainer_feedback shape api.py's
    response also carries, so formatting.py can reuse it directly."""
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

    abc_action, abc_amount = _abc_recommendation(session)
    session.street_decisions.append(
        {
            "street": street,
            "action": action,
            "amount": amount,
            "grade": decision.trainer_grade,
            "verdict": decision.verdict,
            "abc_action": abc_action,
            "abc_amount": round(abc_amount, 2) if abc_amount is not None else None,
        }
    )

    try:
        hand.apply_action(session.hero_seat, action, amount)
    except IllegalAction:
        session.hero_decisions.pop()
        session.street_decisions.pop()
        raise

    if hand.finished:
        _on_hand_finished(session)

    return {
        # ABC-rule-based fields -- what formatting.py's mid-hand feedback
        # line actually displays (per explicit user request: grading must
        # be "по правилам абс бота", not the equity/CFR solver).
        "action": action,
        "amount": amount,
        "abc_action": abc_action,
        "abc_amount": round(abc_amount, 2) if abc_amount is not None else None,
        # Solver-based fields, kept for hand_history's mistake_count
        # bookkeeping (HeroDecision.is_mistake) -- not shown to the user
        # directly anywhere in the bot anymore.
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
    merged = drills.merge_specs(session.settings.get("drill_flags", []))
    forced: tuple[str, float | None] | None = None
    if merged.force_opponent_reraise and forcing.should_force_clear_for_hero_open(hand, seat, session.hero_seat):
        forced = forcing.force_fold_action(hand, seat)
    elif merged.force_opponent_reraise and forcing.should_force_opponent_reraise(hand, seat, session.hero_seat):
        forced = forcing.force_reraise_action(hand, seat, random.Random())
    elif merged.force_opponent_open and forcing.should_force_clear_to_open(hand, seat, session.hero_seat):
        forced = forcing.force_fold_action(hand, seat)
    elif merged.force_opponent_open and forcing.should_force_opponent_open(hand, seat, session.hero_seat):
        forced = forcing.force_open_action(hand, seat)
    elif merged.force_opponent_limp and forcing.should_force_opponent_limp(hand, seat, session.hero_seat):
        forced = forcing.force_limp_action(hand, seat)

    if forced is not None:
        action, amount = forced
        think_time = bot_think_time(action)
    else:
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
        # A turned-over seat is a new "person" sitting down -- give them
        # their own new name too, not the previous occupant's.
        table.players[seat].name = turnover.name_for(seat)
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

    live_opponents, opponent_archetypes, opponent_freq_tiers, opponent_tilt_states, *_ = _live_opponent_reads(session)
    action, amount = _abc_recommendation(session)

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
