"""Demo module used only for the live end-to-end test of the review agent."""

import os
import sqlite3

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def find_user(conn: sqlite3.Connection, name: str):
    query = "SELECT * FROM users WHERE name = ?"
    return conn.execute(query, (name,)).fetchall()


def average(values):
    if not values:
        return 0.0
    return sum(values) / len(values)
