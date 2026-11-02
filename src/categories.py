"""Canonical categories shared by dataset preparation, training, and API inputs."""
import re

ACADEMIC_LEVELS = [
    "Early Childhood / Pre-primary",
    "Primary School",
    "Middle School / Lower Secondary",
    "High School / Upper Secondary",
    "Diploma / Vocational",
    "Undergraduate",
    "Postgraduate (Master's)",
    "Doctoral (PhD)",
    "Other",
]

EMPLOYMENT_STATUSES = ["None (student only)", "Part-time job", "Internship", "Full-time job"]


def normalize_academic_level(value) -> str:
    """Map the workbook's 63 localized labels into nine stable, usable categories."""
    s = " ".join(str(value or "").strip().lower().replace("’", "'").split())
    if not s or s in {"other", "unknown", "not specified", "__missing__"}:
        return "Other"
    if any(k in s for k in ("doctoral", "phd", "doctorate", "doctor of philosophy")):
        return "Doctoral (PhD)"
    if any(k in s for k in ("postgraduate", "post-graduate", "master", "mba", "graduate school")):
        return "Postgraduate (Master's)"
    if any(k in s for k in ("vocational", "diploma", "polytechnic", "ite", "bachelor of vocational")):
        return "Diploma / Vocational"
    if any(k in s for k in ("undergraduate", "bachelor", "university", "college", "collegiate", "tertiary")):
        return "Undergraduate"
    if any(k in s for k in ("kindergarten", "nursery", "preschool", "pre-school", "pre-primary", "preprimary", "maternelle", "infantil", "preescolar", "infant school")):
        return "Early Childhood / Pre-primary"
    if any(k in s for k in ("primary", "elementary", "primaria", "grundschule", "fundamental i", "basisschool", "scuola primaria", "educacion primaria", "école elementaire", "ecole elementaire")):
        return "Primary School"
    if any(k in s for k in ("middle", "junior", "lower secondary", "sek. i", "sek i", "fundamental ii", "grade 6-8", "grades 6-8", "eso", "collège", "college lower")):
        return "Middle School / Lower Secondary"
    if any(k in s for k in ("high school", "upper secondary", "senior secondary", "secondary", "gymnasium", "lycee", "lycée", "lise", "ensino medio", "bachillerato", "matric", "fsc", "hsc", "sixth form", "o/l", "a/l", "grade 9-12", "grades 9-12", "school")):
        return "High School / Upper Secondary"
    return "Other"


def normalize_employment_status(value) -> str:
    s = " ".join(str(value or "").strip().lower().split())
    aliases = {
        "none (student only)": "None (student only)", "none": "None (student only)",
        "student only": "None (student only)", "not employed": "None (student only)",
        "part-time job": "Part-time job", "part time": "Part-time job", "part-time": "Part-time job",
        "internship": "Internship", "intern": "Internship",
        "full-time job": "Full-time job", "full time": "Full-time job", "full-time": "Full-time job",
    }
    return aliases.get(s, "Other")
