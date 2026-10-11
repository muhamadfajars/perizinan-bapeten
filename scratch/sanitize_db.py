import sqlite3
import json
from src.schema.fields import DOCUMENT_FIELDS
from src.extraction.document_parser import _finalize_document_fields

conn = sqlite3.connect('data/output/bapeten_matching.sqlite3')
cursor = conn.cursor()
cursor.execute('SELECT run_id, result_json FROM runs')
rows = cursor.fetchall()

updated_count = 0
for run_id, result_json in rows:
    try:
        payload = json.loads(result_json)
        ext = payload.get('extractions', {})
        modified = False
        for dt, docs in ext.items():
            if dt in DOCUMENT_FIELDS:
                for doc in docs:
                    fields = doc.get('fields', {})
                    # Remove document_number and document_date
                    fields.pop('document_number', None)
                    fields.pop('document_date', None)
                    # If sistem_manajemen, remove table_of_contents and person_name
                    if dt == 'sistem_manajemen':
                        fields.pop('table_of_contents', None)
                        fields.pop('person_name', None)
                    # If program_perawatan, remove person_name
                    if dt == 'program_perawatan':
                        fields.pop('person_name', None)
                    # Finalize fields
                    doc['fields'] = _finalize_document_fields(dt, fields)
                    modified = True
        if modified:
            new_result_json = json.dumps(payload, ensure_ascii=False)
            cursor.execute('UPDATE runs SET result_json = ? WHERE run_id = ?', (new_result_json, run_id))
            updated_count += 1
    except Exception as e:
        print(f"Error on {run_id}: {e}")

conn.commit()
conn.close()
print(f"Successfully sanitized {updated_count} runs in database.")
