import pytest

from app.interview import Session, batch_size, normalize
from app.models import FormField, FormSchema, SourceKind


@pytest.mark.parametrize(
    "remaining,expected", [(1, 1), (3, 3), (4, 4), (6, 6), (7, 4), (8, 4), (12, 6), (13, 5), (20, 5)]
)
def test_batch_size(remaining, expected):
    assert batch_size(remaining) == expected


def make_form(n: int, required: bool = True) -> FormSchema:
    return FormSchema(
        id="f",
        title="T",
        kind=SourceKind.PDF,
        source="t.pdf",
        fields=[FormField(id=f"q{i}", label=f"Q{i}", required=required) for i in range(n)],
    )


def test_batches_cover_all_fields_in_groups_of_4_to_6():
    s = Session(form=make_form(13))
    sizes = []
    while batch := s.next_batch():
        sizes.append(len(batch))
        s.apply({f.id: "x" for f in batch}, [])
    assert sizes == [5, 4, 4]


def test_unanswered_required_are_reasked_then_left_for_review():
    s = Session(form=make_form(5))
    assert len(s.next_batch()) == 5
    s.apply({"q0": "a", "q1": "b", "q2": "c"}, [])  # q3, q4 unanswered
    assert [f.id for f in s.next_batch()] == ["q3", "q4"]
    assert s.next_batch() == []  # asked twice: review screen handles it
    assert [f.id for f in s.missing_required()] == ["q3", "q4"]


def test_optional_asked_once_and_skip():
    s = Session(form=make_form(2, required=False))
    s.next_batch()
    s.apply({}, ["q0"])
    assert s.next_batch() == []


def test_normalize():
    choice = FormField(id="c", label="c", type="choice", options=["Vacation", "Sick leave"])
    assert normalize(choice, "vacation") == "Vacation"
    assert normalize(choice, "sick") == "Sick leave"
    assert normalize(choice, "Bereavement") is None
    box = FormField(id="b", label="b", type="checkbox", options=["A", "B", "C"])
    assert normalize(box, "a, c") == ["A", "C"]
    assert normalize(FormField(id="d", label="d", type="date"), "2026-10-09") == "2026-10-09"
    assert normalize(FormField(id="d", label="d", type="date"), "next friday") is None
    assert normalize(FormField(id="t", label="t", type="time"), "9:05") == "09:05"
    assert normalize(FormField(id="y", label="y", type="boolean"), "Yes") is True
    assert normalize(FormField(id="n", label="n", type="number"), "1,200") == "1200"
