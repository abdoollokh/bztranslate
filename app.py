from flask import Flask, request, render_template_string, redirect, url_for
import asyncpg
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")

# --- HTML Templates ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Admin Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="fw-bold">📋 Xizmatlar roʻyxati</h2>
        <div>
            <a href="/admin/orders" class="btn btn-outline-secondary">📦 Buyurtmalar</a>
            <a href="/admin/add" class="btn btn-success">+ Yangi xizmat</a>
        </div>
    </div>
    {% for service in services %}
    <div class="card mb-3">
        <div class="card-body d-flex justify-content-between align-items-center">
            <div>
                <h5 class="card-title mb-1">{{ service.title_uz }}</h5>
                <p class="mb-0 text-muted">{{ service.title_ru }}</p>
            </div>
            <div class="text-end">
                <div class="fw-bold">${{ '%.2f'|format(service.price_usd) }}</div>
                <a href="/admin/edit/{{ service.id }}" class="btn btn-sm btn-primary mt-2">✏️ Tahrirlash</a>
                <a href="/admin/delete/{{ service.id }}" class="btn btn-sm btn-danger mt-2" onclick="return confirm('Ishonchingiz komilmi?')">🗑 Oʻchirish</a>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
</body>
</html>
"""

FORM_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ 'Yangi xizmat' if is_new else 'Xizmatni tahrirlash' }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-5">
    <h2 class="mb-4">{{ '🆕 Yangi xizmat' if is_new else '✏️ Xizmatni tahrirlash' }}</h2>
    <form method="post">
        <div class="mb-3">
            <label class="form-label">Xizmat nomi (Oʻzbekcha)</label>
            <input type="text" name="title_uz" class="form-control" required value="{{ service.title_uz }}">
        </div>
        <div class="mb-3">
            <label class="form-label">Xizmat nomi (Ruscha)</label>
            <input type="text" name="title_ru" class="form-control" required value="{{ service.title_ru }}">
        </div>
        <div class="mb-3">
            <label class="form-label">Narxi (USD)</label>
            <input type="number" step="0.01" name="price_usd" class="form-control" required value="{{ service.price_usd }}">
        </div>
        <button type="submit" class="btn btn-success">💾 Saqlash</button>
        <a href="/admin" class="btn btn-secondary">Bekor qilish</a>
    </form>
</div>
</body>
</html>
"""

ORDERS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Buyurtmalar</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
    <h2 class="fw-bold mb-4">📦 Buyurtmalar</h2>
    <a href="/admin" class="btn btn-secondary mb-3">⬅️ Ortga</a>
    {% for order in orders %}
    <div class="card mb-3">
        <div class="card-body">
            <h5 class="card-title">👤 {{ order.full_name }} - 📞 {{ order.phone_number }}</h5>
            <p class="mb-1">🛒 {{ order.service_title }} | 💵 ${{ '%.2f'|format(order.price_usd) }}</p>
            <span class="badge bg-{{ 'success' if order.status == 'paid' else 'warning' }}">{{ order.status }}</span>
        </div>
    </div>
    {% endfor %}
</div>
</body>
</html>
"""

# --- Routes ---
@app.route("/admin")
def admin_panel():
    async def fetch_services():
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT id, title_uz, title_ru, price_usd FROM services ORDER BY id")
        await conn.close()
        return rows
    services = asyncio.run(fetch_services())
    return render_template_string(HTML_TEMPLATE, services=services)

@app.route("/admin/add", methods=["GET", "POST"])
def add_service():
    async def insert_service(data):
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO services (title_uz, title_ru, price_usd)
            VALUES ($1, $2, $3)
        """, data['title_uz'], data['title_ru'], float(data['price_usd']))
        await conn.close()

    if request.method == "POST":
        asyncio.run(insert_service(request.form))
        return redirect(url_for('admin_panel'))

    empty = {"title_uz": "", "title_ru": "", "price_usd": 0.0}
    return render_template_string(FORM_TEMPLATE, service=empty, is_new=True)

@app.route("/admin/edit/<int:service_id>", methods=["GET", "POST"])
def edit_service(service_id):
    async def fetch_service():
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow("SELECT * FROM services WHERE id = $1", service_id)
        await conn.close()
        return row

    async def update_service(data):
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            UPDATE services SET title_uz=$1, title_ru=$2, price_usd=$3 WHERE id=$4
        """, data['title_uz'], data['title_ru'], float(data['price_usd']), service_id)
        await conn.close()

    if request.method == "POST":
        asyncio.run(update_service(request.form))
        return redirect(url_for('admin_panel'))

    service = asyncio.run(fetch_service())
    return render_template_string(FORM_TEMPLATE, service=service, is_new=False)

@app.route("/admin/delete/<int:service_id>")
def delete_service(service_id):
    async def delete():
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("DELETE FROM services WHERE id = $1", service_id)
        await conn.close()
    asyncio.run(delete())
    return redirect(url_for('admin_panel'))

@app.route("/admin/orders")
def show_orders():
    async def fetch_orders():
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT o.id, u.full_name, u.phone_number, s.title_uz AS service_title, s.price_usd, o.status
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN services s ON o.service_id = s.id
            ORDER BY o.id DESC
        """)
        await conn.close()
        return rows
    orders = asyncio.run(fetch_orders())
    return render_template_string(ORDERS_TEMPLATE, orders=orders)

# --- Run ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
