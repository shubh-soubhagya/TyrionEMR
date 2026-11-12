"""Item 9: the bundled breached-password list."""
from app.domain.password_policy import check_password, load_common_passwords


def test_list_is_large_lowercase_and_policy_length():
    words = load_common_passwords()
    assert len(words) > 100_000
    assert all(w == w.lower() and len(w) >= 10 and not w.startswith("#") for w in words)


def test_a_known_breached_password_is_rejected_case_insensitively():
    common = load_common_passwords()
    for candidate in ("iloveyou123", "ILoveYou123", "Iloveyou12"):
        assert "TOO_COMMON" in {v.code for v in check_password(candidate, "dr.rao@nephrocare.demo", common)}, candidate


def test_project_words_are_rejected_too():
    assert "TOO_COMMON" in {v.code for v in check_password("Nephrocare123", "x@y.test", load_common_passwords())}


def test_a_strong_unlisted_password_is_accepted():
    assert check_password("Kidney2026care", "dr.rao@nephrocare.demo", load_common_passwords()) == []


def test_the_list_is_loaded_once():
    assert load_common_passwords() is load_common_passwords()
