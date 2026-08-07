from backend.dossier import SeatDossier


def test_dossier_context_metrics_are_available():
    dossier = SeatDossier()
    dossier.position_vpip["BTN"] = 1
    dossier.position_pfr["BTN"] = 1
    dossier.postflop_aggression["flop"] = 2

    assert dossier.position_vpip["BTN"] == 1
    assert dossier.position_pfr["BTN"] == 1
    assert dossier.postflop_aggression["flop"] == 2
