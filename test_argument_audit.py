from argument_audit import replacement


def test_replacement_is_different_and_type_stable():
    values = [True, 1, 1.0, "hello", "2026-01-01", "a@example.com", [1], {"a": 1}]
    for value in values:
        mutated = replacement(value)
        assert mutated != value
        assert type(mutated) is type(value)
