import pytest

from apostrophed.rules import load_rules


def test_loads_all_rules():
    rules = load_rules("data/rules.tsv")
    assert len(rules) == 45
    assert rules["didnt"] == "didn't"
    assert rules["im"] == "I'm"
    assert rules["i"] == "I"


def test_excluded_collision_words_absent():
    rules = load_rules("data/rules.tsv")
    for w in ["its", "were", "well", "ill", "id", "wed", "shed", "cant", "wont", "lets"]:
        assert w not in rules


def test_comments_and_blanks_skipped(tmp_path):
    f = tmp_path / "r.tsv"
    f.write_text("# c\n\ndidnt\tdidn't\n")
    assert load_rules(f) == {"didnt": "didn't"}


def test_malformed_line_raises(tmp_path):
    f = tmp_path / "r.tsv"
    f.write_text("didnt didn't\n")  # space, no tab
    with pytest.raises(ValueError):
        load_rules(f)


def test_duplicate_trigger_raises(tmp_path):
    f = tmp_path / "r.tsv"
    f.write_text("didnt\tdidn't\ndidnt\tdidn't\n")
    with pytest.raises(ValueError):
        load_rules(f)


def test_non_lowercase_trigger_raises(tmp_path):
    f = tmp_path / "r.tsv"
    f.write_text("Didnt\tDidn't\n")
    with pytest.raises(ValueError):
        load_rules(f)
