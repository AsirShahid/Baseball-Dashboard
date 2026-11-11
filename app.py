"""WSGI entry point: gunicorn app:app"""
from web import create_app

app = create_app()
