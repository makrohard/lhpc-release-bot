"""A rule for a source the controller's `dev` pins and its `main` not yet: the run does not stop on
it, and it never moves it — the run examines only what the manifest it runs on pins."""
from types import SimpleNamespace

import pytest

from bot import cli
from bot import manifest as mf
from bot import upstream as up


def _manifest(*paths):
    comps = "".join(
        f'\n  [[stack.component]]\n  id = "{p.split("/")[-1]}"\n'
        f'    [stack.component.source]\n    path = "{p}"\n    pin_commit = "{"a" * 40}"\n'
        f'    remote = "https://example.invalid/{p.split("/")[-1]}.git"\n    branch = "main"\n'
        for p in paths)
    return f'[[stack]]\nid = "s"\n{comps}'


@pytest.fixture
def seen(monkeypatch, tmp_path):
    examined = []
    monkeypatch.setattr(up, "examine", lambda s, rule, remote: examined.append(s.path) or
                        up.Finding(key=s.path, track=rule.get("track", ""), status="same",
                                   current=s.pin, candidate=s.pin, remote=s.remote))
    for name, value in (("graywolf_version", ""), ("meshtastic_web", ("", "")),
                        ("meshtastic_cli", "")):
        monkeypatch.setattr(mf, name, lambda text, v=value: v)
    return examined, SimpleNamespace(work=tmp_path, token="")


POLICY = {"source": {"src/a": {"track": "tip"},
                     "src/new": {"track": "manual", "why": "moves with another pin, by hand"}}}


def test_a_dev_only_rule_neither_stops_the_run_nor_is_examined(seen):
    examined, ctx = seen
    found, _remote = cli._findings(ctx, _manifest("src/a"), POLICY, _manifest("src/a", "src/new"))
    assert examined == ["src/a"] and [f.key for f in found] == ["src/a"]
    assert not any(f.moves for f in found)


def test_without_dev_the_same_rule_stops_the_run(seen):
    _examined, ctx = seen
    with pytest.raises(cli.Stop, match="src/new: in policy.toml, no longer pinned"):
        cli._findings(ctx, _manifest("src/a"), POLICY, _manifest("src/a"))


# ---- the checker the controller's CI calls (`--manifest PATH`): main is never replaced ----

def _check(monkeypatch, capsys, tmp_path, *, main, dev, candidate, policy):
    from tests import policy_covers_manifest as chk
    by_url = {chk.MANIFEST: main, chk.DEV_MANIFEST: dev}
    monkeypatch.setattr(chk, "_fetch", lambda url: by_url[url])
    monkeypatch.setattr(chk, "load_policy", lambda path: policy)
    path = tmp_path / "candidate.toml"
    path.write_text(candidate)
    monkeypatch.setattr(chk.sys, "argv", ["policy_covers_manifest", "--manifest", str(path)])
    rc = chk.main()
    return rc, capsys.readouterr().out


def test_a_rule_main_still_pins_is_kept_although_dev_and_the_candidate_dropped_it(monkeypatch, capsys,
                                                                                 tmp_path):
    rc, out = _check(monkeypatch, capsys, tmp_path, main=_manifest("src/a", "src/old"),
                     dev=_manifest("src/a"), candidate=_manifest("src/a"),
                     policy={"source": {"src/a": {"track": "tip"}, "src/old": {"track": "tip"}}})
    assert rc == 0, out
    assert "::error::" not in out


def test_a_source_main_pins_needs_its_rule_although_the_candidate_dropped_it(monkeypatch, capsys,
                                                                             tmp_path):
    rc, out = _check(monkeypatch, capsys, tmp_path, main=_manifest("src/a", "src/old"),
                     dev=_manifest("src/a"), candidate=_manifest("src/a"),
                     policy={"source": {"src/a": {"track": "tip"}}})
    assert rc == 1
    assert "::error::src/old: pinned in the manifest, absent from policy.toml" in out
