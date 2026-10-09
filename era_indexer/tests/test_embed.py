import pytest

from career_history import embed


class FakeEmbedder:
    """Fails any request with more than ``max_batch`` texts or a text over ``max_chars``."""

    def __init__(self, max_batch=1000, max_chars=10_000):
        self.max_batch, self.max_chars, self.calls = max_batch, max_chars, []

    def embed_documents(self, texts):
        self.calls.append(len(texts))
        if len(texts) > self.max_batch or any(len(t) > self.max_chars for t in texts):
            raise RuntimeError("connection reset by peer")
        return [[float(len(t))] for t in texts]


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        f = FakeEmbedder(**kw)
        monkeypatch.setattr(embed, "_get_embedder", lambda: f)
        monkeypatch.setattr(embed.config, "get", lambda: {"processing": {"embed_batch_size": 4}})
        monkeypatch.setattr(embed.time, "sleep", lambda s: None)
        return f
    return install


def test_embed_sends_fixed_size_batches(fake):
    f = fake()
    out = embed.embed([f"chunk {i}" for i in range(10)])
    assert len(out) == 10 and f.calls == [4, 4, 2]


def test_failed_batch_is_split_and_order_kept(fake):
    f = fake(max_batch=1)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    assert embed.embed(texts) == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert max(f.calls) == 4


def test_oversized_chunk_is_shortened(fake):
    fake(max_chars=1000)
    out = embed.embed(["x" * 3000, "short"])
    assert out[0] == [750.0] and out[1] == [5.0]


def test_gives_up_when_even_short_text_fails(fake):
    fake(max_chars=10)
    with pytest.raises(RuntimeError):
        embed.embed(["y" * 400])
