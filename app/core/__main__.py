"""Entry point for running scanner as module: python -m app.core.scanner"""
from app.core.scanner import start_scanner_loop

if __name__ == "__main__":
    start_scanner_loop()
