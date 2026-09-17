"""Web routes: the only part of the app the outside world touches."""
from flask import Flask, jsonify, request

from app.auth import AuthError, login, register, user_id_for_token
from app.db import init_db
from app.todos import TodoError, add, complete, listing

app = Flask(__name__)


def current_user():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return user_id_for_token(token)


@app.route("/signup", methods=["POST"])
def signup_route():
    body = request.get_json(silent=True) or {}
    try:
        token = register(body.get("email"), body.get("password"))
    except AuthError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"token": token}), 201


@app.route("/login", methods=["POST"])
def login_route():
    body = request.get_json(silent=True) or {}
    try:
        token = login(body.get("email"), body.get("password"))
    except AuthError as error:
        return jsonify({"error": str(error)}), 401
    return jsonify({"token": token})


@app.route("/todos", methods=["GET"])
def list_route():
    user_id = current_user()
    if user_id is None:
        return jsonify({"error": "Please log in."}), 401
    only_open = request.args.get("open") == "1"
    return jsonify(listing(user_id, only_open))


@app.route("/todos", methods=["POST"])
def add_route():
    user_id = current_user()
    if user_id is None:
        return jsonify({"error": "Please log in."}), 401
    body = request.get_json(silent=True) or {}
    try:
        todo = add(user_id, body.get("text"))
    except TodoError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(todo), 201


@app.route("/todos/<int:todo_id>/done", methods=["POST"])
def complete_route(todo_id):
    user_id = current_user()
    if user_id is None:
        return jsonify({"error": "Please log in."}), 401
    return jsonify(complete(user_id, todo_id))


def main():
    init_db()
    app.run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
