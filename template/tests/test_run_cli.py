from myproject import run


def test_run_refuses_live_calls_without_the_switch(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(run.LIVE_SWITCH, raising=False)
    monkeypatch.chdir(tmp_path)
    assert run.main(["run"]) == 2
    assert run.LIVE_SWITCH in capsys.readouterr().err


def test_usage_verb_runs_under_the_lock_with_an_empty_ledger(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert run.main(["usage"]) == 0
    assert not (tmp_path / ".workflow.lock").exists()
