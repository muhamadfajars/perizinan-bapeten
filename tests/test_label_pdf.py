from pathlib import Path
import pypdfium2 as pdfium
import tempfile
from PIL import Image, ImageDraw

from src.services.run_service import _convert_label_to_image
from src.ocr.preprocess import preprocess_image


def test_pdf_label_handling():
    # Create a temporary PDF file simulating a scanned label PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        pdf_path = Path(tmp_pdf.name)

    try:
        # Create a simple image and save it as PDF
        img = Image.new("RGB", (400, 200), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 50), "MODEL: CIRCLEX", fill="black")
        draw.text((20, 80), "SER. NO: TB-123456", fill="black")
        img.save(str(pdf_path), "PDF")

        # 1. Test _convert_label_to_image converts PDF to temporary PNG
        converted_path, is_temp = _convert_label_to_image(pdf_path)
        assert is_temp is True
        assert converted_path.exists()
        assert converted_path.suffix.lower() == ".png"
        converted_path.unlink()

        # 2. Test preprocess_image handles PDF without FileNotFoundError
        thresh = preprocess_image(str(pdf_path))
        assert thresh is not None
        assert thresh.shape[0] > 0
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
