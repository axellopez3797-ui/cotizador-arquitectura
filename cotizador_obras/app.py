"""
app.py
------
Aplicación Flask principal del Sistema de Cotizaciones y Presupuesto de Obras.

Rutas principales:
    /                   -> Página de inicio (dashboard simple)
    /materiales         -> Listado y alta de materiales
    /cotizador          -> Listado de cotizaciones existentes
    /nueva-cotizacion   -> Formulario para crear una nueva cotización

Para ejecutar:
    1) python database.py      (crea la base de datos y datos de ejemplo)
    2) python app.py           (levanta el servidor local)
    3) Abrir http://127.0.0.1:5000 en el navegador
"""

from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import date
from database import get_connection, init_db, seed_data

app = Flask(__name__)

# Clave secreta necesaria para usar mensajes flash (avisos al usuario).
# En producción esto debería ir en una variable de entorno.
app.secret_key = "dev-secret-key-cambiar-en-produccion"


# ---------------------------------------------------------------------------
# Helper: asegura que la base de datos exista antes de servir peticiones
# ---------------------------------------------------------------------------
def asegurar_base_datos():
    """Crea las tablas si aún no existen (no borra datos existentes)."""
    init_db()


# ---------------------------------------------------------------------------
# RUTA: Página de inicio
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Dashboard simple con accesos rápidos y resumen general."""
    conn = get_connection()
    total_materiales = conn.execute(
        "SELECT COUNT(*) AS total FROM materiales"
    ).fetchone()["total"]
    total_cotizaciones = conn.execute(
        "SELECT COUNT(*) AS total FROM cotizaciones"
    ).fetchone()["total"]
    conn.close()

    return render_template(
        "index.html",
        total_materiales=total_materiales,
        total_cotizaciones=total_cotizaciones,
    )


# ---------------------------------------------------------------------------
# RUTA: Materiales (listado + alta rápida)
# ---------------------------------------------------------------------------
@app.route("/materiales", methods=["GET", "POST"])
def materiales():
    """
    GET  -> Muestra el listado de materiales registrados.
    POST -> Recibe el formulario de alta y crea un nuevo material.
    """
    conn = get_connection()

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        unidad_medida = request.form.get("unidad_medida", "").strip()
        precio_unitario = request.form.get("precio_unitario", "0")
        categoria = request.form.get("categoria", "").strip()

        if nombre and unidad_medida and precio_unitario:
            conn.execute(
                """INSERT INTO materiales (nombre, unidad_medida, precio_unitario, categoria)
                   VALUES (?, ?, ?, ?)""",
                (nombre, unidad_medida, float(precio_unitario), categoria),
            )
            conn.commit()
            flash("Material agregado correctamente.", "success")
        else:
            flash("Todos los campos obligatorios deben completarse.", "danger")

        conn.close()
        return redirect(url_for("materiales"))

    # GET: listado ordenado por categoría y nombre
    lista_materiales = conn.execute(
        "SELECT * FROM materiales ORDER BY categoria, nombre"
    ).fetchall()
    conn.close()

    return render_template("materiales.html", materiales=lista_materiales)


# ---------------------------------------------------------------------------
# RUTA: Cotizador (listado de cotizaciones)
# ---------------------------------------------------------------------------
@app.route("/cotizador")
def cotizador():
    """Muestra el listado de todas las cotizaciones generadas."""
    conn = get_connection()
    cotizaciones = conn.execute(
        "SELECT * FROM cotizaciones ORDER BY fecha DESC"
    ).fetchall()
    conn.close()

    return render_template("cotizador.html", cotizaciones=cotizaciones)


# ---------------------------------------------------------------------------
# RUTA: Nueva cotización
# ---------------------------------------------------------------------------
@app.route("/nueva-cotizacion", methods=["GET", "POST"])
def nueva_cotizacion():
    """
    GET  -> Muestra el formulario de nueva cotización con el catálogo
            de materiales disponible para elegir cantidades.
    POST -> Guarda la cotización (encabezado + detalle) en la base de datos.
    """
    conn = get_connection()

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        proyecto = request.form.get("proyecto", "").strip()
        fecha = request.form.get("fecha") or date.today().isoformat()

        # Listas paralelas enviadas desde el formulario:
        # material_id[]  y  cantidad[]
        material_ids = request.form.getlist("material_id[]")
        cantidades = request.form.getlist("cantidad[]")

        if not cliente or not proyecto:
            flash("Cliente y proyecto son obligatorios.", "danger")
            conn.close()
            return redirect(url_for("nueva_cotizacion"))

        # Crear el encabezado de la cotización con total en 0 (se actualiza después)
        cursor = conn.execute(
            "INSERT INTO cotizaciones (cliente, proyecto, fecha, total) VALUES (?, ?, ?, 0)",
            (cliente, proyecto, fecha),
        )
        cotizacion_id = cursor.lastrowid

        total_general = 0.0

        # Recorremos cada línea de material seleccionada en el formulario
        for material_id, cantidad_str in zip(material_ids, cantidades):
            if not material_id or not cantidad_str:
                continue

            cantidad = float(cantidad_str)
            if cantidad <= 0:
                continue

            material = conn.execute(
                "SELECT * FROM materiales WHERE id = ?", (material_id,)
            ).fetchone()

            if material:
                subtotal = round(material["precio_unitario"] * cantidad, 2)
                total_general += subtotal

                conn.execute(
                    """INSERT INTO detalle_cotizacion
                       (cotizacion_id, material_id, cantidad, subtotal)
                       VALUES (?, ?, ?, ?)""",
                    (cotizacion_id, material_id, cantidad, subtotal),
                )

        # Actualiza el total general en el encabezado de la cotización
        conn.execute(
            "UPDATE cotizaciones SET total = ? WHERE id = ?",
            (round(total_general, 2), cotizacion_id),
        )
        conn.commit()
        conn.close()

        flash("Cotización creada correctamente.", "success")
        return redirect(url_for("cotizador"))

    # GET: cargar catálogo de materiales para armar el formulario
    materiales_disponibles = conn.execute(
        "SELECT * FROM materiales ORDER BY categoria, nombre"
    ).fetchall()
    conn.close()

    return render_template(
        "nueva_cotizacion.html",
        materiales=materiales_disponibles,
        fecha_hoy=date.today().isoformat(),
    )


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asegurar_base_datos()
    app.run(debug=True)
