"""Resume <-> job description skill matcher.

How it works (easy to explain in a viva):
1. SKILLS maps each skill's display name to the aliases people write for it.
2. extract_skills() scans the REAL text for those aliases (whole words only).
3. match_resume() compares the two skill sets and computes the match percentage.

Nothing is hardcoded about the result: different text in -> different skills out.
"""
import re

# Display name -> aliases (all lowercase). Longer aliases are matched first, so
# "react native" is found before "react" and "next.js" before "js".
SKILLS = {
    # Languages
    "Python": ["python", "python3"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js", "ecmascript", "es6"],
    "TypeScript": ["typescript"],
    "C": ["c programming", "c language"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "csharp", "c sharp"],
    "Go": ["golang", "go lang"],
    "Rust": ["rust"],
    "PHP": ["php"],
    "Ruby": ["ruby"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "Dart": ["dart"],
    "R": ["r programming", "rstudio"],
    "MATLAB": ["matlab"],
    "Bash": ["bash", "shell scripting", "shell script"],
    # Web frontend
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    "React": ["react", "reactjs", "react.js"],
    "Angular": ["angular", "angularjs"],
    "Vue.js": ["vue", "vuejs", "vue.js"],
    "Next.js": ["next.js", "nextjs"],
    "Redux": ["redux"],
    "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
    "Bootstrap": ["bootstrap"],
    "jQuery": ["jquery"],
    # Backend
    "Node.js": ["node.js", "nodejs", "node"],
    "Express.js": ["express.js", "expressjs", "express"],
    "Flask": ["flask"],
    "Django": ["django"],
    "FastAPI": ["fastapi"],
    "Spring Boot": ["spring boot", "springboot", "spring"],
    ".NET": [".net", "dotnet", "asp.net"],
    "REST APIs": ["rest", "restful", "rest api", "rest apis", "restful api", "restful apis"],
    "GraphQL": ["graphql"],
    "Microservices": ["microservices", "microservice"],
    # Databases
    "SQL": ["sql"],
    "MySQL": ["mysql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "SQLite": ["sqlite"],
    "MongoDB": ["mongodb", "mongo"],
    "NoSQL": ["nosql"],
    "Redis": ["redis"],
    "Firebase": ["firebase"],
    "Elasticsearch": ["elasticsearch"],
    # Cloud / DevOps
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"],
    "Google Cloud": ["gcp", "google cloud"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Git": ["git"],
    "GitHub": ["github"],
    "CI/CD": ["ci/cd", "cicd", "ci cd", "continuous integration"],
    "Linux": ["linux", "unix"],
    "Jenkins": ["jenkins"],
    "Terraform": ["terraform"],
    "Nginx": ["nginx"],
    # Data / AI
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision"],
    "Generative AI": ["generative ai", "genai", "gen ai"],
    "LLMs": ["llm", "llms", "large language model", "large language models"],
    "RAG": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "LangChain": ["langchain"],
    "Prompt Engineering": ["prompt engineering"],
    "Hugging Face": ["hugging face", "huggingface"],
    "TensorFlow": ["tensorflow"],
    "PyTorch": ["pytorch"],
    "Scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "OpenCV": ["opencv"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Data Analysis": ["data analysis", "data analytics"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau"],
    "Excel": ["excel", "ms excel"],
    # Mobile
    "Android": ["android"],
    "Flutter": ["flutter"],
    "React Native": ["react native"],
    # CS fundamentals and practices
    "Data Structures": ["data structures", "data structure", "dsa"],
    "Algorithms": ["algorithms", "algorithm"],
    "OOP": ["oop", "oops", "object oriented", "object-oriented"],
    "Operating Systems": ["operating systems", "operating system"],
    "Computer Networks": ["computer networks", "computer networking"],
    "System Design": ["system design"],
    "Agile": ["agile", "scrum"],
    "Unit Testing": ["unit testing", "unit tests", "pytest", "junit", "jest"],
    "Cybersecurity": ["cybersecurity", "cyber security", "information security"],
    "Figma": ["figma"],
}

_WORD_CHARS = "a-z0-9+#"


def _build_pattern(alias):
    """Whole-word regex for an alias. Handles c++, c#, .net, node.js and similar."""
    # Skills starting with "." (like .net) may follow a space; others must not
    # follow a letter, digit, "+", "#" or "." (so "chart.js" is not "js").
    before = rf"(?<![{_WORD_CHARS}])" if alias.startswith(".") else rf"(?<![{_WORD_CHARS}.])"
    after = rf"(?![{_WORD_CHARS}])"
    return re.compile(before + re.escape(alias) + after)


# (alias, skill, compiled regex), longest alias first.
_PATTERNS = sorted(
    ((alias, skill, _build_pattern(alias)) for skill, aliases in SKILLS.items() for alias in aliases),
    key=lambda item: len(item[0]),
    reverse=True,
)


class MatchError(Exception):
    """Raised when the matcher cannot produce a meaningful result."""


def extract_skills(text):
    """Return the skills found in `text`, in the order they appear in SKILLS."""
    working = (text or "").lower()
    found = set()
    for _alias, skill, pattern in _PATTERNS:
        if pattern.search(working):
            found.add(skill)
            # Blank out the match so shorter aliases can't re-match inside it.
            working = pattern.sub(lambda m: " " * len(m.group()), working)
    return [skill for skill in SKILLS if skill in found]


def match_resume(resume_text, job_text):
    """Compare resume skills with job-description skills."""
    job_skills = extract_skills(job_text)
    if not job_skills:
        raise MatchError(
            "We couldn't find any known skills in that job description. "
            "Please paste the full text of the job posting."
        )
    resume_skills = extract_skills(resume_text)

    matched = [s for s in job_skills if s in resume_skills]
    missing = [s for s in job_skills if s not in resume_skills]
    extra = [s for s in resume_skills if s not in job_skills]
    percent = round(100 * len(matched) / len(job_skills))

    return {
        "match_percent": percent,
        "matched_skills": matched,
        "missing_skills": missing,
        "extra_skills": extra,
        "job_skill_count": len(job_skills),
        "resume_skill_count": len(resume_skills),
    }
