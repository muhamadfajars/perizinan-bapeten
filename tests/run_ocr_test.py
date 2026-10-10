from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import LABEL_DIR, OCR_DIR
from src.ocr.preprocess import preprocess_image
from src.ocr.engine import run_ocr, ocr_to_dataframe


def main():
    images = sorted(
        p for p in LABEL_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    )

    if not images:
        print(f"Masukkan minimal satu foto label ke: {LABEL_DIR.resolve()}")
        return

    for image_path in images:
        print(f"\n=== {image_path.name} ===")

        preprocessed_path = OCR_DIR / f"{image_path.stem}_preprocessed.png"
        preprocess_image(image_path, preprocessed_path)

        lines = run_ocr(str(image_path))
        df = ocr_to_dataframe(lines)

        print(f"Detected lines: {len(df)}")
        if not df.empty:
            print(df[["text", "conf", "x", "y", "needs_review"]].to_string(index=False))
        else:
            print("Tidak ada teks yang terdeteksi.")

        print(f"Preprocessed image: {preprocessed_path.resolve()}")


if __name__ == "__main__":
    main()
