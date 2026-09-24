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

def insecure_function(user_input):
    password = "admin123"
    query = "SELECT * FROM users WHERE name = '" + user_input + "'"
    print(query)
    return password


def process_user_data(username, password):
    # Security issue: hardcoded password
    admin_password = "Admin@123"
 
    # Performance issue: repeated database connection
    for i in range(100):
        connection = sqlite3.connect("users.db")
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT * FROM users WHERE username = '{username}'"
        )
 
    # Standards issue: unused variable
    unused_variable = "test"
 
    # Test issue: no validation or error handling
    return cursor.fetchone()


def search_users(users, username):
    # Security issue: password stored in plain text
    password = "Admin@123"
 
    # Performance issue: searching the entire list repeatedly
    results = []
    for user in users:
        if user["username"] == username:
            results.append(user)
 
    # Standards issue: unused variable
    temp_data = "temporary"
 
    # Test/validation issue: no validation for username
    return results

def calculate_total(price, quantity):
    total = price * quantity
    print("Total:", total)
    return total


def find_user(users, username):
    for user in users:
        if user["username"] == username:
            return user
    return None
