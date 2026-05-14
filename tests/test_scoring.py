"""Tests for CV-JD matching scoring."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.routes.matching import score_skills, score_experience, score_education, compute_composite

def test_score_skills_perfect_match():
    result = score_skills(["python", "react", "aws"], ["python", "react", "aws"], [])
    assert result["score"] >= 80
    assert len(result["missing"]) == 0

def test_score_skills_partial():
    result = score_skills(["python"], ["python", "react", "aws"], [])
    assert result["score"] < 80
    assert "react" in result["missing"] or "aws" in result["missing"]

def test_score_skills_no_required():
    result = score_skills(["python"], [], [])
    assert result["score"] == 50

def test_score_experience_exceeds():
    result = score_experience(10, 5)
    assert result["score"] >= 80

def test_score_experience_below():
    result = score_experience(2, 5)
    assert result["score"] < 80

def test_score_experience_zero_required():
    result = score_experience(5, 0)
    assert result["score"] == 70

def test_score_education_match():
    result = score_education([{"degree": "Master of Science"}], "master")
    assert result["score"] >= 80

def test_score_education_no_requirement():
    result = score_education([], "")
    assert result["score"] == 70

def test_composite_weighted():
    scores = {"skills": 100, "experience": 100, "education": 100, "certifications": 100, "industry": 100}
    weights = {"skills": 40, "experience": 25, "education": 10, "certifications": 10, "industry": 15}
    assert compute_composite(scores, weights) == 100.0

def test_composite_partial():
    scores = {"skills": 50, "experience": 50, "education": 50, "certifications": 50, "industry": 50}
    weights = {"skills": 40, "experience": 25, "education": 10, "certifications": 10, "industry": 15}
    assert compute_composite(scores, weights) == 50.0
