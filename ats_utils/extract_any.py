import docx2txt
import PyPDF2
import os
import fitz
import docx

def extract_pdf(path):
    text = ""
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text

def extract_docx(path):
    return docx2txt.process(path)

def extract_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_pdf(path)
    elif ext in [".docx"]:
        return extract_docx(path)
    else:
        return "Unsupported file format"

def extract_text_from_file(file_path: str) -> str:
    """
    Universal text extractor for PDF and DOCX files.
    """
    if not os.path.exists(file_path):
        return ""
    ext = file_path.split(".")[-1].lower()
    if ext == "pdf":
        text = ""
        with fitz.open(file_path) as pdf:
            for page in pdf:
                page_text = page.get_text("text")
                if not page_text.strip():
                    blocks = page.get_text("blocks")
                    if isinstance(blocks, list):
                        page_text = " ".join([blk[4] for blk in blocks if len(blk) > 4])
                text += page_text + "\n"
        return text.strip()
    elif ext == "docx":
        doc = docx.Document(file_path)
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n".join(lines)
    else:
        return ""
