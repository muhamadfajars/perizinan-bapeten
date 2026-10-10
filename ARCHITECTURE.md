# System architecture

```text
                 +-------------------+
                 | Streamlit Web UI  |
                 +---------+---------+
                           |
                           v
                  +-----------------+
                  | execute_run()   |
                  +--------+--------+
                           |
        +------------------+------------------+
        |                  |                  |
        v                  v                  v
  Formulir PDF         PPKR PDF          Label images
    pdfplumber          pdfplumber       OpenCV + OCR
        |                  |                  |
        v                  v                  v
 Form structured      PPKR structured     Label structured
        |                  |                  |
        +------------------+------------------+
                           |
                           v
                      Normalizer
                           |
                           v
                    Matching engine
                     /                               v             v
             Label matching   Document/personnel
                    \             /
                     v           v
                       Validation
                           |
                           v
                     Result JSON
                           |
                           v
                      SQLite history
```

Notebook tetap disimpan di `notebooks/` hanya sebagai referensi/regression source.
Aplikasi utama berada di `src/`.
