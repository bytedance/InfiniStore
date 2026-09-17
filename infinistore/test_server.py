import asyncio
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from infinistore import lib, server


def parse_args(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["infinistore", *args])
    return server.parse_args()


@pytest.mark.parametrize(
    "args, expected",
    [
        ([], (0.6, 0.8, 5)),
        (["--evict-min-threshold", "0.25"], (0.25, 0.8, 5)),
        (["--evict-max-threshold", "0.9"], (0.6, 0.9, 5)),
        (["--evict-interval", "2"], (0.6, 0.8, 2)),
        (
            [
                "--evict-min-threshold",
                "0",
                "--evict-max-threshold",
                "1",
                "--evict-interval",
                "1",
            ],
            (0.0, 1.0, 1),
        ),
    ],
)
def test_eviction_argument_types(monkeypatch, args, expected):
    config = lib.ServerConfig(**vars(parse_args(monkeypatch, *args)))
    config.verify()
    values = (
        config.evict_min_threshold,
        config.evict_max_threshold,
        config.evict_interval,
    )
    assert values == expected
    assert tuple(type(value) for value in values) == (float, float, int)


@pytest.mark.parametrize(
    "option, value",
    [
        ("--evict-interval", "abc"),
        ("--evict-interval", "1.5"),
        ("--evict-min-threshold", "abc"),
        ("--evict-max-threshold", "abc"),
    ],
)
def test_invalid_eviction_arguments(monkeypatch, capsys, option, value):
    with pytest.raises(SystemExit) as exc:
        parse_args(monkeypatch, f"{option}={value}")
    assert exc.value.code == 2
    assert option in capsys.readouterr().err


def test_periodic_eviction_with_cli_arguments(monkeypatch):
    config = lib.ServerConfig(
        **vars(
            parse_args(
                monkeypatch,
                "--enable-periodic-evict",
                "--evict-min-threshold",
                "0.25",
                "--evict-max-threshold",
                "0.75",
                "--evict-interval",
                "2",
            )
        )
    )
    config.verify()
    evict = Mock()
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(lib._infinistore, "evict_cache", evict)
    monkeypatch.setattr(server.asyncio, "sleep", sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await server.periodic_evict(
                config.evict_min_threshold,
                config.evict_max_threshold,
                config.evict_interval,
            )

    asyncio.run(run())
    evict.assert_called_once_with(0.25, 0.75)
    sleep.assert_awaited_once_with(2)
