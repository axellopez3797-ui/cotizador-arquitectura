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

import io

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
from datetime import date
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

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
# RUTA: Generación de PDF de cotización
# ---------------------------------------------------------------------------
@app.route("/cotizacion/<int:cotizacion_id>/pdf")
def generar_pdf_cotizacion(cotizacion_id):
    """Genera la cotización en formato PDF usando ReportLab y la devuelve en memoria."""
    conn = get_connection()
    cotizacion = conn.execute(
        "SELECT * FROM cotizaciones WHERE id = ?",
        (cotizacion_id,),
    ).fetchone()

    if not cotizacion:
        conn.close()
        abort(404)

    detalle = conn.execute(
        """
        SELECT m.nombre AS material, m.unidad_medida AS unidad, dc.cantidad,
               m.precio_unitario, dc.subtotal
        FROM detalle_cotizacion dc
        JOIN materiales m ON m.id = dc.material_id
        WHERE dc.cotizacion_id = ?
        ORDER BY m.nombre
        """,
        (cotizacion_id,),
    ).fetchall()
    conn.close()

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleCentered",
            parent=styles["Title"],
            alignment=1,
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=6,
            textColor=colors.HexColor("#1F2937"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubtitleCentered",
            parent=styles["Heading2"],
            alignment=1,
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyText",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=1,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="FooterItalic",
            parent=styles["Italic"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#4B5563"),
            alignment=1,
            spaceTop=12,
        )
    )

    elementos = []
    elementos.append(Paragraph("COTIZACIÓN DE OBRA Y PRESUPUESTO", styles["TitleCentered"]))
    elementos.append(
        Paragraph(
            "Taller de Arquitectura — Área de Sistemas e Innovación Digital",
            styles["SubtitleCentered"],
        )
    )
    elementos.append(Spacer(1, 18))

    texto_introduccion = (
        "Por medio de la presente, se hace entrega de la estimación de costos "
        f"correspondiente al proyecto {cotizacion['proyecto']}. La cotización calculada "
        f"para el cliente {cotizacion['cliente']} con fecha {cotizacion['fecha']} asciende "
        f"a un total aproximado de ${float(cotizacion['total']):.2f} MXN, desglosada a "
        "continuación según los materiales e insumos requeridos para su ejecución."
    )
    elementos.append(Paragraph(texto_introduccion, styles["BodyText"]))

    tabla_datos = [["Material", "Cantidad", "Unidad", "Precio Unitario", "Subtotal"]]
    for fila in detalle:
        tabla_datos.append(
            [
                fila["material"],
                f"{float(fila['cantidad']):.2f}",
                fila["unidad"],
                f"${float(fila['precio_unitario']):.2f}",
                f"${float(fila['subtotal']):.2f}",
            ]
        )

    tabla = Table(tabla_datos, colWidths=[190, 70, 60, 90, 90])
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("PADDING", (0, 1), (-1, -1), 6),
            ]
        )
    )
    elementos.append(tabla)
    elementos.append(Spacer(1, 20))
    elementos.append(
        Paragraph(
            "Vigencia del presupuesto: 15 días. Los costos de insumos pueden variar por ajustes del mercado y disponibilidad de materiales.",
            styles["FooterItalic"],
        )
    )

    pdf.build(elementos)
    buffer.seek(0)
    return send_file(buffer, download_name=f"cotizacion_{cotizacion_id}.pdf", mimetype="application/pdf")


# ---------------------------------------------------------------------------
# RUTA: Descargar cotización en PDF formal
# ---------------------------------------------------------------------------
@app.route("/descargar_pdf/<int:cotizacion_id>")
def descargar_pdf(cotizacion_id):
    """Genera y devuelve la cotización en PDF formal usando ReportLab."""
    conn = get_connection()
    cotizacion = conn.execute(
        "SELECT * FROM cotizaciones WHERE id = ?",
        (cotizacion_id,),
    ).fetchone()

    if not cotizacion:
        conn.close()
        abort(404)

    detalle = conn.execute(
        """
        SELECT m.nombre AS material, m.unidad_medida AS unidad,
               dc.cantidad, m.precio_unitario, dc.subtotal
        FROM detalle_cotizacion dc
        JOIN materiales m ON m.id = dc.material_id
        WHERE dc.cotizacion_id = ?
        ORDER BY m.nombre
        """,
        (cotizacion_id,),
    ).fetchall()
    conn.close()

    monto_total = float(cotizacion["total"])
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=30,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleCentered",
            parent=styles["Title"],
            alignment=1,
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubtitleCentered",
            parent=styles["Heading2"],
            alignment=1,
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="IntroFormal",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            alignment=1,
            textColor=colors.HexColor("#1F2937"),
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="FooterItalic",
            parent=styles["Italic"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#4B5563"),
            alignment=1,
            spaceTop=12,
        )
    )

    story = []
    story.append(Paragraph("COTIZACIÓN DE OBRA Y PRESUPUESTO", styles["TitleCentered"]))
    story.append(
        Paragraph(
            "Taller de Arquitectura — Área de Sistemas e Innovación Digital",
            styles["SubtitleCentered"],
        )
    )
    story.append(Spacer(1, 18))

    intro = (
        "Por medio de la presente, se hace entrega de la estimación de costos "
        f"correspondiente al proyecto {cotizacion['proyecto']}. La cotización calculada "
        f"para el cliente {cotizacion['cliente']} con fecha {cotizacion['fecha']} asciende "
        f"a un total aproximado de ${monto_total:,.2f} MXN, desglosada a continuación "
        "según los materiales e insumos requeridos para su ejecución."
    )
    story.append(Paragraph(intro, styles["IntroFormal"]))

    table_data = [["Material", "Cantidad", "Unidad", "Precio Unitario", "Subtotal"]]
    for item in detalle:
        table_data.append(
            [
                item["material"],
                f"{float(item['cantidad']):.2f}",
                item["unidad"],
                f"${float(item['precio_unitario']):,.2f}",
                f"${float(item['subtotal']):,.2f}",
            ]
        )

    table = Table(table_data, colWidths=[190, 70, 60, 90, 90])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("PADDING", (0, 1), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 18))
    story.append(
        Paragraph(
            "Vigencia del presupuesto: 15 días. Los costos de insumos pueden variar por ajustes del mercado y disponibilidad de materiales.",
            styles["FooterItalic"],
        )
    )

    pdf.build(story)
    buffer.seek(0)
    return send_file(buffer, download_name="Cotizacion.pdf", mimetype="application/pdf")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asegurar_base_datos()
    app.run(debug=True)
