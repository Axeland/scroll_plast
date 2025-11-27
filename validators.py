import re
from typing import Union

# Regex for basic email validation, loosely based on RFC 5322
EMAIL_REGEX = re.compile(
    r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
)

class ValidationError(ValueError):
    """Custom exception for validation failures."""
    pass


def is_valid_email(email: str) -> bool:
    """
    Validates if the given string is a valid email address.

    Args:
        email: The string to validate.

    Returns:
        True if the email is valid, False otherwise.
    """
    if not isinstance(email, str):
        return False
    return EMAIL_REGEX.match(email) is not None


def validate_email(email: str) -> None:
    """
    Validates an email address, raising ValidationError on failure.

    Args:
        email: The string to validate.

    Raises:
        ValidationError: If the email is invalid.
    """
    if not is_valid_email(email):
        raise ValidationError(f"'{email}' is not a valid email address.")


def is_in_range(
    value: Union[int, float],
    min_val: Union[int, float, None] = None,
    max_val: Union[int, float, None] = None
) -> bool:
    """
    Checks if a numeric value is within a specified range (inclusive).

    Args:
        value: The number to check.
        min_val: The minimum allowed value (inclusive). If None, no lower bound.
        max_val: The maximum allowed value (inclusive). If None, no upper bound.

    Returns:
        True if the value is within the range, False otherwise.
    """
    if min_val is not None and value < min_val:
        return False
    if max_val is not None and value > max_val:
        return False
    return True


def validate_range(
    value: Union[int, float],
    min_val: Union[int, float, None] = None,
    max_val: Union[int, float, None] = None
) -> None:
    """
    Validates if a numeric value is in a range, raising ValidationError on failure.

    Args:
        value: The number to check.
        min_val: The minimum allowed value (inclusive). If None, no lower bound.
        max_val: The maximum allowed value (inclusive). If None, no upper bound.

    Raises:
        ValidationError: If the value is outside the specified range.
    """
    if not is_in_range(value, min_val, max_val):
        if min_val is not None and max_val is not None:
            range_str = f"between {min_val} and {max_val}"
        elif min_val is not None:
            range_str = f"greater than or equal to {min_val}"
        elif max_val is not None:
            range_str = f"less than or equal to {max_val}"
        else:
            # This case should not be triggered by is_in_range, but for completeness
            return

        raise ValidationError(f"Value {value} is not in the required range ({range_str}).")
