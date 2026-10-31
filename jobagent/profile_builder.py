"""Merge every resume version in resumes/ into one master profile (config/profile.yaml).

This runs once (and again whenever you add a resume), so it uses Sonnet: the
profile is the source of truth for every tailored resume, so accuracy matters.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from . import llm
from .config import CONFIG_DIR, ROOT

RESUME_SRC = ROOT / "resumes"
SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


class Contact(BaseModel):
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""


class Education(BaseModel):
    school: str
    degree: str
    start: str = ""
    end: str = ""
    gpa: str = ""
    coursework: list[str] = Field(default_factory=list)


class ProfileBullet(BaseModel):
    id: str = Field(description="Unique, e.g. 'acme-1'")
    text: str
    tags: list[str] = Field(description="Lowercase skills/topics, e.g. python, llm, etl")


class Experience(BaseModel):
    id: str = Field(description="Short unique slug, e.g. 'acme'")
    company: str
    title: str
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[ProfileBullet]
    found_in: list[str] = Field(description="Resume file names this entry appears in")


class Project(BaseModel):
    id: str
    name: str
    link: str = ""
    start: str = ""
    end: str = ""
    bullets: list[ProfileBullet]
    found_in: list[str]


class Skills(BaseModel):
    languages: list[str]
    frameworks: list[str] = Field(description="Frameworks and libraries")
    tools: list[str] = Field(description="Tools, platforms, databases, cloud")
    other: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    name: str
    contact: Contact
    education: list[Education]
    experience: list[Experience]
    projects: list[Project]
    skills: Skills
    certifications: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(
        description="Facts that differ between versions (dates, titles, numbers) and which one you kept"
    )


SYSTEM = """You merge several versions of one person's resume into a single master profile.

- Use only facts written in the resumes. Never add a skill, number, tool, date or result.
- The same job or project often appears in several versions with different wording. Merge it into one entry.
- Keep every distinct bullet across versions. If two bullets state the same fact, keep the more specific one.
  If they state different facts, keep both.
- Keep every project from every version, even ones missing from the latest resume.
- When versions disagree (dates, titles, numbers), use the latest version and record the conflict.
- Contact details come from the latest version.
- Order experience and projects newest first. Bullet text should read as a resume bullet."""


def read_resume(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    return path.read_text(encoding="utf-8")


def run(latest: str | None = None) -> dict:
    files = sorted((p for p in RESUME_SRC.iterdir() if p.suffix.lower() in SUPPORTED), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No resumes found. Put PDF, DOCX, TXT or MD files in {RESUME_SRC}/")
    latest_file = next((p for p in files if p.name == latest), None) if latest else files[-1]
    if latest_file is None:
        raise SystemExit(f"--latest {latest} is not in {RESUME_SRC}/")

    parts, empty = [], []
    for p in files:
        text = read_resume(p).strip()
        if len(text) < 200:
            empty.append(p.name)  # likely a scanned/image PDF with no text layer
            continue
        tag = "LATEST VERSION" if p == latest_file else "older version"
        parts.append(f'<resume file="{p.name}" note="{tag}">\n{text}\n</resume>')
    if not parts:
        raise SystemExit(f"Could not read text from: {', '.join(empty)}. Export them as DOCX or TXT.")

    profile = llm.structured("build_profile", SYSTEM, "\n\n".join(parts), Profile, max_tokens=48000)

    data = profile.model_dump(exclude={"conflicts"})
    target = CONFIG_DIR / "profile.yaml"
    if target.exists():
        target = CONFIG_DIR / "profile.generated.yaml"  # never overwrite edits you've made
    header = "# Generated from: " + ", ".join(p.name for p in files) + "\n# Review every line before use.\n"
    target.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return {
        "path": str(target),
        "files": [p.name for p in files if p.name not in empty],
        "unreadable": empty,
        "latest": latest_file.name,
        "experience": len(profile.experience),
        "projects": len(profile.projects),
        "bullets": sum(len(e.bullets) for e in profile.experience + profile.projects),
        "conflicts": profile.conflicts,
    }
