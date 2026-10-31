"""Render a tailored resume in the same LaTeX layout as resumes/ScaleAI.pdf, then compile it."""

import re
import subprocess
from pathlib import Path

from pypdf import PdfReader

# Uses only packages that ship with BasicTeX (no titlesec/enumitem/fullpage).
PREAMBLE = r"""\documentclass[letterpaper,10pt]{article}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[letterpaper,left=0.5in,right=0.5in,top=0.4in,bottom=0.4in]{geometry}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\parindent}{0pt}
\setlength{\tabcolsep}{0in}
\renewcommand{\section}[1]{\vspace{5pt}{\large\bfseries #1}\par\vspace{-5pt}\rule{\textwidth}{0.4pt}\par\vspace{-2pt}}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\newcommand{\resumeSubheading}[4]{\item
  \begin{tabular*}{\linewidth}[t]{l@{\extracolsep{\fill}}r}
    \textbf{\small #1} & \small #2 \\
    \textit{\small #3} & \textit{\small #4} \\
  \end{tabular*}}
\newcommand{\resumeProjectHeading}[1]{\item\textbf{\small #1}}
\newenvironment{headlist}{\begin{list}{}{\setlength{\leftmargin}{0.15in}\setlength{\labelwidth}{0pt}%
  \setlength{\itemsep}{0pt}\setlength{\parsep}{0pt}\setlength{\topsep}{0pt}\setlength{\partopsep}{0pt}}}{\end{list}}
\newenvironment{bulletlist}{\begin{list}{--}{\setlength{\leftmargin}{0.17in}\setlength{\labelwidth}{0.1in}%
  \setlength{\labelsep}{0.07in}\setlength{\itemsep}{0pt}\setlength{\parsep}{0pt}\setlength{\topsep}{0pt}%
  \setlength{\partopsep}{0pt}}}{\end{list}}
\newcommand{\resumeSubHeadingListStart}{\begin{headlist}}
\newcommand{\resumeSubHeadingListEnd}{\end{headlist}}
\newcommand{\resumeItemListStart}{\begin{bulletlist}}
\newcommand{\resumeItemListEnd}{\end{bulletlist}}
\begin{document}
"""

_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def tex(text: str) -> str:
    """Escape LaTeX specials, then turn **bold** into \\textbf{}."""
    out = "".join(_ESCAPES.get(ch, ch) for ch in str(text))
    return re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", out)


def build(resume, profile: dict) -> str:
    c = profile.get("contact", {})
    contact = " $|$ ".join(tex(v) for v in (c.get("phone"), c.get("email"), c.get("location"),
                                             c.get("linkedin"), c.get("github"), c.get("website")) if v)
    out = [PREAMBLE,
           r"\begin{center}",
           rf"{{\Huge \scshape {tex(profile['name'])}}} \\ \vspace{{1pt}}",
           rf"\small {contact}",
           r"\end{center}\vspace{-8pt}",
           r"\section{Summary}",
           rf"{{\small {tex(resume.summary)}\par}}",
           r"\section{Education}", r"\resumeSubHeadingListStart"]

    for e in profile.get("education", []):
        out.append(rf"\resumeSubheading{{{tex(e['degree'])}}}{{{tex(e.get('end', ''))}}}"
                   rf"{{{tex(e['school'])}}}{{{tex(e.get('location', ''))}}}")
        if e.get("coursework") and e is profile["education"][0]:
            out.append(r"\resumeItemListStart\resumeItem{Coursework: "
                       + tex(", ".join(e["coursework"][:6])) + r"}\resumeItemListEnd")
    out.append(r"\resumeSubHeadingListEnd")

    by_id = {x["id"]: x for x in profile.get("experience", [])}
    if resume.experience:
        out += [r"\section{Experience}", r"\resumeSubHeadingListStart"]
        for s in resume.experience:
            item = by_id[s.id]
            dates = " -- ".join(tex(d) for d in (item.get("start"), item.get("end")) if d)
            out.append(rf"\resumeSubheading{{{tex(item['title'])}}}{{{dates}}}"
                       rf"{{{tex(item['company'])}}}{{{tex(item.get('location', ''))}}}")
            out.append(r"\resumeItemListStart")
            out += [rf"\resumeItem{{{tex(b.text)}}}" for b in s.bullets]
            out.append(r"\resumeItemListEnd")
        out.append(r"\resumeSubHeadingListEnd")

    by_id = {x["id"]: x for x in profile.get("projects", [])}
    if resume.projects:
        out += [r"\section{Project Experience}", r"\resumeSubHeadingListStart"]
        for s in resume.projects:
            out.append(rf"\resumeProjectHeading{{{tex(by_id[s.id]['name'])}}}")
            out.append(r"\resumeItemListStart")
            out += [rf"\resumeItem{{{tex(b.text)}}}" for b in s.bullets]
            out.append(r"\resumeItemListEnd")
        out.append(r"\resumeSubHeadingListEnd")

    out += [r"\section{Technical Skills}", r"\begin{headlist}\small\item"]
    rows = [rf"\textbf{{{tex(g.category)}:}} {tex(', '.join(g.items))}" for g in resume.skills if g.items]
    out.append(r" \\ ".join(rows))
    # Report how much of the page is used, for fill_page(): typeset height so far vs. page height.
    out += [r"\end{headlist}", r"\par\typeout{JOBAGENT-FILL \the\pagetotal\space\the\pagegoal}", r"\end{document}"]
    return "\n".join(out)


def page_fill(pdf: Path) -> float:
    """Share of the page's text height in use (0-1), as LaTeX measured it while compiling."""
    measured = pdf.with_suffix(".fill")
    if measured.exists():
        return float(measured.read_text())
    page = PdfReader(pdf).pages[0]  # rough fallback for PDFs we didn't build
    height = float(page.mediabox.height)
    top, bottom = height - 0.4 * 72, 0.4 * 72  # the 0.4in margins set in PREAMBLE
    ys = []
    page.extract_text(visitor_text=lambda text, cm, tm, *_: ys.append(tm[5] * cm[3] + cm[5]) if text.strip() else None)
    lowest = min((y for y in ys if bottom - 5 <= y <= top + 5), default=top)
    return (top - lowest) / (top - bottom)


def compile_pdf(source: str, tex_path: Path) -> tuple[Path, int]:
    """Compile with pdflatex; return the PDF path and its page count."""
    tex_path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        cwd=tex_path.parent, capture_output=True, text=True,
    )
    pdf = tex_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf.exists():
        errors = [l for l in result.stdout.splitlines() if l.startswith("!")]
        raise RuntimeError(f"pdflatex failed on {tex_path.name}: {errors[:3]}")
    pages = len(PdfReader(pdf).pages)
    m = re.search(r"JOBAGENT-FILL ([\d.]+)pt ([\d.]+)pt", result.stdout)
    if m and pages == 1:
        tex_path.with_suffix(".fill").write_text(f"{float(m.group(1)) / float(m.group(2)):.4f}")
    for ext in (".aux", ".log", ".out"):
        tex_path.with_suffix(ext).unlink(missing_ok=True)
    return pdf, pages
