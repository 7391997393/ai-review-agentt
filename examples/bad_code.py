"""Example intentionally vulnerable code for testing the reviewer.

Do not use this code in a real application.
"""

import os
import sqlite3
import subprocess


def get_user(user_id):
    connection = sqlite3.connect("app.db")
    query = "SELECT * FROM users WHERE id = " + user_id
    return connection.execute(query).fetchall()


def run_command(filename):
    return subprocess.check_output("cat " + filename, shell=True)


def save_password(password):
    with open("password.txt", "w") as file:
        file.write(password)


def calculate_total(items):
    total = 0
    for item in items:
        total += item["price"]
    return total
