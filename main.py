import os
import psycopg2
from os import environ
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = environ.get("APP_SECRET")

DB_HOST = environ.get('DB_HOST')
DB_NAME = environ.get('DB_NAME')
DB_USER = environ.get('DB_USER')
DB_PASS = environ.get('DB_PASS')

path = environ.get('PathToDirectory') or os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(path, exist_ok=True)
app.config['path'] = path

MAX_BYTES = 15 * 1024 * 1024 * 1024  # 10 ГБ


def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


def sizeof_fmt(num, suffix='B'):
    if num is None:
        return "0 B"
    for unit in ['', 'K', 'M', 'G', 'T', 'P']:
        if abs(num) < 1024.0:
            return f"{num:.2f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.2f}P{suffix}"


def get_user_files_size(id_user):
    total_size = 0
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "filename" FROM "files" WHERE "ID_user"=%s', (id_user,))
            rows = cursor.fetchall()
            for row in rows:
                filename = row[0]
                filepath = os.path.join(app.config['path'], filename)
                if os.path.exists(filepath):
                    try:
                        total_size += os.path.getsize(filepath)
                    except OSError:
                        # если по какой-то причине файл недоступен — пропускаем
                        pass
    return total_size


@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            row = cursor.fetchone()
            if not row:
                return redirect(url_for("login"))
            id_user = row[0]

            cursor.execute('SELECT "ID", "filename" FROM "files" WHERE "ID_user"=%s', (id_user,))
            files = cursor.fetchall()

    total_bytes = get_user_files_size(id_user)
    total_size = sizeof_fmt(total_bytes)
    max_bytes = MAX_BYTES
    max_size = sizeof_fmt(max_bytes)

    return render_template("index.html",
                           files=files,
                           total_bytes=total_bytes,
                           total_size=total_size,
                           max_bytes=max_bytes,
                           max_size=max_size)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1 FROM "users" WHERE "name"=%s', (username,))
                if cursor.fetchone():
                    return render_template('register.html', message="Пользователь уже существует")

                hashed_password = generate_password_hash(password)
                cursor.execute(
                    'INSERT INTO "users" ("name", "password") VALUES (%s, %s)',
                    (username, hashed_password)
                )
                conn.commit()
                flash("Вы успешно зарегистрировались!", "success")
                return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT "password" FROM "users" WHERE "name"=%s', (username,))
                row = cursor.fetchone()
                if row and check_password_hash(row[0], password):
                    session['username'] = username
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', message="Неверный логин или пароль")

    return render_template('login.html')


@app.route("/upload", methods=["POST"])
def upload_file():
    if "username" not in session:
        return redirect(url_for("login"))

    if "files" not in request.files:
        return jsonify({"error": "Нет файлов"}), 400

    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        return jsonify({"error": "Нет файлов"}), 400

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Пользователь не найден"}), 400
            id_user = row[0]

    total_size = get_user_files_size(id_user)

    saved_files = []
    total_new_size = 0
    file_sizes = []
    for f in uploaded_files:
        try:
            f.stream.seek(0, os.SEEK_END)
            size = f.stream.tell()
            f.stream.seek(0)
        except Exception:
            size = getattr(f, 'content_length', 0) or 0
        file_sizes.append(size)
        total_new_size += size

    if total_size + total_new_size > MAX_BYTES:
        return jsonify({
            "error": "Превышен лимит хранения. Загрузка отклонена.",
            "used_bytes": total_size,
            "max_bytes": MAX_BYTES
        }), 413

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            for idx, f in enumerate(uploaded_files):
                if f.filename == "":
                    continue
                filename = secure_filename(f.filename)

                # если файл с таким именем уже существует на диске, добавим суффикс чтобы не перезаписать
                dest = os.path.join(app.config['path'], filename)
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest):
                    filename = f"{base}_{counter}{ext}"
                    dest = os.path.join(app.config['path'], filename)
                    counter += 1

                f.save(dest)

                cursor.execute(
                    'INSERT INTO "files" ("ID_user", "filename") VALUES (%s, %s)',
                    (id_user, filename)
                )
                saved_files.append(filename)

            conn.commit()

    new_total = get_user_files_size(id_user)
    return jsonify({
        "saved": saved_files,
        "used_bytes": new_total,
        "used_readable": sizeof_fmt(new_total),
        "max_bytes": MAX_BYTES,
        "max_readable": sizeof_fmt(MAX_BYTES)
    })


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config['path'], filename)


@app.route("/getting", methods=["GET"])
def getting_files():
    if "username" not in session:
        return redirect(url_for("login"))

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            row = cursor.fetchone()
            if not row:
                return redirect(url_for("login"))
            id_user = row[0]

            cursor.execute('SELECT "ID", "filename" FROM "files" WHERE "ID_user"=%s', (id_user,))
            files = cursor.fetchall()

    return render_template("files.html", files=files)


@app.route("/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    if "username" not in session:
        return "Unauthorized", 401

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            row = cursor.fetchone()
            if not row:
                return "Unauthorized", 401
            id_user = row[0]

            cursor.execute('DELETE FROM "files" WHERE "ID_user"=%s AND "filename"=%s',
                           (id_user, filename))
            conn.commit()

    filepath = os.path.join(app.config['path'], filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass

    return "Deleted", 200


@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    if "username" not in session:
        return "Unauthorized", 401

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            row = cursor.fetchone()
            if not row:
                return "Unauthorized", 401
            id_user = row[0]

            cursor.execute('SELECT 1 FROM "files" WHERE "ID_user"=%s AND "filename"=%s',
                           (id_user, filename))
            if not cursor.fetchone():
                return "File not found", 404

    filepath = os.path.join(app.config['path'], filename)
    if not os.path.exists(filepath):
        return "File not found on disk", 404

    return send_from_directory(app.config['path'], filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
