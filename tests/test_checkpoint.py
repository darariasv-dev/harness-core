from harness_core.checkpoint import FIELDS, format_checkpoint_block, parse_checkpoint_block


def _fields(**overrides):
    base = {name: f"{name.lower()} value" for name in FIELDS}
    base.update(overrides)
    return base


def test_format_requires_all_fields():
    incomplete = {name: "x" for name in FIELDS[:-1]}
    try:
        format_checkpoint_block(incomplete)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "UPDATED" in str(exc)


def test_format_includes_every_label_in_order():
    text = format_checkpoint_block(_fields())
    positions = [text.index(f"{name}:") for name in FIELDS]
    assert positions == sorted(positions)


def test_format_empty_field_becomes_n_a():
    text = format_checkpoint_block(_fields(BLOCKER=""))
    assert "BLOCKER:" in text
    assert "n/a" in text.split("BLOCKER:")[1].split("\n")[0]


def test_round_trip_short_values():
    fields = _fields()
    text = format_checkpoint_block(fields)
    parsed = parse_checkpoint_block(text)
    for name in FIELDS:
        assert parsed[name] == fields[name]


def test_round_trip_long_wrapped_value():
    long_value = "word " * 40
    fields = _fields(COMPLETED=long_value.strip())
    text = format_checkpoint_block(fields)
    # confirm it actually wrapped across multiple lines
    assert text.count("\n") >= len(FIELDS)
    parsed = parse_checkpoint_block(text)
    assert parsed["COMPLETED"] == long_value.strip()


def test_parse_returns_none_when_no_command_line():
    assert parse_checkpoint_block("just some prose\nno checkpoint block here") is None


def test_parse_stops_at_end_of_block():
    text = format_checkpoint_block(_fields()) + "\n\n## Some other section\nMore prose here."
    parsed = parse_checkpoint_block(text)
    assert parsed["UPDATED"] == "updated value"
