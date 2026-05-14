"""Tests for CV parser utilities."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.cv_parser import classify_file, score_extraction_quality, detect_language

def test_classify_pdf():
    assert classify_file("resume.pdf") == "pdf"
    assert classify_file("RESUME.PDF") == "pdf"

def test_classify_docx():
    assert classify_file("resume.docx") == "docx"
    assert classify_file("resume.doc") == "docx"

def test_classify_image():
    assert classify_file("scan.png") == "image"
    assert classify_file("photo.jpg") == "image"

def test_classify_unknown():
    assert classify_file("file.exe") == "unknown"
    assert classify_file("data.csv") == "unknown"

def test_quality_good():
    text = "John Doe\nSenior Software Engineer\nExperience: 10 years\nSkills: Python, React\nEducation: BS Computer Science\njohn@email.com\n+1234567890"
    result = score_extraction_quality(text)
    assert result["score"] >= 50
    assert result["has_email"]

def test_quality_empty():
    result = score_extraction_quality("")
    assert result["score"] == 0

def test_quality_garbled():
    result = score_extraction_quality("@#$%^&*()!@#$%^&*()")
    assert result["score"] < 50

def test_detect_language_english():
    assert detect_language("Hello world this is English text") == "en"

def test_detect_language_hindi():
    assert detect_language("नमस्ते दुनिया") == "hi"

def test_detect_language_arabic():
    assert detect_language("مرحبا بالعالم") == "ar"
