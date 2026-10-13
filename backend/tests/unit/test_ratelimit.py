import pytest
from starlette.requests import Request

from app.ratelimit import Limit, RateLimitedError, RateLimiter, client_ip
from app.settings import Settings


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def limiter(clock: Clock, spec: str = "3/1m", *, enabled: bool = True) -> RateLimiter:
    return RateLimiter({"b": Limit.parse(spec)}, enabled=enabled, clock=clock)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("20/1m", Limit(20, 60)), ("10/15m", Limit(10, 900)), (" 5 / 30s ", Limit(5, 30))],
)
def test_parse(spec: str, expected: Limit) -> None:
    assert Limit.parse(spec) == expected
    assert Limit.parse("1/2h") == Limit(1, 7200)


@pytest.mark.parametrize("spec", ["", "20", "20/m", "20/1d", "0/1m", "5/0s", "-1/1m"])
def test_parse_rejects(spec: str) -> None:
    with pytest.raises(ValueError, match="rate limit"):
        Limit.parse(spec)


def test_settings_validate_and_list_limits() -> None:
    limits = Settings(_env_file=None).rate_limits
    assert limits["chat"] == Limit(20, 60)
    assert limits["login"] == Limit(10, 900)
    assert set(limits) == {
        "login",
        "login_ip",
        "login_email",
        "signup",
        "chat",
        "generate",
        "tts",
        "asr",
    }
    with pytest.raises(ValueError, match="rate limit"):
        Settings(_env_file=None, rate_limit_tts="lots")


def test_window_slides() -> None:
    clock = Clock()
    rl = limiter(clock)
    for at in (1000, 1010, 1030):
        clock.now = at
        rl.hit("b", "k")
    with pytest.raises(RateLimitedError) as caught:
        rl.hit("b", "k")
    # The oldest hit (1000) leaves the window at 1060; now is 1030.
    assert caught.value.retry_after == 30
    assert caught.value.bucket == "b"
    clock.now = 1060
    rl.hit("b", "k")  # the first hit has left
    with pytest.raises(RateLimitedError):
        rl.hit("b", "k")


def test_retry_after_rounds_up_and_is_at_least_one() -> None:
    clock = Clock()
    rl = limiter(clock, "1/1m")
    rl.hit("b", "k")
    clock.now += 59.2
    with pytest.raises(RateLimitedError) as caught:
        rl.check("b", "k")
    assert caught.value.retry_after == 1
    clock.now = 1000.5
    with pytest.raises(RateLimitedError) as caught:
        rl.check("b", "k")
    assert caught.value.retry_after == 60


def test_refused_hits_are_not_recorded() -> None:
    clock = Clock()
    rl = limiter(clock, "1/1m")
    rl.hit("b", "k")
    for _ in range(5):
        clock.now += 10
        with pytest.raises(RateLimitedError):
            rl.hit("b", "k")
    clock.now = 1060
    rl.hit("b", "k")


def test_keys_are_separate_and_reset_clears_one() -> None:
    clock = Clock()
    rl = limiter(clock, "1/1m")
    rl.hit("b", "alice")
    rl.hit("b", "bob")
    rl.reset("b", "alice")
    rl.hit("b", "alice")
    with pytest.raises(RateLimitedError):
        rl.hit("b", "bob")


def test_check_does_not_record() -> None:
    clock = Clock()
    rl = limiter(clock, "1/1m")
    for _ in range(3):
        rl.check("b", "k")
    rl.record("b", "k")
    with pytest.raises(RateLimitedError):
        rl.check("b", "k")


def test_disabled_never_limits() -> None:
    rl = limiter(Clock(), "1/1m", enabled=False)
    for _ in range(5):
        rl.hit("b", "k")


def test_sweep_forgets_idle_keys() -> None:
    clock = Clock()
    rl = limiter(clock, "1/1m")
    rl.hit("b", "old")
    clock.now += 30
    rl.hit("b", "new")
    clock.now += 31
    rl.sweep()
    assert list(rl._hits) == [("b", "new")]


def _request(headers: dict[str, str], peer: tuple[str, int] | None = ("10.0.0.5", 1)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": peer})


def test_client_ip_takes_rightmost_forwarded_entry() -> None:
    assert client_ip(_request({"X-Forwarded-For": "1.1.1.1"})) == "1.1.1.1"
    # A spoofed entry on the left is ignored once a proxy has added the real one.
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6, 2.2.2.2"})) == "2.2.2.2"
    assert client_ip(_request({"X-Forwarded-For": " , "})) == "10.0.0.5"
    assert client_ip(_request({})) == "10.0.0.5"
    assert client_ip(_request({}, peer=None)) == "unknown"
