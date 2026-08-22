"""Minimal FastAPI backend tying everything together: game engine (Phase A),
behavior-clone bots (Phase C), session dossier, and the live EV panel
(Phase D). Single global table for now -- this is a local practice tool for
one person, not a multi-tenant server.
"""

import pickle
import sys
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.bots.behavior_clone import bot_think_time, choose_bot_action
from backend.bots.player_profile_bots import choose_player_profile_action, load_profile_pool, player_profile_think_time
from backend.dossier import TableDossier
from backend.engine.hand import IllegalAction
from backend.engine.table import Table
from backend.ev.live_ev import estimate_live_ev, recommend_gto_action
from backend.hand_history import HandHistoryStore, grade_decision
from backend.sessions.live_dynamics import ARCHETYPE_POOL, TableTurnover

app = FastAPI(title="PokerDom Practice")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HERO_SEAT = 1

# 2026-07-30: session state used to be pure in-memory, lost on every server
# restart (killed dev server, machine reboot) -- a real annoyance for a
# practice tool meant to track a running session's dossier/history over
# multiple sittings. Simplest fix that covers it: pickle the whole `state`
# dict to disk after every mutating request, load it back on import if
# present. Not a real database -- fine for a single-user local tool where the
# whole point is surviving process restarts, not concurrent access.
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "app_state.pkl"

# Settings panel: "which bots" (allowed_archetypes, None = full real
# population mix), "are hints given" (hints_enabled -- purely advisory, the
# frontend just doesn't call /api/live_ev or render that panel when off; the
# post-action grade in trainer_feedback is a separate, always-on feature, not
# gated by this), and "sizing" as effective stack depth in bb (starting_stack
# is already denominated in bb-equivalent chips at sb=1/bb=2, so 200 == 100bb
# effective). Changing any of allowed_archetypes/starting_stack/max_seats
# requires a fresh table (can't swap opponent pool or stack depth mid-session)
# -- see update_settings below.
DEFAULT_SETTINGS = {
    "hints_enabled": True,
    "allowed_archetypes": None,
    "player_profile_ids": None,
    "starting_stack": 200.0,
    "max_seats": 6,
}

state = {
    "table": None,
    "hand": None,
    "dossier": None,
    "turnover": None,
    "starting_stack": 200.0,
    "hand_history": None,
    "hand_number": 0,
    "hero_decisions": [],
    "settings": dict(DEFAULT_SETTINGS),
}
LIVE_EV_CACHE_MAX = 64
_live_ev_response_cache: OrderedDict[tuple, dict] = OrderedDict()


def _save_state() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_FILE.with_suffix(".pkl.tmp")
    with open(tmp_path, "wb") as fh:
        pickle.dump(state, fh)
    tmp_path.replace(STATE_FILE)  # atomic swap -- a crash mid-write can't corrupt the real file


def _live_ev_cache_key(hand, opponent_archetype: str | None) -> tuple:
    players = tuple(
        (
            seat,
            player.in_hand,
            round(player.stack, 4),
            round(player.street_contributed, 4),
            round(player.total_contributed, 4),
        )
        for seat, player in sorted(hand.players.items())
    )
    return (
        state["hand_number"],
        hand.street,
        tuple(hand.board),
        hand.current_actor(),
        tuple(hand.players[HERO_SEAT].hole_cards),
        players,
        opponent_archetype,
    )


def _load_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        with open(STATE_FILE, "rb") as fh:
            loaded = pickle.load(fh)
    except Exception:
        return  # corrupt/incompatible save (e.g. after an engine code change) -- start fresh rather than crash
    state.update(loaded)


_load_state()


class ActionRequest(BaseModel):
    action: str
    amount: float | None = None


class SettingsRequest(BaseModel):
    hints_enabled: bool | None = None
    allowed_archetypes: list[str] | None = None
    player_profile_ids: list[str] | None = None
    starting_stack: float | None = None
    max_seats: int | None = None


# PokerDom's real microlimit rake structure (see PokerDom_Microlimits_Analysis/
# src/config.py: RAKE_PERCENT / RAKE_CAP_BB, cross-checked against parsed
# hand-history summaries): 5% of the pot, capped at 5 big blinds, "no flop no drop".
RAKE_PERCENT = 0.05
RAKE_CAP_BB = 5.0


def _new_table(max_seats: int = 6, starting_stack: float = 200.0, sb: float = 1.0, bb: float = 2.0):
    table = Table(
        small_blind=sb,
        big_blind=bb,
        max_seats=max_seats,
        rake_percent=RAKE_PERCENT,
        rake_cap_bb=RAKE_CAP_BB,
    )
    dossier = TableDossier()
    bot_seats = [s for s in range(1, max_seats + 1) if s != HERO_SEAT]
    turnover = TableTurnover(
        bot_seats,
        allowed_archetypes=state["settings"].get("allowed_archetypes"),
        player_profile_ids=state["settings"].get("player_profile_ids"),
    )

    for seat in range(1, max_seats + 1):
        table.add_player(seat=seat, name=("Hero" if seat == HERO_SEAT else f"Bot{seat}"), stack=starting_stack)

    state["table"] = table
    state["dossier"] = dossier
    state["turnover"] = turnover
    state["starting_stack"] = starting_stack
    state["hand"] = None
    state["hand_history"] = HandHistoryStore()
    state["hand_number"] = 0
    state["hero_decisions"] = []
    return table


def _step_one_bot() -> float | None:
    """Compute and apply exactly one bot action (whoever is currently on
    turn). Returns that bot's think-time so the caller (the frontend, via
    /api/bots/step) can pace revealing actions one at a time instead of
    resolving the whole betting round silently before the client sees it.
    Returns None if there's nothing to do (hero's turn, or hand over)."""
    hand = state["hand"]
    if hand is None or hand.finished:
        return None
    seat = hand.current_actor()
    if seat is None or seat == HERO_SEAT:
        return None

    turnover: TableTurnover = state["turnover"]
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
        hero_dossier = state["dossier"].by_seat.get(HERO_SEAT)
        action, amount = choose_bot_action(
            hand,
            seat,
            archetype=archetype,
            freq_tier=freq_tier,
            tilt_tier=tilt_tier,
            bluff_tier_a=bluff_tier_a,
            bluff_tier_c=bluff_tier_c,
            hero_seat=HERO_SEAT,
            hero_dossier=hero_dossier,
        )
        think_time = bot_think_time(action)
    try:
        hand.apply_action(seat, action, amount)
    except IllegalAction:
        hand.apply_action(seat, "fold")

    if hand.finished:
        _on_hand_finished(hand)
    return think_time


def _on_hand_finished(hand) -> None:
    state["dossier"].record_hand(hand)
    if hand.result is not None and hand.result.rake:
        state["table"].record_rake(hand.result.rake)
    state["hand_history"].record(hand, state["hand_number"], HERO_SEAT, state["hero_decisions"])
    _apply_table_turnover(hand)


def _apply_table_turnover(hand) -> None:
    """After a finished hand: advance each bot's planned-session countdown
    (Phase B's real per-archetype session lengths), and for anyone who
    busted or hit their sampled session length, seat a fresh bot -- new
    archetype, new planned length, stack topped back up, dossier reset."""
    turnover: TableTurnover = state["turnover"]
    table: Table = state["table"]
    turnover.record_hand_for_tilt(hand)
    seat_stacks = {seat: p.stack for seat, p in hand.players.items() if seat != HERO_SEAT}
    turned_over = turnover.after_hand(seat_stacks, state["starting_stack"])

    for seat, did_turn_over in turned_over.items():
        if not did_turn_over:
            continue
        table.players[seat].stack = state["starting_stack"]
        table.players[seat].sitting_out = False
        state["dossier"].reset_seat(seat)


def _visible_hole_cards(hand, seat: int, player) -> list[str]:
    """Hero's own cards are always visible. An opponent's cards are only
    revealed if a real showdown happened (2+ live hands compared) AND this
    specific player was still in the hand -- NOT just because the hand is
    over. A hand that ends by everyone folding has no winners_by_pot entries
    (see Hand._finish_hand's uncontested-pot branch) and must never reveal
    anyone's cards, matching how mucking actually works.
    """
    if seat == HERO_SEAT:
        return player.hole_cards
    if hand is None:
        return []
    real_showdown = hand.finished and hand.result is not None and len(hand.result.winners_by_pot) > 0
    if real_showdown and player.in_hand:
        return player.hole_cards
    if not hand.finished and player.in_hand:
        return ["??", "??"]
    return []


def _serialize_state(reveal_hero_cards: bool = True) -> dict:
    table: Table = state["table"]
    hand = state["hand"]

    players = []
    for seat, p in sorted(table.players.items()):
        dossier = state["dossier"].by_seat.get(seat)
        players.append(
            {
                "seat": seat,
                "name": p.name,
                "stack": round(p.stack, 2),
                "bet": round(p.street_contributed, 2),
                "folded": p.folded,
                "all_in": p.all_in,
                "sitting_out": p.sitting_out,
                "hole_cards": _visible_hole_cards(hand, seat, p),
                "dossier": None
                if dossier is None
                else {
                    "hands": dossier.hands_seen,
                    "vpip": round(dossier.vpip, 3),
                    "pfr": round(dossier.pfr, 3),
                    "threebet": round(dossier.threebet_pct, 3),
                    "afq": round(dossier.afq, 3),
                    "style": dossier.style,
                    "net_won": round(dossier.net_won, 2),
                },
            }
        )

    result = None
    if hand and hand.finished and hand.result:
        result = {"payouts": hand.result.payouts, "rake": round(hand.result.rake, 2)}

    action_log = []
    if hand:
        for a in hand.actions:
            action_log.append(
                {
                    "seat": a.seat,
                    "name": table.players[a.seat].name,
                    "street": a.street,
                    "action": a.action,
                    "amount": round(a.amount, 2) if a.amount else None,
                }
            )

    session_summary = {
        "hands_played": state["hand_number"],
        "hero_net": round(sum(entry.hero_net for entry in state["hand_history"].entries) if state["hand_history"] else 0.0, 2),
        "mistake_count": sum(entry.mistake_count for entry in state["hand_history"].entries) if state["hand_history"] else 0,
        "recent_style": None,
    }
    if state["dossier"] and state["dossier"].by_seat.get(HERO_SEAT):
        session_summary["recent_style"] = state["dossier"].by_seat[HERO_SEAT].style

    return {
        "button_seat": table.button_seat,
        "street": hand.street if hand else None,
        "board": hand.board if hand else [],
        "pot": sum(p.total_contributed for p in hand.players.values()) if hand else 0.0,
        "current_actor": hand.current_actor() if hand else None,
        "hero_seat": HERO_SEAT,
        "legal_actions": hand.legal_actions(HERO_SEAT) if hand and hand.current_actor() == HERO_SEAT else None,
        "finished": hand.finished if hand else True,
        "result": result,
        "players": players,
        "action_log": action_log,
        "total_rake_collected": round(table.total_rake_collected, 2),
        "session_summary": session_summary,
        "settings": state["settings"],
    }


@app.post("/api/table/start")
def start_table(max_seats: int | None = None, starting_stack: float | None = None):
    _new_table(
        max_seats=max_seats if max_seats is not None else state["settings"]["max_seats"],
        starting_stack=starting_stack if starting_stack is not None else state["settings"]["starting_stack"],
    )
    _save_state()
    return {"ok": True}


@app.post("/api/table/reset")
def reset_table(max_seats: int | None = None, starting_stack: float | None = None):
    _new_table(
        max_seats=max_seats if max_seats is not None else state["settings"]["max_seats"],
        starting_stack=starting_stack if starting_stack is not None else state["settings"]["starting_stack"],
    )
    _save_state()
    return {"ok": True}


def _profile_pool_summary() -> dict:
    return {
        pid: {"archetype": p["archetype"], "vpip": p["vpip"], "pfr": p["pfr"], "hands_seen": p["hands_seen"]}
        for pid, p in load_profile_pool().items()
    }


@app.get("/api/settings")
def get_settings():
    return {**state["settings"], "archetype_pool": ARCHETYPE_POOL, "player_profile_pool": _profile_pool_summary()}


@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    """Hints can be toggled live, no reset needed (the frontend simply stops
    calling /api/live_ev when off). Changing the opponent pool, stack depth,
    or table size takes effect on a fresh table only -- you can't swap who's
    sitting or how deep the stacks are mid-session -- so those trigger
    _new_table the same way the "Сбросить стол" button already does; the
    caller (frontend) is expected to follow a table_reset:true response with
    the same /api/hand/new call resetTable() already makes."""
    settings = state["settings"]
    table_reset_needed = False

    if req.hints_enabled is not None:
        settings["hints_enabled"] = req.hints_enabled

    if req.allowed_archetypes is not None:
        cleaned = [a for a in req.allowed_archetypes if a in ARCHETYPE_POOL]
        new_value = cleaned or None
        if new_value != settings.get("allowed_archetypes"):
            settings["allowed_archetypes"] = new_value
            table_reset_needed = True

    if req.player_profile_ids is not None:
        # player_profile_ids overrides allowed_archetypes entirely at
        # seating time (see TableTurnover) -- both are kept in settings
        # independently so switching back to archetype mode (clearing this
        # to an empty list) restores whatever allowed_archetypes was set to,
        # rather than losing that choice.
        valid_ids = set(load_profile_pool().keys())
        cleaned_profiles = [pid for pid in req.player_profile_ids if pid in valid_ids]
        new_profile_value = cleaned_profiles or None
        if new_profile_value != settings.get("player_profile_ids"):
            settings["player_profile_ids"] = new_profile_value
            table_reset_needed = True

    if req.starting_stack is not None and req.starting_stack != settings.get("starting_stack"):
        if req.starting_stack <= 0:
            raise HTTPException(400, "starting_stack must be positive")
        settings["starting_stack"] = req.starting_stack
        table_reset_needed = True

    if req.max_seats is not None and req.max_seats != settings.get("max_seats"):
        if not (2 <= req.max_seats <= 8):
            raise HTTPException(400, "max_seats must be between 2 and 8")
        settings["max_seats"] = req.max_seats
        table_reset_needed = True

    if table_reset_needed:
        _new_table(max_seats=settings["max_seats"], starting_stack=settings["starting_stack"])

    _save_state()
    return {**settings, "archetype_pool": ARCHETYPE_POOL, "table_reset": table_reset_needed}


@app.post("/api/hand/new")
def new_hand():
    table: Table | None = state["table"]
    if table is None:
        raise HTTPException(400, "no table -- call /api/table/start first")
    try:
        state["hand"] = table.start_new_hand()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    state["hand_number"] += 1
    state["hero_decisions"] = []
    _save_state()
    return _serialize_state()


@app.post("/api/hand/action")
def hero_action(req: ActionRequest):
    hand = state["hand"]
    if hand is None or hand.finished:
        raise HTTPException(400, "no hand in progress")
    if hand.current_actor() != HERO_SEAT:
        raise HTTPException(400, "not hero's turn")

    # Grade against the objective ("auto"/dossier-blended) EV read, computed
    # right now before the action is applied -- regardless of whatever
    # archetype hypothesis the user had selected in the live panel, so every
    # decision is judged against the same consistent baseline.
    street = hand.street
    to_call = hand.legal_actions(HERO_SEAT)["call_amount"]
    ev = estimate_live_ev(hand, HERO_SEAT, opponent_archetype=None, dossier=state["dossier"], equity_trials=800)
    rec = recommend_gto_action(
        hand,
        HERO_SEAT,
        opponent_archetype=None,
        dossier=state["dossier"],
        equity_trials=800,
        base=ev,
    )
    decision = grade_decision(street, to_call, req.action, req.amount, ev, recommendation=rec)
    state["hero_decisions"].append(decision)

    try:
        hand.apply_action(HERO_SEAT, req.action, req.amount)
    except IllegalAction as e:
        state["hero_decisions"].pop()
        raise HTTPException(400, str(e))
    if hand.finished:
        _on_hand_finished(hand)
    _save_state()
    result = _serialize_state()
    result["trainer_feedback"] = {
        "grade": decision.trainer_grade,
        "verdict": decision.verdict,
        "ev_loss": round(decision.solver_ev_loss, 3) if decision.solver_ev_loss is not None else None,
        "solver_action": decision.solver_action,
        "solver_amount": round(decision.solver_amount, 2) if decision.solver_amount is not None else None,
    }
    return result


@app.post("/api/bots/step")
def bots_step():
    if state["hand"] is None:
        raise HTTPException(400, "no hand in progress")
    think_time = _step_one_bot()
    result = _serialize_state()
    result["think_time"] = think_time or 0.0
    _save_state()
    return result


@app.get("/api/state")
def get_state():
    if state["table"] is None:
        raise HTTPException(400, "no table")
    return _serialize_state()


@app.get("/api/live_ev")
def live_ev(opponent_archetype: str | None = None):
    hand = state["hand"]
    if hand is None or hand.finished:
        raise HTTPException(400, "no hand in progress")
    cache_key = _live_ev_cache_key(hand, opponent_archetype)
    cached = _live_ev_response_cache.get(cache_key)
    if cached is not None:
        _live_ev_response_cache.move_to_end(cache_key)
        result = deepcopy(cached)
        result["response_cache_hit"] = True
        return result
    r = estimate_live_ev(
        hand, HERO_SEAT, opponent_archetype=opponent_archetype, dossier=state["dossier"], equity_trials=1200
    )
    rec = recommend_gto_action(
        hand,
        HERO_SEAT,
        opponent_archetype=opponent_archetype,
        dossier=state["dossier"],
        equity_trials=1200,
        base=r,
    )
    range_cfr = rec.gto_equilibrium.get("flop_subgame") if rec.gto_equilibrium else None
    range_weights = {}
    range_lines = []
    if range_cfr:
        range_weights = range_cfr.get("focus_strategy") or range_cfr.get("root_strategy", {})
        range_lines = range_cfr.get("line_analysis", [])
    result = {
        "street": r.street,
        "pot_before": round(r.pot_before, 2),
        "to_call": round(r.to_call, 2),
        "equity_vs_range": round(r.equity_vs_range, 4) if r.equity_vs_range is not None else None,
        "opponent_range_size": r.opponent_range_size,
        "ev_call": round(r.ev_call, 3) if r.ev_call is not None else None,
        "breakeven_equity": round(r.breakeven_equity, 4) if r.breakeven_equity is not None else None,
        "verdict": r.verdict,
        "confidence": round(r.confidence, 2),
        "confidence_note": r.confidence_note,
        "recommendation": {
            "recommended_action": rec.recommended_action,
            "recommended_amount": round(rec.recommended_amount, 2) if rec.recommended_amount is not None else None,
            "best_ev": round(rec.best_ev, 3) if rec.best_ev is not None else None,
            "action_evs": [
                {
                    "action": item.action,
                    "ev": round(item.ev, 3) if item.ev is not None else None,
                    "amount": round(item.amount, 2) if item.amount is not None else None,
                    "reason": item.reason,
                }
                for item in rec.action_evs
            ],
            "gto_equilibrium": rec.gto_equilibrium,
            "solver_summary": {
                "recommended_action": rec.recommended_action,
                "recommended_amount": round(rec.recommended_amount, 2) if rec.recommended_amount is not None else None,
                "best_ev": round(rec.best_ev, 3) if rec.best_ev is not None else None,
                "action_weights": range_weights or (rec.gto_equilibrium.get("wizard_like", {}).get("action_weights", {}) if rec.gto_equilibrium else {}),
                "tree": rec.gto_equilibrium.get("tree", []) if rec.gto_equilibrium else [],
                "line_analysis": range_lines or (rec.gto_equilibrium.get("wizard_like", {}).get("line_analysis", []) if rec.gto_equilibrium else []),
                "range_cfr": range_cfr,
            },
        },
    }
    result["response_cache_hit"] = False
    _live_ev_response_cache[cache_key] = deepcopy(result)
    _live_ev_response_cache.move_to_end(cache_key)
    while len(_live_ev_response_cache) > LIVE_EV_CACHE_MAX:
        _live_ev_response_cache.popitem(last=False)
    return result


@app.get("/api/hand_history")
def hand_history_list(limit: int = 50):
    if state["hand_history"] is None:
        raise HTTPException(400, "no table")
    return {"hands": state["hand_history"].list_summaries(limit=limit)}


@app.get("/api/hand_history/{hand_number}")
def hand_history_detail(hand_number: int):
    if state["hand_history"] is None:
        raise HTTPException(400, "no table")
    entry = state["hand_history"].get(hand_number)
    if entry is None:
        raise HTTPException(404, "hand not found")

    table: Table = state["table"]
    return {
        "hand_number": entry.hand_number,
        "hero_cards": entry.hero_cards,
        "final_board": entry.final_board,
        "hero_net": round(entry.hero_net, 2),
        "rake": round(entry.rake, 2),
        "payouts": entry.payouts,
        "action_log": [
            {
                "seat": a["seat"],
                "name": table.players[a["seat"]].name if a["seat"] in table.players else f"Seat{a['seat']}",
                "street": a["street"],
                "action": a["action"],
                "amount": round(a["amount"], 2) if a["amount"] else None,
            }
            for a in entry.action_log
        ],
        "decisions": [
            {
                "street": d.street,
                "pot_before": round(d.pot_before, 2),
                "to_call": round(d.to_call, 2),
                "action": d.action,
                "amount": round(d.amount, 2) if d.amount else None,
                "equity_vs_range": round(d.equity_vs_range, 4) if d.equity_vs_range is not None else None,
                "ev_call": round(d.ev_call, 3) if d.ev_call is not None else None,
                "verdict": d.verdict,
                "is_mistake": d.is_mistake,
                "confidence": round(d.confidence, 2),
                "trainer_grade": d.trainer_grade,
                "solver_ev_loss": round(d.solver_ev_loss, 3) if getattr(d, "solver_ev_loss", None) is not None else None,
                "solver_action": getattr(d, "solver_action", None),
                "solver_amount": round(d.solver_amount, 2) if getattr(d, "solver_amount", None) is not None else None,
            }
            for d in entry.decisions
        ],
    }


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
