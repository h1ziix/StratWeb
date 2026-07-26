"""KAST boolean composition kept separate for definition-level testing."""


def is_kast(*, kill: bool, assist: bool, survived: bool, traded: bool) -> bool:
    return kill or assist or survived or traded
