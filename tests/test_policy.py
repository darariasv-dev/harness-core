from harness_core.policy import load_yaml_policy, write_yaml_policy


def test_load_yaml_policy_missing_file_returns_empty(tmp_path):
    data, content_hash = load_yaml_policy(tmp_path / "nonexistent.yaml")
    assert data == {}
    assert content_hash == ""


def test_load_yaml_policy_returns_data_and_stable_hash(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("a: 1\nb:\n  - x\n")
    data1, hash1 = load_yaml_policy(path)
    data2, hash2 = load_yaml_policy(path)
    assert data1 == {"a": 1, "b": ["x"]}
    assert hash1 == hash2 and hash1


def test_load_yaml_policy_hash_changes_with_content(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("a: 1\n")
    _, hash1 = load_yaml_policy(path)
    path.write_text("a: 2\n")
    _, hash2 = load_yaml_policy(path)
    assert hash1 != hash2


def test_write_yaml_policy_preserves_header_comments(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("# A header.\n# Second line.\na: 1\n")
    write_yaml_policy(path, {"a": 2, "b": 3})
    text = path.read_text()
    assert "# A header." in text
    assert "# Second line." in text
    reloaded, _ = load_yaml_policy(path)
    assert reloaded == {"a": 2, "b": 3}


def test_write_yaml_policy_new_file_no_header(tmp_path):
    path = tmp_path / "new.yaml"
    write_yaml_policy(path, {"a": 1})
    reloaded, _ = load_yaml_policy(path)
    assert reloaded == {"a": 1}
