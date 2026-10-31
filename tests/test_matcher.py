import pytest

from matcher import MatchError, SKILLS, extract_skills, match_resume

JOB = "We need a developer with React, Node.js, SQL and Docker experience."


def test_skills_dictionary_is_large_enough():
    assert len(SKILLS) >= 50


def test_extracts_skills_from_text():
    assert extract_skills(JOB) == ["React", "Node.js", "SQL", "Docker"]


def test_aliases_map_to_one_skill():
    assert extract_skills("I write JS and ReactJS daily") == ["JavaScript", "React"]
    # Results follow the order of the SKILLS dictionary (databases come before cloud).
    assert extract_skills("k8s, Postgres, sklearn") == ["PostgreSQL", "Kubernetes", "Scikit-learn"]


def test_special_character_skills():
    assert extract_skills("C++, C# and .NET developer") == ["C++", "C#", ".NET"]
    assert extract_skills("Experience with C/C++") == ["C++"]


def test_whole_word_matching_only():
    assert extract_skills("javascript only") == ["JavaScript"]  # "java" must not match inside it
    assert "SQL" not in extract_skills("MySQL experience")  # "sql" inside mysql is not SQL
    assert extract_skills("MySQL experience") == ["MySQL"]
    assert extract_skills("github projects") == ["GitHub"]  # "git" must not match inside github
    assert extract_skills("I like pythonic code, git-based flow") == ["Git"]


def test_longer_phrases_win_over_parts():
    assert extract_skills("React Native app") == ["React Native"]  # not also React
    assert extract_skills("Next.js and Node.js") == ["Next.js", "Node.js"]  # js not counted separately
    assert extract_skills("chart.js library") == []  # ".js" suffix is not JavaScript


def test_case_and_punctuation_insensitive():
    assert extract_skills("PYTHON, python; Python.") == ["Python"]
    assert extract_skills("(AWS/Azure)") == ["AWS", "Azure"]


def test_empty_and_none_input():
    assert extract_skills("") == []
    assert extract_skills(None) == []
    assert extract_skills("We value teamwork and cooking") == []


def test_match_result_is_computed_from_text():
    result = match_resume("I know React, SQL and Python.", JOB)
    assert result["matched_skills"] == ["React", "SQL"]
    assert result["missing_skills"] == ["Node.js", "Docker"]
    assert result["extra_skills"] == ["Python"]
    assert result["match_percent"] == 50


def test_different_resumes_give_different_results():
    strong = match_resume("React Node.js SQL Docker", JOB)
    weak = match_resume("Photoshop and Excel", JOB)
    medium = match_resume("React and SQL", JOB)
    assert strong["match_percent"] == 100 and strong["missing_skills"] == []
    assert weak["match_percent"] == 0 and weak["matched_skills"] == []
    assert medium["match_percent"] == 50
    assert len({strong["match_percent"], weak["match_percent"], medium["match_percent"]}) == 3


def test_different_job_descriptions_give_different_results():
    resume = "Python, Flask, SQL"
    a = match_resume(resume, "Looking for Python and Flask")
    b = match_resume(resume, "Looking for Java and Spring Boot")
    assert a["match_percent"] == 100
    assert b["match_percent"] == 0


def test_percentage_rounds_correctly():
    result = match_resume("Python", "Python, Java and Rust needed")
    assert result["match_percent"] == 33


def test_job_without_known_skills_raises_clear_error():
    with pytest.raises(MatchError) as info:
        match_resume("Python", "We are a friendly team that loves coffee.")
    assert "couldn't find any known skills" in str(info.value)


# ---- through the HTTP API ---------------------------------------------------
def test_api_match_with_pasted_text(alice):
    response = alice.post(
        "/api/match",
        json={"resume_text": "React and Docker engineer", "job_description": JOB},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["matched_skills"] == ["React", "Docker"]
    assert body["missing_skills"] == ["Node.js", "SQL"]
    assert body["match_percent"] == 50
    assert body["resume_source"] == "pasted text"


def test_api_match_requires_both_texts(alice):
    no_job = alice.post("/api/match", json={"resume_text": "Python", "job_description": "  "})
    assert no_job.status_code == 400
    assert "paste the job description" in no_job.get_json()["error"]

    no_resume = alice.post("/api/match", json={"resume_text": "", "job_description": JOB})
    assert no_resume.status_code == 400
    assert "upload your resume or paste" in no_resume.get_json()["error"]


def test_api_match_warns_when_resume_has_no_skills(alice):
    response = alice.post(
        "/api/match", json={"resume_text": "I enjoy painting.", "job_description": JOB}
    )
    assert response.status_code == 200
    assert response.get_json()["match_percent"] == 0
    assert "couldn't find any known skills in your resume" in response.get_json()["warning"]


def test_api_match_rejects_non_text_and_huge_input(alice):
    assert alice.post("/api/match", json={"resume_text": 5, "job_description": JOB}).status_code == 400
    huge = alice.post("/api/match", json={"resume_text": "Python", "job_description": "python " * 5000})
    assert huge.status_code == 400
    assert "too long" in huge.get_json()["error"]
