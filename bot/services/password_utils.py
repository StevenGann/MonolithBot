"""
Password generation utilities for MonolithBot.

This module provides secure password generation for the multi-service
user registration feature. It uses Python's `secrets` module which is
designed for cryptographic purposes.

Key Features:
    - Cryptographically secure random password generation
    - Configurable password length and character sets
    - Excludes ambiguous characters by default (0, O, l, 1, I)

Example:
    >>> from bot.services.password_utils import generate_password
    >>>
    >>> # Generate a 16-character password (default)
    >>> password = generate_password()
    >>> print(password)  # e.g., "Kx7$mP9qL2nR4wJf"
    >>>
    >>> # Generate a longer password
    >>> password = generate_password(length=24)
    >>>
    >>> # Generate without special characters
    >>> password = generate_password(include_special=False)

See Also:
    - bot.services.registration: Uses this for generating user passwords
    - https://docs.python.org/3/library/secrets.html
"""

import secrets
import string


# Default character sets for password generation
# Excludes ambiguous characters: 0, O, o, l, 1, I
LOWERCASE = "abcdefghjkmnpqrstuvwxyz"  # No 'l' or 'o'
UPPERCASE = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # No 'I' or 'O'
DIGITS = "23456789"  # No '0' or '1'
SPECIAL = "!@#$%^&*"

# Full alphabet without ambiguous characters
UNAMBIGUOUS_LETTERS = LOWERCASE + UPPERCASE
UNAMBIGUOUS_ALL = UNAMBIGUOUS_LETTERS + DIGITS


def generate_password(
    length: int = 16,
    include_special: bool = True,
    include_digits: bool = True,
    include_uppercase: bool = True,
    include_lowercase: bool = True,
) -> str:
    """
    Generate a cryptographically secure random password.

    Uses the `secrets` module for secure random generation, which is
    suitable for generating passwords, tokens, and other security-sensitive
    data.

    By default, generates a 16-character password with:
    - Lowercase letters (a-z, excluding ambiguous: l, o)
    - Uppercase letters (A-Z, excluding ambiguous: I, O)
    - Digits (2-9, excluding ambiguous: 0, 1)
    - Special characters (!@#$%^&*)

    The generated password is guaranteed to contain at least one character
    from each enabled character set.

    Args:
        length: Length of the password. Must be at least 8 characters.
            Defaults to 16.
        include_special: Whether to include special characters (!@#$%^&*).
            Defaults to True.
        include_digits: Whether to include digits (2-9).
            Defaults to True.
        include_uppercase: Whether to include uppercase letters.
            Defaults to True.
        include_lowercase: Whether to include lowercase letters.
            Defaults to True.

    Returns:
        A randomly generated password string.

    Raises:
        ValueError: If length is less than 8, or if no character sets
            are enabled.

    Example:
        >>> password = generate_password()
        >>> len(password)
        16

        >>> password = generate_password(length=24, include_special=False)
        >>> len(password)
        24
        >>> all(c not in "!@#$%^&*" for c in password)
        True
    """
    if length < 8:
        raise ValueError("Password length must be at least 8 characters")

    # Build the character set based on options
    charset = ""
    required_chars = []

    if include_lowercase:
        charset += LOWERCASE
        required_chars.append(secrets.choice(LOWERCASE))

    if include_uppercase:
        charset += UPPERCASE
        required_chars.append(secrets.choice(UPPERCASE))

    if include_digits:
        charset += DIGITS
        required_chars.append(secrets.choice(DIGITS))

    if include_special:
        charset += SPECIAL
        required_chars.append(secrets.choice(SPECIAL))

    if not charset:
        raise ValueError("At least one character set must be enabled")

    # Calculate remaining characters needed
    remaining_length = length - len(required_chars)

    if remaining_length < 0:
        raise ValueError(
            f"Password length {length} is too short to include all required "
            f"character types ({len(required_chars)} required)"
        )

    # Generate remaining random characters
    remaining_chars = [secrets.choice(charset) for _ in range(remaining_length)]

    # Combine required and remaining characters
    all_chars = required_chars + remaining_chars

    # Shuffle the characters to randomize positions
    # Using Fisher-Yates shuffle with secrets for security
    shuffled = all_chars.copy()
    for i in range(len(shuffled) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]

    return "".join(shuffled)


def generate_simple_password(length: int = 16) -> str:
    """
    Generate a simple alphanumeric password without special characters.

    This is useful for services that have restrictions on special
    characters in passwords.

    Args:
        length: Length of the password. Must be at least 8 characters.
            Defaults to 16.

    Returns:
        A randomly generated alphanumeric password string.

    Example:
        >>> password = generate_simple_password()
        >>> password.isalnum()
        True
    """
    return generate_password(
        length=length,
        include_special=False,
        include_digits=True,
        include_uppercase=True,
        include_lowercase=True,
    )


def is_strong_password(password: str) -> bool:
    """
    Check if a password meets minimum strength requirements.

    A strong password must:
    - Be at least 8 characters long
    - Contain at least one lowercase letter
    - Contain at least one uppercase letter
    - Contain at least one digit

    Args:
        password: The password to check.

    Returns:
        True if the password meets all requirements, False otherwise.

    Example:
        >>> is_strong_password("Weak1")
        False
        >>> is_strong_password("StrongPass123")
        True
    """
    if len(password) < 8:
        return False

    has_lower = any(c in string.ascii_lowercase for c in password)
    has_upper = any(c in string.ascii_uppercase for c in password)
    has_digit = any(c in string.digits for c in password)

    return has_lower and has_upper and has_digit
