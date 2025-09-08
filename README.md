# Meal Picker (MVP)

A tiny Flask app where users click meals they want to eat; the app compiles a tally shown on a results page.

## Quickstart (Windows CMD)

```cmd
:: 1) (Optional) Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

:: 2) Install dependencies
pip install -r requirements.txt

:: 3) Run the app (either way works)
python app.py
:: or:
:: set FLASK_APP=app.py
:: flask run

:: 4) Open in your browser:
:: http://127.0.0.1:5000/
```

## Project Structure
```
meal-picker/
├─ app.py
├─ models.py
├─ requirements.txt
├─ README.md
├─ templates/
│  ├─ base.html
│  ├─ index.html
│  ├─ add.html
│  └─ results.html
└─ static/
   └─ style.css
```

## Notes
- Uses SQLite (`app.db`) locally; tables auto-create on first run.
- Default meals are seeded the first time if the DB is empty.
- Click any meal to add to the tally. See **Results** to view counts.
- You can add new meals via the **Add Meal** page.
