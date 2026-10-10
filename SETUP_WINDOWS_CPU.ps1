$ErrorActionPreference = "Stop"

py -3.12 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-core.txt
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install paddleocr

Write-Host ""
Write-Host "Selesai."
Write-Host "Verifikasi Paddle:"
Write-Host "python -c ""import paddle; print(paddle.__version__)"""
Write-Host "Jalankan aplikasi:"
Write-Host "streamlit run app.py"
