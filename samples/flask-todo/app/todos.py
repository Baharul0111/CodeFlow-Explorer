"""The todo list itself."""
from app.db import insert_todo, select_todos, update_todo_done

MAX_LENGTH = 200


class TodoError(Exception):
    pass


def add(user_id, text):
    """Add one todo after checking it is not empty or silly long."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise TodoError("Please write something to do.")
    if len(cleaned) > MAX_LENGTH:
        raise TodoError("That is too long for one todo.")
    return insert_todo(user_id, cleaned)


def listing(user_id, only_open=False):
    """Fetch this person's todos, newest last, optionally hiding finished ones."""
    rows = select_todos(user_id)
    if only_open:
        rows = [row for row in rows if not row["done"]]
    return sorted(rows, key=lambda row: row["id"])


def complete(user_id, todo_id):
    update_todo_done(todo_id, user_id, True)
    return {"id": todo_id, "done": True}
