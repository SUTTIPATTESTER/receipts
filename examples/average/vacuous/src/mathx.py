def average(xs):
    """Return the arithmetic mean of xs (0.0 for an empty list)."""
    if not xs:
        return 0.0
    return sum(xs) / len(xs)
