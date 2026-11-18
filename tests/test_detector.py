import random

from clipper.detector import DetectorConfig, SpikeDetector

T0 = 1_000_000.0


def feed(det, rng, start, end, rate, users=5000):
    for sec in range(start, end):
        for _ in range(rate):
            det.add(f"u{rng.randint(0, users)}", T0 + sec + rng.random())


def test_fires_on_explosion_with_correct_onset():
    rng = random.Random(1)
    det = SpikeDetector(DetectorConfig())
    feed(det, rng, 0, 200, 5)
    assert all(det.check(T0 + s) is None for s in range(61, 201))
    feed(det, rng, 200, 210, 60)
    spikes = [sp for s in range(201, 211) if (sp := det.check(T0 + s))]
    assert len(spikes) == 1
    assert spikes[0].onset == T0 + 200
    assert spikes[0].baseline < 7


def test_no_false_alarm_on_steady_busy_chat():
    rng = random.Random(2)
    det = SpikeDetector(DetectorConfig())
    for sec in range(900):
        feed(det, rng, sec, sec + 1, rng.randint(30, 50))
        assert det.check(T0 + sec + 1) is None


def test_single_spammer_does_not_trigger():
    rng = random.Random(3)
    det = SpikeDetector(DetectorConfig())
    feed(det, rng, 0, 200, 3)
    for sec in range(200, 210):
        for i in range(100):
            det.add("spammer", T0 + sec + i / 100)
    assert all(det.check(T0 + s) is None for s in range(201, 211))


def test_cooldown_and_warmup():
    rng = random.Random(4)
    cfg = DetectorConfig(cooldown=90, warmup=60)
    det = SpikeDetector(cfg)
    feed(det, rng, 0, 30, 2)
    feed(det, rng, 30, 40, 50)
    assert all(det.check(T0 + s) is None for s in range(31, 41))  # still warming up
    feed(det, rng, 40, 200, 2)
    feed(det, rng, 200, 205, 50)
    assert det.check(T0 + 205) is not None
    feed(det, rng, 205, 240, 2)
    feed(det, rng, 240, 245, 50)
    assert det.check(T0 + 245) is None  # inside cooldown


def test_detects_relative_spike_on_huge_channel():
    rng = random.Random(5)
    det = SpikeDetector(DetectorConfig())
    feed(det, rng, 0, 300, 80, users=200000)
    feed(det, rng, 300, 306, 400, users=200000)
    assert any(det.check(T0 + s) for s in range(301, 307))


def _poisson_chat(det, rng, start, end, rate):
    import math
    for sec in range(start, end):
        # Poisson-distributed message counts, like real chat
        lam, k, p, limit = rate, 0, 1.0, math.exp(-rate)
        while p > limit:
            k += 1
            p *= rng.random()
        for _ in range(k - 1):
            det.add(f"u{rng.randint(0, 10**6)}", T0 + sec + rng.random())


def _fires(det, start, end):
    return [s for s in (det.check(T0 + t) for t in range(start, end)) if s]


def test_big_chat_clips_on_a_smaller_jump():
    """6 msg/s normal: 2.5x (15 msg/s) never reached 3x before, but it's a real moment."""
    rng = random.Random(10)
    det = SpikeDetector(DetectorConfig())
    _poisson_chat(det, rng, 0, 300, 6)
    assert not _fires(det, 61, 300)
    _poisson_chat(det, rng, 300, 310, 15)
    assert _fires(det, 300, 311)


def test_small_chat_needs_more_than_tripling():
    """1.5 msg/s normal: tripling to 4.5 msg/s is just a few people talking, not a moment."""
    rng = random.Random(11)
    det = SpikeDetector(DetectorConfig())
    _poisson_chat(det, rng, 0, 300, 1.5)
    _poisson_chat(det, rng, 300, 310, 4.5)
    assert not _fires(det, 61, 311)
    _poisson_chat(det, rng, 311, 500, 1.5)
    _poisson_chat(det, rng, 500, 510, 9)            # a real burst still clips
    assert _fires(det, 500, 511)


def test_no_false_alarms_on_steady_chats_of_any_size():
    for rate, seed in ((1.5, 1), (6, 2), (15, 3), (40, 4)):
        rng = random.Random(seed)
        det = SpikeDetector(DetectorConfig())
        _poisson_chat(det, rng, 0, 1200, rate)
        assert not _fires(det, 61, 1200), rate
