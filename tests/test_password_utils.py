"""
Unit tests for bot/services/password_utils.py - Secure password generation.

Tests cover:
    - Password generation with various options
    - Character set inclusion/exclusion
    - Password strength validation
    - Edge cases and error handling
"""

import pytest

from bot.services.password_utils import (
    generate_password,
    generate_simple_password,
    is_strong_password,
)


# Ambiguous characters that should be excluded by default
AMBIGUOUS_CHARACTERS = "0OolI1"


# =============================================================================
# generate_password Tests
# =============================================================================


class TestGeneratePassword:
    """Tests for generate_password function."""

    def test_default_length(self) -> None:
        """Test default password length is 16 characters."""
        password = generate_password()
        assert len(password) == 16

    def test_custom_length(self) -> None:
        """Test custom password lengths."""
        for length in [8, 12, 20, 32, 64]:
            password = generate_password(length=length)
            assert len(password) == length

    def test_minimum_length(self) -> None:
        """Test minimum length of 8 characters."""
        password = generate_password(length=8)
        assert len(password) == 8

    def test_length_too_short_raises_error(self) -> None:
        """Test that length below 8 raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_password(length=7)
        assert "at least 8 characters" in str(exc_info.value)

    def test_includes_special_characters_by_default(self) -> None:
        """Test that special characters are included by default."""
        # Generate multiple passwords to ensure we catch special chars
        passwords = [generate_password(length=32) for _ in range(10)]
        special_chars = set("!@#$%^&*")

        has_special = any(any(c in special_chars for c in pwd) for pwd in passwords)
        assert has_special, "No special characters found in any generated password"

    def test_exclude_special_characters(self) -> None:
        """Test excluding special characters."""
        special_chars = set("!@#$%^&*")

        # Generate many passwords to ensure none have special chars
        for _ in range(20):
            password = generate_password(length=32, include_special=False)
            assert not any(c in special_chars for c in password)

    def test_excludes_ambiguous_characters_by_default(self) -> None:
        """Test that ambiguous characters are excluded by default."""
        # Generate many passwords
        for _ in range(50):
            password = generate_password(length=32)
            for char in AMBIGUOUS_CHARACTERS:
                assert char not in password, f"Found ambiguous char '{char}'"

    def test_contains_letters_and_digits(self) -> None:
        """Test password contains both letters and digits."""
        password = generate_password(length=16)

        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)

        assert has_letter, "Password should contain letters"
        assert has_digit, "Password should contain digits"

    def test_contains_mixed_case(self) -> None:
        """Test password contains both upper and lower case."""
        # Generate longer password to ensure mixed case
        password = generate_password(length=32)

        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)

        assert has_upper, "Password should contain uppercase"
        assert has_lower, "Password should contain lowercase"

    def test_uniqueness(self) -> None:
        """Test that generated passwords are unique."""
        passwords = [generate_password() for _ in range(100)]
        unique_passwords = set(passwords)

        # All passwords should be unique (cryptographically secure)
        assert len(unique_passwords) == 100

    def test_no_whitespace(self) -> None:
        """Test passwords don't contain whitespace."""
        for _ in range(20):
            password = generate_password(length=32)
            assert not any(c.isspace() for c in password)

    def test_no_character_sets_raises_error(self) -> None:
        """Test that disabling all character sets raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_password(
                include_special=False,
                include_digits=False,
                include_uppercase=False,
                include_lowercase=False,
            )
        assert "must be enabled" in str(exc_info.value)


# =============================================================================
# generate_simple_password Tests
# =============================================================================


class TestGenerateSimplePassword:
    """Tests for generate_simple_password function."""

    def test_default_length(self) -> None:
        """Test default length is 16."""
        password = generate_simple_password()
        assert len(password) == 16

    def test_custom_length(self) -> None:
        """Test custom lengths."""
        password = generate_simple_password(length=24)
        assert len(password) == 24

    def test_alphanumeric_only(self) -> None:
        """Test only contains alphanumeric characters."""
        for _ in range(20):
            password = generate_simple_password(length=32)
            assert password.isalnum(), "Password should be alphanumeric only"

    def test_excludes_ambiguous_by_default(self) -> None:
        """Test ambiguous characters are excluded."""
        for _ in range(50):
            password = generate_simple_password(length=32)
            for char in AMBIGUOUS_CHARACTERS:
                assert char not in password

    def test_minimum_length_validation(self) -> None:
        """Test minimum length is enforced."""
        with pytest.raises(ValueError):
            generate_simple_password(length=7)

    def test_no_special_characters(self) -> None:
        """Test no special characters in simple password."""
        special_chars = set("!@#$%^&*")
        for _ in range(20):
            password = generate_simple_password(length=32)
            assert not any(c in special_chars for c in password)


# =============================================================================
# is_strong_password Tests
# =============================================================================


class TestIsStrongPassword:
    """Tests for is_strong_password function."""

    def test_strong_password(self) -> None:
        """Test a properly strong password."""
        assert is_strong_password("MyPassw0rd123")

    def test_generated_password_is_strong(self) -> None:
        """Test that generated passwords are strong."""
        for _ in range(20):
            password = generate_password()
            assert is_strong_password(password)

    def test_too_short(self) -> None:
        """Test password too short."""
        assert not is_strong_password("Ab1!")  # Only 4 chars

    def test_no_uppercase(self) -> None:
        """Test password without uppercase."""
        assert not is_strong_password("mypassw0rd123")

    def test_no_lowercase(self) -> None:
        """Test password without lowercase."""
        assert not is_strong_password("MYPASSW0RD123")

    def test_no_digit(self) -> None:
        """Test password without digits."""
        assert not is_strong_password("MyPasswordABC")

    def test_exactly_8_characters(self) -> None:
        """Test password with exactly minimum length."""
        assert is_strong_password("Abcd1234")  # 8 chars with all requirements

    def test_empty_password(self) -> None:
        """Test empty password."""
        assert not is_strong_password("")

    def test_whitespace_only(self) -> None:
        """Test whitespace-only password."""
        assert not is_strong_password("        ")

    def test_simple_password_is_strong(self) -> None:
        """Test that simple passwords (no special chars) can be strong."""
        # is_strong_password only requires letters and digits, not special chars
        password = generate_simple_password()
        assert is_strong_password(password)
