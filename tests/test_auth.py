"""Tests for auth module."""
import pytest
from backend.core.auth import hash_password, verify_password, validate_email, validate_password

def test_hash_and_verify():
    pw = "TestPass123"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)

def test_validate_email_valid():
    assert validate_email("test@example.com")
    assert validate_email("user.name+tag@domain.co.uk")

def test_validate_email_invalid():
    assert not validate_email("")
    assert not validate_email("notanemail")
    assert not validate_email("@domain.com")
    assert not validate_email("user@")

def test_validate_password_too_short():
    assert validate_password("Ab1") is not None

def test_validate_password_no_uppercase():
    assert validate_password("abcdefg1") is not None

def test_validate_password_no_digit():
    assert validate_password("Abcdefgh") is not None

def test_validate_password_valid():
    assert validate_password("TestPass1") is None
    assert validate_password("MyP@ssw0rd") is None
