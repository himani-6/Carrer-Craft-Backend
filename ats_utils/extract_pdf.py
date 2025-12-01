from pdfminer.high_level import extract_text

def extract_text_from_pdf(file_path: str) -> str:
    try:
        text = extract_text(file_path)
        return text.strip()
    except Exception as e:
        return f"[ERROR extracting PDF] {str(e)}"
