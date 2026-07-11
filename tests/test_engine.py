from apostrophed.engine import Engine
from apostrophed.rules import load_rules
from apostrophed.tokens import Backspace, Correction, Letter, Reset, WordBoundary

RULES = load_rules("data/rules.tsv")


def feed_word(engine, s):
    """Feed each letter of ``s`` then a WordBoundary; return the boundary result."""
    for c in s:
        engine.feed(Letter(c))
    return engine.feed(WordBoundary())


def test_basic_contraction():
    e = Engine(RULES)
    assert feed_word(e, "didnt") == Correction(5, "didn't")


def test_first_upper_preserved():
    assert feed_word(Engine(RULES), "Didnt") == Correction(5, "Didn't")


def test_all_upper():
    assert feed_word(Engine(RULES), "DIDNT") == Correction(5, "DIDN'T")


def test_intrinsic_capital_lowercase_typed():
    assert feed_word(Engine(RULES), "im") == Correction(2, "I'm")


def test_standalone_i():
    assert feed_word(Engine(RULES), "i") == Correction(1, "I")


def test_noop_skip_when_already_correct():
    # typing capital "I" already: key 'i', result 'I' == typed -> no rewrite
    e = Engine(RULES)
    e.feed(Letter("I"))
    assert e.feed(WordBoundary()) is None


def test_mixed_case_no_correction():
    assert feed_word(Engine(RULES), "dIdnt") is None


def test_non_trigger_word():
    assert feed_word(Engine(RULES), "hello") is None


def test_backspace_syncs_buffer():
    e = Engine(RULES)
    for c in "dont":
        e.feed(Letter(c))
    e.feed(Backspace())  # buffer now "don"
    for c in "e":
        e.feed(Letter(c))  # "done"
    assert e.feed(WordBoundary()) is None


def test_backspace_on_empty_is_noop():
    e = Engine(RULES)
    e.feed(Backspace())  # must not underflow/raise
    assert feed_word(e, "dont") == Correction(4, "don't")


def test_reset_clears_buffer():
    e = Engine(RULES)
    for c in "dont":
        e.feed(Letter(c))
    e.feed(Reset())
    assert e.feed(WordBoundary()) is None


def test_boundary_clears_between_words():
    e = Engine(RULES)
    assert feed_word(e, "hello") is None
    assert feed_word(e, "dont") == Correction(4, "don't")


def test_empty_boundary_is_noop():
    # a lone boundary (no letters buffered) must not match or crash
    assert Engine(RULES).feed(WordBoundary()) is None


def test_first_upper_intrinsic_capital():
    # "Im" -> first-upper applied to "I'm" stays "I'm"
    assert feed_word(Engine(RULES), "Im") == Correction(2, "I'm")


def test_every_rule_roundtrips():
    e = Engine(RULES)
    for trig, repl in RULES.items():
        assert feed_word(e, trig) == Correction(len(trig), repl)
