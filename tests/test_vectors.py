"""The two arithmetic functions the loop guard and the memory store both stand on.

They lived in `safety.py` and were tested there, as an aside to the firewall. They are now
`kernel/vectors.py` — rank 0, no opinions — and the mismatched-length rule below is the
reason the split was worth making explicit: it is a *safety* decision expressed as a return
value, and until now the docstring was the only place it was written down.
"""

import pytest

from corparius.kernel.vectors import cosine, hash_embed


def test_cosine_of_identical_vectors_is_one():
    v = hash_embed("hello world")
    assert cosine(v, v) == pytest.approx(1.0)


def test_unrelated_texts_are_not_similar():
    assert cosine(hash_embed("quarterly revenue forecast"), hash_embed("")) == 0.0


def test_mismatched_lengths_read_as_not_a_stutter_rather_than_raising():
    """The docstring's claim, which nothing checked. LoopGuard treats 0.0 as "not a
    stutter", so an embedding model swapped in mid-run — changing the dimension — lets the
    agent carry on instead of halting its day on an arithmetic detail. Truncating to the
    shorter prefix would instead produce a real-looking number from two unrelated vectors,
    which is the failure mode worth refusing.
    """
    assert cosine(hash_embed("same text", dim=64), hash_embed("same text", dim=32)) == 0.0


def test_the_embedding_is_deterministic_across_processes():
    """`hash_embed` feeds `store.remember`, which uses it to decide that an incoming fact is
    a near-duplicate of one already held. A value that shifted between runs would make that
    check quietly stop deduplicating."""
    assert hash_embed("coaches and mentors") == hash_embed("coaches and mentors")
    assert hash_embed("a b") == hash_embed("A  B")  # lowercased, whitespace-split
