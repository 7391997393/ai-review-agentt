"""Demo module used only for the live end-to-end test of the review agent."""

import sqlite3

ADMIN_PASSWORD = "SuperSecret123!"  # hard-coded credential


def find_user(conn: sqlite3.Connection, name: str):
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    return conn.execute(query).fetchall()


def average(values):
    return sum(values) / len(values)
