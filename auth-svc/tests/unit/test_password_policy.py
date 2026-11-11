from app.domain.password_policy import check_password, load_common_passwords

COMMON = frozenset({"password1234"})


def codes(pw: str, email: str = "priya.sharma@clinic.test") -> set[str]:
    return {v.code for v in check_password(pw, email, COMMON)}


def test_valid_password_has_no_violations():
    assert check_password("Kidney2026care", "priya.sharma@clinic.test", COMMON) == []


def test_too_short_nine_vs_ten():
    assert "TOO_SHORT" in codes("Abcdefgh1")
    assert "TOO_SHORT" not in codes("Abcdefghi1")


def test_too_long_128_vs_129():
    ok = "a1" * 64
    assert "TOO_LONG" not in codes(ok)
    assert "TOO_LONG" in codes(ok + "a")


def test_letters_only_needs_digit():
    assert codes("abcdefghijkl") == {"NEEDS_DIGIT"}


def test_digits_only_needs_letter():
    assert codes("123456789012") == {"NEEDS_LETTER"}


def test_common_password_is_case_insensitive():
    assert "TOO_COMMON" in codes("PassWord1234")


def test_contains_email_local_part():
    assert "CONTAINS_EMAIL" in codes("xx-priya.sharma-99")


def test_short_email_local_part_is_ignored():
    assert "CONTAINS_EMAIL" not in codes("Kidney2026care", email="ab@clinic.test")


def test_bundled_list_loads_lowercased():
    common = load_common_passwords()
    assert "password1234" in common
    assert all(p == p.lower() for p in common)
