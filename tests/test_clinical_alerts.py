from app.clinical.alerts import evaluate_clinical_risks, AlertSeverity


def test_preeclampsia_alert():
    # TA sévère + protéinurie
    data = {
        "tension_systolique": 165,
        "tension_diastolique": 105,
        "proteinurie": "POSITIF",
    }
    alerts = evaluate_clinical_risks(data)
    codes = [a.code for a in alerts]
    assert "PREECLAMPSIE_SEVERE" in codes
    alert = next(a for a in alerts if a.code == "PREECLAMPSIE_SEVERE")
    assert alert.severity == AlertSeverity.ROUGE


def test_fetal_heart_rate_alerts():
    # Bradycardie
    alerts_low = evaluate_clinical_risks({"bcf_bpm": 95})
    assert any(a.code == "BRADYCARDIE_FOETALE" and a.severity == AlertSeverity.ROUGE for a in alerts_low)

    # Tachycardie
    alerts_high = evaluate_clinical_risks({"bcf_bpm": 175})
    assert any(a.code == "TACHYCARDIE_FOETALE" and a.severity == AlertSeverity.ORANGE for a in alerts_high)

    # Normal
    alerts_ok = evaluate_clinical_risks({"bcf_bpm": 140})
    assert not any("FOETALE" in a.code for a in alerts_ok)


def test_infectious_and_anemia_alerts():
    data = {
        "vih": "POSITIF",
        "hemoglobine": 6.8,
        "cesarienne_anterieure": "OUI",
    }
    alerts = evaluate_clinical_risks(data)
    codes = [a.code for a in alerts]
    assert "VIH_POSITIF" in codes
    assert "ANEMIE_TRES_SEVERE" in codes
    assert "UTERUS_CICATRICIEL" in codes
