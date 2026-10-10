from pathlib import Path
import cv2
import numpy as np
import pypdfium2 as pdfium

def preprocess_image(image_path, save_path=None, scale=1.5):
    image_path = str(image_path)
    if image_path.lower().endswith(".pdf"):
        doc = pdfium.PdfDocument(image_path)
        try:
            pil_img = doc[0].render(scale=scale).to_pil()
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        finally:
            doc.close()
    else:
        img = cv2.imread(image_path)

    if img is None:
        raise FileNotFoundError(f"Image could not be read: {image_path}")

    h, w = img.shape[:2]
    eff_scale = scale if max(h, w) < 1500 else 1.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if eff_scale != 1.0:
        gray = cv2.resize(gray, None, fx=eff_scale, fy=eff_scale, interpolation=cv2.INTER_CUBIC)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15
    )

    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(save_path), thresh):
            raise IOError(f"Failed to save preprocessed image: {save_path}")
        return str(save_path)

    return thresh
