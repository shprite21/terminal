from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_empty_dashboard_has_no_performance(monkeypatch,tmp_path):
    monkeypatch.setenv("EVIDENCE_DATA_DIR",str(tmp_path))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"),default_timeout=20).run()
    assert not app.exception
    assert any("No lab data loaded" in info.value for info in app.info)
    assert all(metric.label not in {"Net return","Maximum drawdown"} for metric in app.metric)
    app.sidebar.radio[0].set_value("Market making").run()
    assert not app.exception
    assert not app.metric
    app.sidebar.radio[0].set_value("Advanced daily research").run()
    for page in ["Data & connection","Hypotheses","Strategy","Research & validation","Experiments & reports","Forward review"]:
        app.sidebar.radio[1].set_value(page).run()
        assert not app.exception


def test_real_computed_report_renders(monkeypatch,registered):
    from evidence.experiments import run_experiment
    store,key,_=registered
    run_experiment(store,key)
    monkeypatch.setenv("EVIDENCE_DATA_DIR",str(store.root))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"),default_timeout=20).run()
    app.sidebar.radio[0].set_value("Advanced daily research").run()
    app.sidebar.radio[1].set_value("Experiments & reports").run()
    assert not app.exception
    assert any(m.label=="Net return" for m in app.metric)


def test_lab_forms_and_comparison_render(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_DATA_DIR",str(tmp_path))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"),default_timeout=30).run()
    next(r for r in app.radio if r.label == "Data source").set_value("Synthetic scenario").run()
    next(b for b in app.button if b.label == "Generate synthetic history").click().run()
    assert not app.exception
    assert not app.error
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check()
    next(b for b in app.button if b.label == "Compare both periods").click().run()
    assert not app.exception
    assert not app.error
    assert any("Saved report dataset" in c.value for c in app.caption)
    app.sidebar.radio[0].set_value("Market making").run()
    next(n for n in app.number_input if n.label == "Events").set_value(100)
    next(c for c in app.checkbox if c.label.startswith("I understand")).check()
    next(b for b in app.button if b.label == "Run market-making scenario").click().run()
    assert not app.exception
    assert not app.error
    assert any(m.label == "Synthetic net P&L" for m in app.metric)
