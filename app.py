import logging

from servio import create_app

logging.basicConfig(level=logging.INFO)

app = create_app()

if __name__ == "__main__":
    # In production, use a WSGI server (e.g., gunicorn app:app).
    app.run(host="0.0.0.0", port=5000, debug=True)
