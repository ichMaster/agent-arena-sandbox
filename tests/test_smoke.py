"""Smoke test: the toolchain runs and the top-level packages import on a fresh checkout."""


def test_toolchain_runs() -> None:
    assert True


def test_packages_are_importable() -> None:
    import agent  # noqa: F401
    import games  # noqa: F401
    import server  # noqa: F401
