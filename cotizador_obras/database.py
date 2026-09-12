"""
database.py
------------
Módulo encargado de la creación e inicialización de la base de datos SQLite
para el Sistema de Cotizaciones y Presupuesto de Obras.

Ejecutar directamente este archivo (python database.py) para crear/actualizar
el archivo 'cotizaciones.db' con las tablas necesarias.
"""

import sqlite3
import os

# Nombre del archivo de base de datos (se crea en la raíz del proyecto)
DB_NAME = "cotizaciones.db"


def get_connection():
    """
    Crea y retorna una conexión a la base de datos SQLite.
    row_factory permite acceder a las columnas por nombre (como diccionario).
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    # Activa las claves foráneas (SQLite las trae desactivadas por defecto)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """
    Crea las tablas del sistema si no existen todavía.
    Se puede ejecutar múltiples veces sin duplicar información.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Tabla de materiales / insumos de construcción
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materiales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            unidad_medida TEXT NOT NULL,
            precio_unitario REAL NOT NULL,
            categoria TEXT
        )
    """)

    # Tabla de cotizaciones (encabezado)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL,
            proyecto TEXT NOT NULL,
            fecha TEXT NOT NULL,
            total REAL DEFAULT 0
        )
    """)

    # Tabla de detalle de cotización (líneas de materiales por cotización)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detalle_cotizacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cotizacion_id INTEGER NOT NULL,
            material_id INTEGER NOT NULL,
            cantidad REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (cotizacion_id) REFERENCES cotizaciones (id)
                ON DELETE CASCADE,
            FOREIGN KEY (material_id) REFERENCES materiales (id)
                ON DELETE RESTRICT
        )
    """)

    conn.commit()
    conn.close()
    print(f"Base de datos '{DB_NAME}' inicializada correctamente.")


def seed_data():
    """
    Inserta algunos materiales de ejemplo si la tabla está vacía.
    Útil para probar la aplicación sin tener que cargar datos manualmente.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM materiales")
    total = cursor.fetchone()["total"]

    if total == 0:
        materiales_ejemplo = [
            ("Cemento gris (bulto 50kg)", "bulto", 235.00, "Cemento y agregados"),
            ("Arena de río", "m3", 450.00, "Cemento y agregados"),
            ("Grava 3/4", "m3", 480.00, "Cemento y agregados"),
            ("Varilla 3/8 (12m)", "pieza", 145.00, "Acero"),
            ("Block de concreto 15x20x40", "pieza", 14.50, "Mampostería"),
            ("Lámina galvanizada cal. 26", "pieza", 320.00, "Techumbre"),
            ("Pintura vinílica (cubeta 19L)", "cubeta", 890.00, "Acabados"),
            ("Cable eléctrico calibre 12", "m", 12.50, "Instalaciones"),
        ]
        cursor.executemany("""
            INSERT INTO materiales (nombre, unidad_medida, precio_unitario, categoria)
            VALUES (?, ?, ?, ?)
        """, materiales_ejemplo)
        conn.commit()
        print(f"Se insertaron {len(materiales_ejemplo)} materiales de ejemplo.")
    else:
        print("La tabla 'materiales' ya contiene datos, no se insertó nada.")

    conn.close()


if __name__ == "__main__":
    # Permite ejecutar: python database.py
    init_db()
    seed_data()
